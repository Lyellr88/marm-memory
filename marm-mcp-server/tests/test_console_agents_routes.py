"""Route contract, loopback guard, probe wiring, and key secrecy for the /agents endpoints."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_mcp_probe import FakeMcp, stdio_env

from marm_mcp_server.console.endpoints import agents, setup
from marm_mcp_server.services import client_config, key_management, mcp_probe

SECRET = "sk-marm-route-secret"
REAL_WHICH = shutil.which
REAL_APPDATA = os.environ.get("APPDATA")


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(client_config, "_home", lambda: tmp_path)
    monkeypatch.setattr(client_config, "_platform", lambda: "win32")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("CLINE_DIR", raising=False)
    monkeypatch.delenv("CLINE_DATA_DIR", raising=False)
    monkeypatch.delenv("CLINE_MCP_SETTINGS_PATH", raising=False)
    monkeypatch.setattr(client_config.shutil, "which", lambda name: None)
    monkeypatch.setattr(key_management, "read_managed_key", lambda: "")
    return tmp_path


@pytest.fixture
def app_client(isolated_home, monkeypatch):
    monkeypatch.setattr(
        "marm_mcp_server.core.runtime_manager.inspect_runtime",
        lambda: {"state": "ready", "metadata": {"port": 8001}},
    )
    monkeypatch.setattr("marm_mcp_server.config.settings.MARM_API_KEY", "")

    app = FastAPI()
    app.include_router(agents.router)
    with TestClient(app) as test_client:
        yield test_client


def detect(home, folder=".cursor"):
    (home / folder).mkdir(parents=True, exist_ok=True)


def entry_file(home):
    return home / ".cursor" / "mcp.json"


def write_entry(home, entry):
    detect(home)
    entry_file(home).write_text(json.dumps({"mcpServers": {"marm-memory": entry}}))


# --- List and scope ---------------------------------------------------------------------


def test_list_agents_shape(app_client, isolated_home):
    detect(isolated_home)
    response = app_client.get("/api/connections/agents")
    assert response.status_code == 200
    body = response.json()

    assert body["auth_required"] is False
    assert body["configure_allowed"] is True
    assert body["configure_blocked_reason"] is None
    assert [c["id"] for c in body["clients"]] == client_config.CLIENT_IDS
    cursor = next(c for c in body["clients"] if c["id"] == "cursor")
    assert cursor["detected"] is True
    assert cursor["transports"] == ["http", "stdio", "docker-stdio"]
    assert cursor["scopes"] == ["user", "project"]
    assert cursor["user"]["state"] == "missing"
    assert cursor["user"]["config_path"] == str(entry_file(isolated_home))
    assert set(cursor) == {
        "id",
        "label",
        "detected",
        "transports",
        "scopes",
        "user",
        "skill",
        "notes",
        "unavailable",
    }
    cline = next(c for c in body["clients"] if c["id"] == "cline")
    assert cline["label"] == "Cline CLI"
    assert cline["scopes"] == ["user"]
    hermes = next(c for c in body["clients"] if c["id"] == "hermes")
    assert hermes["label"] == "Hermes Agent"
    assert hermes["scopes"] == ["user"]
    grok = next(c for c in body["clients"] if c["id"] == "grok")
    assert grok["label"] == "Grok Build"
    assert grok["scopes"] == ["user", "project"]


def test_list_reports_the_bound_state(app_client, monkeypatch):
    monkeypatch.setattr(agents, "_loopback_only", lambda: False)

    body = app_client.get("/api/connections/agents").json()

    assert body["configure_allowed"] is False
    assert body["configure_blocked_reason"]


def test_old_connection_routes_are_gone(app_client):
    assert app_client.get("/api/connections").status_code == 404
    response = app_client.post("/api/connections/cursor/configure", json={})
    assert response.status_code == 404


def test_scope_route_reads_user_and_project_files(app_client, isolated_home):
    project = isolated_home / "repo"
    project.mkdir()
    (project / ".cursor").mkdir()
    (project / ".cursor" / "mcp.json").write_text(
        json.dumps(
            {"mcpServers": {"marm-memory": {"url": "http://127.0.0.1:8001/mcp"}}}
        )
    )

    user = app_client.get("/api/connections/agents/cursor/scope").json()
    scoped = app_client.get(
        "/api/connections/agents/cursor/scope",
        params={"scope": "project", "project": str(project)},
    ).json()

    assert user["state"] == "missing"
    assert user["config_exists"] is False
    assert scoped["state"] == "configured"
    assert scoped["transport_detected"] == "http"
    assert scoped["project"] == str(project)
    assert scoped["config_path"] == str(project / ".cursor" / "mcp.json")
    assert scoped["current_entry"] == {"url": "http://127.0.0.1:8001/mcp"}
    assert set(scoped) == {
        "scope",
        "project",
        "config_path",
        "config_exists",
        "state",
        "transport_detected",
        "current_entry",
    }


def test_scope_route_errors(app_client, isolated_home):
    missing = str(isolated_home / "nope")
    assert (
        app_client.get(
            "/api/connections/agents/cursor/scope",
            params={"scope": "project", "project": missing},
        ).status_code
        == 422
    )
    assert (
        app_client.get(
            "/api/connections/agents/cursor/scope", params={"scope": "project"}
        ).status_code
        == 422
    )
    assert (
        app_client.get(
            "/api/connections/agents/cursor/scope", params={"scope": "galaxy"}
        ).status_code
        == 422
    )
    assert app_client.get("/api/connections/agents/nope/scope").status_code == 404


# --- Configure and remove -----------------------------------------------------------------


def test_dry_run_returns_the_contract_and_writes_nothing(app_client, isolated_home):
    detect(isolated_home)
    response = app_client.post(
        "/api/connections/agents/cursor/configure",
        json={"transport": "http", "scope": "user", "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "client": "cursor",
        "transport": "http",
        "scope": "user",
        "config_path": str(entry_file(isolated_home)),
        "action": "create",
        "entry": {"url": "http://127.0.0.1:8001/mcp"},
        "backup_path": None,
        "method": "file",
        "notes": [],
    }
    assert not entry_file(isolated_home).exists()


def test_configure_writes_and_reads_back(app_client, isolated_home):
    detect(isolated_home)
    response = app_client.post(
        "/api/connections/agents/cursor/configure",
        json={"transport": "stdio", "scope": "user", "dry_run": False},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["written"] is True
    assert body["verified"] is True
    assert json.loads(entry_file(isolated_home).read_text())["mcpServers"][
        "marm-memory"
    ] == {"command": "marm-mcp-stdio", "args": []}


def test_configure_project_scope(app_client, isolated_home):
    project = isolated_home / "repo"
    project.mkdir()

    response = app_client.post(
        "/api/connections/agents/claude/configure",
        json={"transport": "http", "scope": "project", "project": str(project)},
    )

    assert response.status_code == 200
    assert response.json()["config_path"] == str(project / ".mcp.json")
    assert (project / ".mcp.json").is_file()


def test_every_post_is_403_off_loopback(app_client, monkeypatch):
    monkeypatch.setattr(setup, "_loopback_only", lambda: False)
    bodies = {
        "configure": {"transport": "http", "scope": "user", "dry_run": True},
        "remove": {"scope": "user", "dry_run": True},
        "test": {"scope": "user"},
        "skill": None,
    }
    for action, body in bodies.items():
        response = app_client.post(
            f"/api/connections/agents/cursor/{action}",
            **({"json": body} if body is not None else {}),
        )
        assert response.status_code == 403, action


def test_unknown_client_is_404_on_every_post(app_client):
    for action, body in {
        "configure": {"dry_run": True},
        "remove": {},
        "test": {},
        "skill": None,
    }.items():
        response = app_client.post(
            f"/api/connections/agents/nope/{action}",
            **({"json": body} if body is not None else {}),
        )
        assert response.status_code == 404, action


@pytest.mark.parametrize(
    "body",
    [
        {"transport": "grpc"},
        {"scope": "galaxy"},
        {"scope": "project"},
        {"scope": "project", "project": "relative"},
    ],
)
def test_bad_transport_scope_or_project_is_422(app_client, isolated_home, body):
    detect(isolated_home)
    response = app_client.post(
        "/api/connections/agents/cursor/configure", json={"dry_run": True, **body}
    )
    assert response.status_code == 422


def test_409_manual_client_with_auth_suggests_stdio(
    app_client, isolated_home, monkeypatch
):
    detect(isolated_home, ".gemini/config")
    monkeypatch.setattr("marm_mcp_server.config.settings.MARM_API_KEY", SECRET)
    response = app_client.post(
        "/api/connections/agents/antigravity/configure", json={"dry_run": False}
    )

    assert response.status_code == 409
    assert SECRET not in response.text
    assert "STDIO" in response.json()["detail"]


def test_409_unreadable_file(app_client, isolated_home):
    detect(isolated_home)
    entry_file(isolated_home).write_text("[]")

    response = app_client.post(
        "/api/connections/agents/cursor/configure", json={"dry_run": False}
    )

    assert response.status_code == 409
    assert entry_file(isolated_home).read_text() == "[]"


def test_409_os_error_leaves_no_tmp(app_client, isolated_home, monkeypatch):
    detect(isolated_home)

    def locked(src, dst):
        raise PermissionError(13, "locked")

    monkeypatch.setattr(client_config.os, "replace", locked)
    response = app_client.post(
        "/api/connections/agents/cursor/configure", json={"dry_run": False}
    )

    assert response.status_code == 409
    assert "Could not write" in response.json()["detail"]
    assert not (isolated_home / ".cursor" / "mcp.json.tmp").exists()


def test_remove_deletes_only_marms_entry(app_client, isolated_home):
    detect(isolated_home)
    entry_file(isolated_home).write_text(
        json.dumps(
            {"mcpServers": {"a": {"url": "x"}, "marm-memory": {"url": "http://y"}}}
        )
    )

    dry = app_client.post(
        "/api/connections/agents/cursor/remove", json={"scope": "user", "dry_run": True}
    ).json()
    real = app_client.post(
        "/api/connections/agents/cursor/remove", json={"scope": "user"}
    ).json()

    assert dry["action"] == "remove"
    assert "written" not in dry
    assert real["written"] is True
    assert real["verified"] is True
    assert set(real) == {
        "client",
        "config_path",
        "action",
        "backup_path",
        "method",
        "written",
        "verified",
    }
    assert json.loads(entry_file(isolated_home).read_text()) == {
        "mcpServers": {"a": {"url": "x"}}
    }


# --- Test connection ------------------------------------------------------------------------


def test_test_route_without_an_entry(app_client, isolated_home):
    response = app_client.post(
        "/api/connections/agents/cursor/test", json={"scope": "user"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False
    assert body["error"]["kind"] == "missing_entry"
    assert set(body) == {"ok", "transport", "tools", "latency_ms", "error"}


def test_test_route_unreadable_file_is_missing_entry(app_client, isolated_home):
    detect(isolated_home)
    entry_file(isolated_home).write_text("{nope")

    body = app_client.post(
        "/api/connections/agents/cursor/test", json={"scope": "user"}
    ).json()

    assert body["error"]["kind"] == "missing_entry"


def test_test_route_unrecognised_entry_is_unsupported(app_client, isolated_home):
    write_entry(isolated_home, {"nothing": "useful"})

    body = app_client.post(
        "/api/connections/agents/cursor/test", json={"scope": "user"}
    ).json()

    assert body["error"]["kind"] == "unsupported"


def test_test_route_http_resolves_the_key_server_side(
    app_client, isolated_home, monkeypatch
):
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    with FakeMcp(key=SECRET, tools=7) as fake:
        write_entry(
            isolated_home,
            {
                "url": fake.url,
                "headers": {"Authorization": "Bearer ${env:MARM_API_KEY}"},
            },
        )

        response = app_client.post(
            "/api/connections/agents/cursor/test", json={"scope": "user"}
        )

    body = response.json()
    assert body["ok"] is True
    assert body["transport"] == "http"
    assert body["tools"] == 7
    assert body["error"] is None
    assert fake.requests[0]["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in response.text
    assert SECRET not in entry_file(isolated_home).read_text()


@pytest.mark.parametrize(
    "ref", ["${MARM_API_KEY}", "${env:MARM_API_KEY}", "${input:marm-api-key}"]
)
def test_test_route_resolves_every_key_reference_form(
    app_client, isolated_home, monkeypatch, ref
):
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    with FakeMcp(key=SECRET) as fake:
        write_entry(
            isolated_home,
            {"url": fake.url, "headers": {"Authorization": f"Bearer {ref}"}},
        )
        body = app_client.post(
            "/api/connections/agents/cursor/test", json={"scope": "user"}
        ).json()

    assert body["ok"] is True


def test_test_route_resolves_codex_bearer_token_env_var(
    app_client, isolated_home, monkeypatch
):
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    with FakeMcp(key=SECRET) as fake:
        (isolated_home / ".codex").mkdir()
        (isolated_home / ".codex" / "config.toml").write_text(
            f'[mcp_servers.marm-memory]\nurl = "{fake.url}"\n'
            'bearer_token_env_var = "MARM_API_KEY"\n'
        )
        response = app_client.post(
            "/api/connections/agents/codex/test", json={"scope": "user"}
        )

    pytest.importorskip("tomllib")
    assert response.json()["ok"] is True
    assert SECRET not in response.text


def test_grok_configure_then_test_resolves_the_bearer_env_var(
    app_client, isolated_home, monkeypatch
):
    pytest.importorskip("tomllib")
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    (isolated_home / ".grok").mkdir()
    with FakeMcp(key=SECRET) as fake:
        (isolated_home / ".grok" / "config.toml").write_text(
            f'[mcp_servers.marm-memory]\nurl = "{fake.url}"\n'
            'bearer_token_env_var = "MARM_API_KEY"\n'
        )
        response = app_client.post(
            "/api/connections/agents/grok/test", json={"scope": "user"}
        )

    assert response.json()["ok"] is True
    assert SECRET not in response.text


def test_grok_configure_writes_its_toml_and_the_skill_lands_in_grok_skills(
    app_client, isolated_home
):
    (isolated_home / ".grok").mkdir()

    configured = app_client.post(
        "/api/connections/agents/grok/configure", json={"dry_run": False}
    )
    skill = app_client.post("/api/connections/agents/grok/skill")

    assert configured.status_code == 200
    assert configured.json()["verified"] is True
    assert (
        "[mcp_servers.marm-memory]"
        in (isolated_home / ".grok" / "config.toml").read_text()
    )
    assert skill.json()["target"] == str(
        isolated_home / ".grok" / "skills" / "marm-init" / "SKILL.md"
    )


def test_hermes_configure_then_remove_round_trip(app_client, isolated_home):
    home = isolated_home / "AppData" / "Local" / "hermes"
    home.mkdir(parents=True)
    config = home / "config.yaml"
    config.write_text("# mine\nmodel: gpt-x\n")

    configured = app_client.post(
        "/api/connections/agents/hermes/configure", json={"dry_run": False}
    )
    removed = app_client.post(
        "/api/connections/agents/hermes/remove", json={"scope": "user"}
    )

    assert configured.status_code == 200
    assert configured.json()["verified"] is True
    assert configured.json()["config_path"] == str(config)
    assert removed.status_code == 200
    assert removed.json()["verified"] is True
    assert config.read_text().startswith("# mine\nmodel: gpt-x\n")


def test_hermes_test_route_resolves_the_key_reference_in_headers(
    app_client, isolated_home, monkeypatch
):
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    home = isolated_home / "AppData" / "Local" / "hermes"
    home.mkdir(parents=True)
    with FakeMcp(key=SECRET) as fake:
        (home / "config.yaml").write_text(
            "mcp_servers:\n"
            "  marm-memory:\n"
            f'    url: "{fake.url}"\n'
            "    headers:\n"
            '      Authorization: "Bearer ${MARM_API_KEY}"\n'
        )
        response = app_client.post(
            "/api/connections/agents/hermes/test", json={"scope": "user"}
        )

    assert response.json()["ok"] is True
    assert SECRET not in response.text


def test_cline_configure_and_skill_round_trip(app_client, isolated_home):
    (isolated_home / ".cline").mkdir()

    configured = app_client.post(
        "/api/connections/agents/cline/configure", json={"dry_run": False}
    )
    skill = app_client.post("/api/connections/agents/cline/skill")
    removed = app_client.post(
        "/api/connections/agents/cline/remove", json={"scope": "user"}
    )

    settings = (
        isolated_home / ".cline" / "data" / "settings" / "cline_mcp_settings.json"
    )
    assert configured.status_code == 200
    assert configured.json()["verified"] is True
    assert skill.json()["target"] == str(
        isolated_home / ".cline" / "skills" / "marm-init" / "SKILL.md"
    )
    assert removed.json()["verified"] is True
    assert json.loads(settings.read_text())["mcpServers"] == {}


def test_hermes_skill_installs_under_hermes_home(app_client, isolated_home):
    (isolated_home / "AppData" / "Local" / "hermes").mkdir(parents=True)

    response = app_client.post("/api/connections/agents/hermes/skill")

    target = (
        isolated_home
        / "AppData"
        / "Local"
        / "hermes"
        / "skills"
        / "marm-init"
        / "SKILL.md"
    )
    assert response.json() == {"state": "installed", "target": str(target)}


def test_test_route_wrong_key_is_unauthorized_without_echo(
    app_client, isolated_home, monkeypatch
):
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    with FakeMcp(key="sk-a-different-key") as fake:
        write_entry(
            isolated_home,
            {"url": fake.url, "headers": {"Authorization": "Bearer ${MARM_API_KEY}"}},
        )
        response = app_client.post(
            "/api/connections/agents/cursor/test", json={"scope": "user"}
        )

    assert response.json()["error"]["kind"] == "unauthorized"
    assert SECRET not in response.text


def test_test_route_never_sends_the_key_to_a_non_local_host(
    app_client, isolated_home, monkeypatch
):
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    seen: list[dict] = []

    def capture(url, headers=None, timeout=5.0):
        seen.append(headers)
        return {
            "ok": False,
            "transport": "http",
            "tools": 0,
            "latency_ms": 1,
            "error": {"kind": "unauthorized", "detail": "The server rejected the key."},
        }

    monkeypatch.setattr(mcp_probe, "probe_http", capture)
    write_entry(
        isolated_home,
        {
            "url": "https://mcp.example.com/mcp",
            "headers": {"Authorization": "Bearer ${MARM_API_KEY}"},
        },
    )

    response = app_client.post(
        "/api/connections/agents/cursor/test", json={"scope": "user"}
    )

    assert seen == [{"Authorization": "Bearer ${MARM_API_KEY}"}]
    assert "only sent to a local address" in response.json()["error"]["detail"]
    assert SECRET not in response.text


def test_test_route_refused(app_client, isolated_home):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    write_entry(isolated_home, {"url": f"http://127.0.0.1:{port}/mcp"})

    body = app_client.post(
        "/api/connections/agents/cursor/test", json={"scope": "user"}
    ).json()

    assert body["error"]["kind"] == "refused"


def test_test_route_project_scope_reads_the_project_file(app_client, isolated_home):
    project = isolated_home / "repo"
    project.mkdir()
    with FakeMcp(tools=4) as fake:
        (project / ".mcp.json").write_text(
            json.dumps(
                {"mcpServers": {"marm-memory": {"type": "http", "url": fake.url}}}
            )
        )
        body = app_client.post(
            "/api/connections/agents/claude/test",
            json={"scope": "project", "project": str(project)},
        ).json()

    assert body["ok"] is True
    assert body["tools"] == 4


@pytest.mark.slow_stdio
def test_test_route_stdio_runs_the_real_server_from_the_file_entry(
    app_client, isolated_home, monkeypatch
):
    monkeypatch.setattr(shutil, "which", REAL_WHICH)
    env = stdio_env(isolated_home)
    if REAL_APPDATA:
        env["APPDATA"] = REAL_APPDATA
    write_entry(
        isolated_home,
        {
            "command": sys.executable,
            "args": ["-m", "marm_mcp_server.server_stdio"],
            "env": {
                k: env[k]
                for k in env
                if k.startswith("MARM_") or k in {"HOME", "USERPROFILE", "APPDATA"}
            },
        },
    )

    body = app_client.post(
        "/api/connections/agents/cursor/test", json={"scope": "user"}
    ).json()

    assert body["error"] is None
    assert body["ok"] is True
    assert body["transport"] == "stdio"
    assert body["tools"] == 16


def test_test_route_stdio_spawn_failure(app_client, isolated_home):
    write_entry(
        isolated_home, {"command": str(isolated_home / "missing-binary"), "args": []}
    )

    body = app_client.post(
        "/api/connections/agents/cursor/test", json={"scope": "user"}
    ).json()

    assert body["transport"] == "stdio"
    assert body["error"]["kind"] == "spawn_failed"


# --- Skill install -------------------------------------------------------------------------------


def test_skill_install_then_refresh(app_client, isolated_home):
    first = app_client.post("/api/connections/agents/antigravity/skill")
    second = app_client.post("/api/connections/agents/antigravity/skill")

    target = isolated_home / ".gemini" / "config" / "skills" / "marm-init" / "SKILL.md"
    assert first.status_code == 200
    assert first.json() == {"state": "installed", "target": str(target)}
    assert second.json()["state"] == "refreshed"
    assert target.is_file()
    agent = next(
        c
        for c in app_client.get("/api/connections/agents").json()["clients"]
        if c["id"] == "antigravity"
    )
    assert agent["skill"] == {"supported": True, "installed": True}


def test_skill_install_error_state_carries_the_detail(app_client, isolated_home):
    (isolated_home / ".kiro").write_text("a file where the agent dir should be")

    response = app_client.post("/api/connections/agents/kiro/skill")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "error"
    assert body["detail"]


def test_skill_install_is_409_for_agents_without_support(app_client):
    for client_id in ("cursor", "vscode", "windsurf", "claude-desktop"):
        response = app_client.post(f"/api/connections/agents/{client_id}/skill")
        assert response.status_code == 409, client_id


# --- Key value never leaks ----------------------------------------------------------------------------


def test_key_value_never_in_any_response(app_client, isolated_home, monkeypatch):
    monkeypatch.setattr("marm_mcp_server.config.settings.MARM_API_KEY", SECRET)
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    detect(isolated_home)
    responses = [
        app_client.get("/api/connections/agents"),
        app_client.get("/api/connections/agents/cursor/scope"),
        app_client.post(
            "/api/connections/agents/cursor/configure", json={"dry_run": True}
        ),
        app_client.post("/api/connections/agents/cursor/configure", json={}),
    ]
    assert SECRET not in entry_file(isolated_home).read_text()
    responses += [
        app_client.post("/api/connections/agents/cursor/test", json={}),
        app_client.post("/api/connections/agents/cursor/remove", json={}),
    ]
    assert responses[0].json()["auth_required"] is True
    for response in responses:
        assert SECRET not in response.text
