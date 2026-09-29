"""Setup routes: overview, settings, runtime restart job, loopback guard, key secrecy."""

from __future__ import annotations

import json
import os
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marm_mcp_server.config import settings as marm_settings
from marm_mcp_server.config import user_settings
from marm_mcp_server.console import mcp_client, runtime_control
from marm_mcp_server.console.endpoints import setup
from marm_mcp_server.console.terminal.router import HOST_ENV
from marm_mcp_server.core import runtime_flags, runtime_manager
from marm_mcp_server.services import client_config, key_management, skill_install

SECRET = "sk-marm-setup-secret-value"


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name in [s.env for s in user_settings.SETTINGS] + [
        user_settings.SHADOW_ENV,
        "MARM_TRANSPORT",
    ]:
        # setenv first so teardown also removes a var the overlay creates later.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.delenv("MARM_SETTINGS_PATH", raising=False)
    monkeypatch.delenv(HOST_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setattr(user_settings, "_home", lambda: tmp_path)
    monkeypatch.setattr(user_settings, "_in_container", lambda: False)
    monkeypatch.setattr(client_config, "_home", lambda: tmp_path)
    monkeypatch.setattr(client_config.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        key_management, "managed_key_path", lambda: tmp_path / ".marm" / ".env"
    )
    monkeypatch.setattr(key_management, "read_keychain_key", lambda: "")
    monkeypatch.setattr(marm_settings, "MARM_API_KEY", "")
    monkeypatch.setattr(runtime_flags, "get_bool", lambda key, default: default)
    monkeypatch.setattr(runtime_flags, "saved_runtime_preset", lambda: (None, None))
    return tmp_path


@pytest.fixture
def runtime(monkeypatch):
    state: dict = {
        "inspect": {
            "state": "ready",
            "managed": True,
            "metadata": {"port": 8123, "profile": "fast"},
        },
        "read": {"profile": "fast", "rate_limit_rpm": 90},
        "calls": [],
    }
    monkeypatch.setattr(runtime_manager, "inspect_runtime", lambda: state["inspect"])
    monkeypatch.setattr(runtime_manager, "read_state", lambda: state["read"])

    def stop(**kwargs):
        state["calls"].append(("stop", kwargs))
        return True

    def start(**kwargs):
        state["calls"].append(("start", kwargs))
        return {"state": "ready"}

    monkeypatch.setattr(runtime_manager, "stop_runtime", stop)
    monkeypatch.setattr(runtime_manager, "start_background", start)
    return state


@pytest.fixture
def client(home, runtime, monkeypatch):
    monkeypatch.setattr(mcp_client, "list_projects", lambda: [{"name": "demo"}])
    runtime_control._jobs.clear()
    app = FastAPI()
    app.include_router(setup.router)
    with TestClient(app) as test_client:
        yield test_client
    runtime_control._jobs.clear()


def wait_for_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/connections/runtime/restart/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.02)
    raise AssertionError("restart job never finished")


def test_overview_reports_a_fully_set_up_machine(client, home) -> None:
    claude_dir = home / ".claude"
    (claude_dir / "skills" / "marm-init").mkdir(parents=True)
    (claude_dir / "skills" / "marm-init" / "SKILL.md").write_text("skill")
    (home / ".gemini" / "config").mkdir(parents=True)
    entry = client_config.build_entry(
        "claude", "http", "http://127.0.0.1:8123/mcp", False
    )
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"marm-memory": entry}}), encoding="utf-8"
    )

    body = client.get("/api/connections/overview").json()

    assert body["version"] == marm_settings.SERVER_VERSION
    assert body["runtime"] == {
        "state": "ready",
        "managed": True,
        "url": "http://127.0.0.1:8123/mcp",
        "profile": "fast",
    }
    assert body["auth"] == {"mode": "local", "key_file_exists": False}
    assert body["skills_installed"] == 1
    assert body["agents"]["detected"] >= 2
    assert body["agents"]["connected"] == 1
    assert [(c["id"], c["done"]) for c in body["checklist"]] == [
        ("installed", True),
        ("runtime", True),
        ("agents", True),
        ("project", True),
    ]
    assert all(c["label"] and c["detail"] for c in body["checklist"])


def test_overview_on_an_empty_stopped_machine(client, runtime) -> None:
    runtime["inspect"] = {"state": "stopped", "managed": False}

    body = client.get("/api/connections/overview").json()

    assert body["runtime"]["state"] == "stopped"
    assert body["runtime"]["managed"] is False
    assert body["runtime"]["url"] == f"http://127.0.0.1:{marm_settings.SERVER_PORT}/mcp"
    detected = [
        c
        for c in client_config.list_agents(body["runtime"]["url"], False)
        if c["detected"]
    ]
    assert body["agents"] == {"connected": 0, "detected": len(detected)}
    assert body["skills_installed"] == 0
    steps = {c["id"]: c for c in body["checklist"]}
    assert [c["done"] for c in body["checklist"]] == [True, False, False, False]
    assert steps["project"]["detail"] == "Runtime is not running"


