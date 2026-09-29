"""Manual tab routes: real route wiring, the runtime OpenAPI feed, Docker target, and key secrecy."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marm_mcp_server.config import user_settings
from marm_mcp_server.console import mcp_client
from marm_mcp_server.console.endpoints import manual
from marm_mcp_server.services import client_config, client_snippets

SECRET = "sk-marm-manual-secret-value"
BASE = "/api/connections/manual"


@pytest.fixture
def runtime_schema() -> dict:
    from marm_mcp_server.server import app as runtime_app

    return runtime_app.openapi()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "marm_mcp_server.core.runtime_manager.inspect_runtime",
        lambda: {"state": "ready", "metadata": {"port": 8001}},
    )
    monkeypatch.setattr("marm_mcp_server.config.settings.MARM_API_KEY", "")
    monkeypatch.setenv("MARM_API_KEY", SECRET)
    monkeypatch.setattr(user_settings, "_home", lambda: tmp_path)
    app = FastAPI()
    app.include_router(manual.router)
    with TestClient(app) as test_client:
        yield test_client


def test_snippet_route_returns_the_spec_shape(client) -> None:
    response = client.get(
        f"{BASE}/snippet",
        params={"client": "vscode", "os": "windows", "transport": "http"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"client", "os", "path", "format", "text", "notes"}
    assert body["path"] == "%APPDATA%\\Code\\User\\mcp.json"
    assert json.loads(body["text"])["servers"]["marm-memory"] == {
        "type": "http",
        "url": "http://127.0.0.1:8001/mcp",
    }


def test_snippet_route_errors(client) -> None:
    def status(**params) -> int:
        return client.get(f"{BASE}/snippet", params=params).status_code

    assert status(client="nope") == 404
    assert status(client="claude-desktop", os="linux", transport="stdio") == 422
    assert status(client="claude-desktop", transport="http") == 422
    assert status(client="windsurf", scope="project") == 422
    assert status(client="cursor", transport="pigeon") == 422
    assert status(client="cursor", os="dos") == 422
    assert status(client="xai") == 422
    assert status() == 422
    detail = client.get(
        f"{BASE}/snippet",
        params={"client": "claude-desktop", "os": "linux", "transport": "stdio"},
    ).json()["detail"]
    assert "not available on linux" in detail


def test_snippet_defaults_to_the_host_os(client) -> None:
    body = client.get(f"{BASE}/snippet", params={"client": "cursor"}).json()
    assert body["os"] == client_snippets.host_os()


def test_docker_target_uses_the_saved_port_tag_and_always_a_key_reference(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        user_settings,
        "load_docker",
        lambda: {**user_settings.docker_defaults(), "port": 9123, "tag": "v9.9.9"},
    )
    http = client.get(
        f"{BASE}/snippet",
        params={"client": "cursor", "os": "linux", "target": "docker"},
    ).json()
    entry = json.loads(http["text"])["mcpServers"]["marm-memory"]
    assert entry["url"] == "http://127.0.0.1:9123/mcp"
    assert entry["headers"]["Authorization"] == "Bearer ${env:MARM_API_KEY}"
    stdio = client.get(
        f"{BASE}/snippet",
        params={
            "client": "cursor",
            "os": "linux",
            "target": "docker",
            "transport": "docker-stdio",
        },
    ).json()
    assert json.loads(stdio["text"])["mcpServers"]["marm-memory"]["args"][-1].endswith(
        ":v9.9.9"
    )
    commands = client.get(
        f"{BASE}/agent-commands", params={"target": "docker", "os": "linux"}
    ).json()["commands"]
    claude = next(c for c in commands if c["client"] == "claude")
    assert "http://127.0.0.1:9123/mcp" in claude["command"]
    assert '--header "Authorization: Bearer ${MARM_API_KEY}"' in claude["command"]


def test_agent_commands_route(client) -> None:
    response = client.get(
        f"{BASE}/agent-commands", params={"transport": "stdio", "os": "linux"}
    )
    body = response.json()
    assert [c["client"] for c in body["commands"]] == [
        c for c in client_config.CLIENT_IDS if c != "xai"
    ]
    assert all(
        set(c) == {"client", "label", "command", "note"} for c in body["commands"]
    )
    claude = body["commands"][0]
    assert claude["command"] == (
        "claude mcp add --transport stdio --scope user marm-memory -- marm-mcp-stdio"
    )
    assert (
        client.get(f"{BASE}/agent-commands", params={"scope": "team"}).status_code
        == 422
    )


def test_cli_route_lists_the_real_catalog(client) -> None:
    commands = {c["command"]: c for c in client.get(f"{BASE}/cli").json()["commands"]}
    assert commands["projects index"]["args"][0]["kind"] == "positional"
    assert commands["key reveal"]["cli_only"] is True


def test_endpoints_route_groups_the_runtime_openapi(
    client, monkeypatch, runtime_schema
) -> None:
    seen: dict = {}

    def fake_get(operation, *, query=None, timeout=10.0):
        seen.update(operation=operation, timeout=timeout)
        return runtime_schema

    monkeypatch.setattr(mcp_client, "get", fake_get)
    body = client.get(f"{BASE}/endpoints").json()

    assert seen["operation"] == "openapi.json" and seen["timeout"] <= 5
    assert body["runtime_available"] is True and body["reason"] is None
    assert body["mcp_url"] == "http://127.0.0.1:8001/mcp"
    groups = {g["name"]: g["routes"] for g in body["groups"]}
    assert groups["marm_log_show"] == [
        {
            "method": "GET",
            "path": "/marm_log_show",
            "summary": runtime_schema["paths"]["/marm_log_show"]["get"]["summary"],
            "auth": "local",
        }
    ]
    served = {(r["method"], r["path"]) for g in groups.values() for r in g}
    expected = {
        (method.upper(), path)
        for path, item in runtime_schema["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert served == expected
    assert all(
        r["path"].strip("/").split("/")[0] == name
        for name, routes in groups.items()
        for r in routes
    )
    assert all(r["summary"] for routes in groups.values() for r in routes)


def test_endpoints_route_marks_public_paths_and_key_auth(
    client, monkeypatch, runtime_schema
) -> None:
    monkeypatch.setattr("marm_mcp_server.config.settings.MARM_API_KEY", SECRET)
    monkeypatch.setattr(mcp_client, "get", lambda *a, **k: runtime_schema)
    body = client.get(f"{BASE}/endpoints").json()
    routes = {r["path"]: r for g in body["groups"] for r in g["routes"]}
    assert routes["/marm_log_show"]["auth"] == "key"
    assert SECRET not in json.dumps(body)


def test_endpoints_route_falls_back_to_operation_id_when_no_summary(
    client, monkeypatch
) -> None:
    schema = {
        "paths": {
            "/": {"get": {"operationId": "root_status"}},
            "/health": {"get": {"summary": "Health"}},
            "/things/{id}": {
                "parameters": [],
                "delete": {"operationId": "delete_thing"},
            },
        }
    }
    monkeypatch.setattr(mcp_client, "get", lambda *a, **k: schema)
    groups = {
        g["name"]: g["routes"] for g in client.get(f"{BASE}/endpoints").json()["groups"]
    }
    assert groups["root"][0]["summary"] == "Root status"
    assert groups["root"][0]["auth"] == "public"
    assert groups["health"][0]["auth"] == "public"
    assert groups["things"][0] == {
        "method": "DELETE",
        "path": "/things/{id}",
        "summary": "Delete thing",
        "auth": "local",
    }


def test_endpoints_route_when_the_runtime_is_down(client, monkeypatch) -> None:
    def down(*args, **kwargs):
        raise mcp_client.McpUnavailable(
            "MARM MCP server is unavailable for this request."
        )

    monkeypatch.setattr(mcp_client, "get", down)
    response = client.get(f"{BASE}/endpoints")
    assert response.status_code == 200
    body = response.json()
    assert body["runtime_available"] is False
    assert body["groups"] == []
    assert "unavailable" in body["reason"]
    assert body["mcp_url"] == "http://127.0.0.1:8001/mcp"


def test_console_routes_come_from_the_real_console_app(client, monkeypatch) -> None:
    monkeypatch.setattr(mcp_client, "get", lambda *a, **k: {"paths": {}})
    console = client.get(f"{BASE}/endpoints").json()["console"]
    paths = {(r["method"], r["path"]) for r in console}
    assert ("GET", "/api/connections/manual/env") in paths
    assert ("POST", "/api/connections/agents/{client_id}/configure") in paths
    assert all(r["path"].startswith("/api") and r["summary"] for r in console)


def test_env_route_never_returns_the_key_value(client) -> None:
    response = client.get(f"{BASE}/env")
    assert response.status_code == 200
    assert SECRET not in response.text
    items = {i["name"]: i for i in response.json()["items"]}
    assert items["MARM_API_KEY"]["current"] == "set"
    assert items["MARM_API_KEY"]["setting_key"] == "auth.require_key"
    assert items["SERVER_PORT"]["setting_key"] == "server.port"
    assert items["MARM_RATE_LIMIT_RPM"]["setting_key"] is None


def test_every_manual_response_is_free_of_the_key(client, monkeypatch) -> None:
    monkeypatch.setattr(mcp_client, "get", lambda *a, **k: {"paths": {}})
    for path, params in (
        ("snippet", {"client": "claude", "transport": "http"}),
        ("agent-commands", {"transport": "http"}),
        ("cli", {}),
        ("endpoints", {}),
        ("env", {}),
    ):
        assert SECRET not in client.get(f"{BASE}/{path}", params=params).text