def test_overview_project_step_survives_a_dead_backend(client, monkeypatch) -> None:
    def down():
        raise mcp_client.McpUnavailable("down")

    monkeypatch.setattr(mcp_client, "list_projects", down)

    response = client.get("/api/connections/overview")

    assert response.status_code == 200
    project = response.json()["checklist"][-1]
    assert project["done"] is False


def test_overview_counts_every_skill_agent_and_never_leaks_the_key(
    client, home, monkeypatch
) -> None:
    monkeypatch.setattr(marm_settings, "MARM_API_KEY", SECRET)
    for directory in skill_install.AGENTS.values():
        target = home / directory / "skills" / "marm-init"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("skill")
    (home / ".marm").mkdir()
    (home / ".marm" / ".env").write_text(f"MARM_API_KEY={SECRET}\n")

    response = client.get("/api/connections/overview")

    body = response.json()
    assert body["skills_installed"] == len(skill_install.AGENTS)
    assert body["auth"] == {"mode": "key", "key_file_exists": True}
    assert SECRET not in response.text


def test_settings_defaults_and_group_shape(client) -> None:
    body = client.get("/api/connections/settings").json()

    assert body["path"].endswith("settings.json")
    keys = [i["key"] for g in body["groups"] for i in g["items"]]
    assert len(keys) == 14
    assert set(body["live"]) == {
        "profile",
        "rate_limit_rpm",
        "auto_index_graph",
        "auto_index_concept",
        "llm_enabled",
    }
    assert body["live"]["profile"] == "fast"
    assert body["live"]["rate_limit_rpm"] == 90
    assert all(i["source"] == "default" for g in body["groups"] for i in g["items"])


def test_put_settings_persists_and_returns_the_new_view(client, home) -> None:
    (home / ".marm").mkdir()
    (home / ".marm" / "settings.json").write_text(
        json.dumps({"docker": {"port": 8002}}), encoding="utf-8"
    )

    response = client.put(
        "/api/connections/settings",
        json={"values": {"server.port": 8500, "search.semantic": False}},
    )

    assert response.status_code == 200
    items = {i["key"]: i for g in response.json()["groups"] for i in g["items"]}
    assert (items["server.port"]["value"], items["server.port"]["source"]) == (
        8500,
        "saved",
    )
    assert items["search.semantic"]["value"] is False
    on_disk = json.loads((home / ".marm" / "settings.json").read_text("utf-8"))
    assert on_disk["docker"] == {"port": 8002}
    assert on_disk["server"] == {"port": 8500}
    assert client.get("/api/connections/settings").json() == response.json()


@pytest.mark.parametrize(
    "values",
    [
        {"nope.key": 1},
        {"server.port": 99999},
        {"server.port": "8001"},
        {"graph.auto_index_mode": "turbo"},
        {"search.semantic": "yes"},
    ],
)
def test_put_settings_rejects_bad_input_with_422_and_writes_nothing(
    client, home, values
) -> None:
    response = client.put("/api/connections/settings", json={"values": values})

    assert response.status_code == 422
    assert not (home / ".marm" / "settings.json").exists()


def test_put_settings_write_failure_is_409(client, monkeypatch) -> None:
    def locked(values):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(user_settings, "save", locked)

    response = client.put("/api/connections/settings", json={"values": {}})

    assert response.status_code == 409
    assert "Permission denied" in response.json()["detail"]


def test_require_key_creates_a_managed_key_and_never_returns_it(client, home) -> None:
    response = client.put(
        "/api/connections/settings", json={"values": {"auth.require_key": True}}
    )

    assert response.status_code == 200
    key_file = home / ".marm" / ".env"
    text = key_file.read_text("utf-8")
    secret = text.split("=", 1)[1].strip()
    assert text.startswith("MARM_API_KEY=") and len(secret) >= 16
    every_body = [
        response.text,
        client.get("/api/connections/settings").text,
        client.get("/api/connections/overview").text,
    ]
    assert all(secret not in body for body in every_body)
    assert "auth.require_key" in response.text
    assert client.get("/api/connections/overview").json()["auth"]["key_file_exists"]


def test_require_key_keeps_an_existing_managed_key(client, home) -> None:
    (home / ".marm").mkdir()
    (home / ".marm" / ".env").write_text(f"MARM_API_KEY={SECRET}\n")

    response = client.put(
        "/api/connections/settings", json={"values": {"auth.require_key": True}}
    )

    assert response.status_code == 200
    assert (home / ".marm" / ".env").read_text() == f"MARM_API_KEY={SECRET}\n"
    assert SECRET not in response.text


def test_require_key_failure_is_409_without_the_key(client, monkeypatch) -> None:
    def broken(path=None):
        raise RuntimeError(f"cannot secure {SECRET}")

    monkeypatch.setattr(key_management, "initialize_managed_key", broken)

    response = client.put(
        "/api/connections/settings",
        json={"values": {"auth.require_key": True, "server.port": 9123}},
    )

    assert response.status_code == 409
    assert SECRET not in response.text
    assert "Nothing was saved" in response.json()["detail"]
    assert user_settings.load() == {}
    require_key = next(
        entry
        for group in client.get("/api/connections/settings").json()["groups"]
        for entry in group["items"]
        if entry["key"] == "auth.require_key"
    )
    assert require_key["value"] is False


def test_an_invalid_payload_creates_no_key(client, home) -> None:
    response = client.put(
        "/api/connections/settings",
        json={"values": {"auth.require_key": True, "server.port": 0}},
    )

    assert response.status_code == 422
    assert not (home / ".marm" / ".env").exists()
    assert user_settings.load() == {}


def test_restart_job_stops_without_killing_the_console_then_starts(
    client, runtime
) -> None:
    response = client.post("/api/connections/runtime/restart")

    assert response.status_code == 202
    job = wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "done"
    assert isinstance(job["seconds"], float)
    assert runtime["calls"] == [
        ("stop", {"stop_console_process": False}),
        ("start", {"profile": "fast", "rate_limit_rpm": 90}),
    ]


def test_restart_job_uses_the_saved_preset_over_stale_metadata(
    client, runtime, monkeypatch
) -> None:
    monkeypatch.setattr(runtime_flags, "saved_runtime_preset", lambda: ("light", 30))

    job_id = client.post("/api/connections/runtime/restart").json()["job_id"]
    wait_for_job(client, job_id)

    start = runtime["calls"][1][1]
    assert start["profile"] == "light"
    assert start["rate_limit_rpm"] is not None


def test_restart_job_records_the_failure(client, monkeypatch) -> None:
    def refuse(**kwargs):
        raise RuntimeError("MARM runtime did not stop cleanly")

    monkeypatch.setattr(runtime_manager, "stop_runtime", refuse)

    job_id = client.post("/api/connections/runtime/restart").json()["job_id"]
    job = wait_for_job(client, job_id)

    assert job["status"] == "error"
    assert "did not stop cleanly" in job["detail"]
    assert "seconds" not in job


def test_restart_when_not_managed_is_409_with_the_command(client, runtime) -> None:
    runtime["inspect"] = {"state": "stopped", "managed": False}

    response = client.post("/api/connections/runtime/restart")

    assert response.status_code == 409
    assert response.json()["command"] == "marm-memory restart"
    assert response.json()["detail"]
    assert runtime["calls"] == []
    assert runtime_control._jobs == {}


def test_unknown_restart_job_is_404(client) -> None:
    assert client.get("/api/connections/runtime/restart/nope").status_code == 404


def test_mutating_routes_are_403_off_loopback_and_do_nothing(
    client, home, runtime, monkeypatch
) -> None:
    monkeypatch.setenv(HOST_ENV, "0.0.0.0")

    put = client.put(
        "/api/connections/settings",
        json={"values": {"auth.require_key": True, "server.port": 9000}},
    )
    restart = client.post("/api/connections/runtime/restart")

    assert put.status_code == restart.status_code == 403
    assert not (home / ".marm").exists()
    assert runtime["calls"] == []
    assert runtime_control._jobs == {}
    assert client.get("/api/connections/settings").status_code == 200
    assert client.get("/api/connections/overview").status_code == 200


def test_overlay_of_a_saved_key_never_reaches_a_response(
    client, home, monkeypatch
) -> None:
    (home / ".marm").mkdir()
    (home / ".marm" / ".env").write_text(f"MARM_API_KEY={SECRET}\n")
    client.put("/api/connections/settings", json={"values": {"auth.require_key": True}})
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    user_settings.apply_overlay()

    assert os.environ["MARM_API_KEY"] == SECRET
    for path in ("/api/connections/settings", "/api/connections/overview"):
        assert SECRET not in client.get(path).text


def test_second_restart_while_one_runs_reuses_the_job(
    client, runtime, monkeypatch
) -> None:
    release = threading.Event()

    def slow_stop(**kwargs):
        runtime["calls"].append(("stop", kwargs))
        release.wait(5)
        return True

    monkeypatch.setattr(runtime_manager, "stop_runtime", slow_stop)
    first = client.post("/api/connections/runtime/restart").json()["job_id"]
    second = client.post("/api/connections/runtime/restart").json()["job_id"]
    release.set()

    assert second == first
    assert wait_for_job(client, first)["status"] == "done"
    assert [call[0] for call in runtime["calls"]] == ["stop", "start"]


def test_console_follows_the_runtime_port_from_state(monkeypatch) -> None:
    monkeypatch.delenv("MARM_MCP_URL", raising=False)
    monkeypatch.setattr(runtime_manager, "read_state", lambda: {"port": 8123})
    assert mcp_client._base_url() == "http://127.0.0.1:8123"

    monkeypatch.setenv("MARM_MCP_URL", "http://127.0.0.1:9000/")
    assert mcp_client._base_url() == "http://127.0.0.1:9000"
