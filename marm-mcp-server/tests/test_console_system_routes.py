"""Contract coverage for the Console proxy routes added for the System tab.

The Console owns no data here: every route forwards to the MCP runtime and
translates its failures. These tests assert the forwarding target, the payload,
and the error mapping, which is the whole of the Console's responsibility.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marm_mcp_server.console import mcp_client
from marm_mcp_server.console.endpoints.settings import router


@pytest.fixture
def client(monkeypatch):
    calls: list[tuple[str, str, dict | None, dict | None]] = []

    def record(verb):
        def inner(operation, payload=None, *, query=None, timeout=None):
            calls.append((verb, operation, payload, query))
            return {"status": "success", "echo": operation}

        return inner

    def fake_get(operation, *, query=None, timeout=None):
        calls.append(("GET", operation, None, query))
        return {"status": "success", "echo": operation}

    monkeypatch.setattr(mcp_client, "get", fake_get)
    monkeypatch.setattr(mcp_client, "post", record("POST"))
    monkeypatch.setattr(mcp_client, "put", record("PUT"))
    monkeypatch.setattr(mcp_client, "delete", record("DELETE"))

    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client, calls


@pytest.mark.parametrize(
    ("path", "operation"),
    [
        ("/api/settings/maintenance", "internal/runtime/maintenance"),
        ("/api/settings/doctor", "internal/runtime/doctor"),
        ("/api/settings/upgrade-check", "internal/runtime/upgrade/check"),
        ("/api/settings/backups", "internal/runtime/backups"),
    ],
)
def test_read_routes_forward_to_their_runtime_operation(client, path, operation):
    test_client, calls = client

    response = test_client.get(path)

    assert response.status_code == 200
    assert calls == [("GET", operation, None, None)]


def test_logs_route_passes_the_line_count_through(client):
    test_client, calls = client

    assert (
        test_client.get("/api/settings/logs", params={"lines": 750}).status_code == 200
    )

    assert calls == [("GET", "internal/runtime/logs", None, {"lines": 750})]


def test_logs_route_has_a_default_line_count(client):
    test_client, calls = client

    test_client.get("/api/settings/logs")

    assert calls[0][3] == {"lines": 200}


def test_compaction_dry_run_forwards_the_session_name(client):
    test_client, calls = client

    response = test_client.post(
        "/api/settings/maintenance/compaction-dry-run",
        json={"session_name": "general"},
    )

    assert response.status_code == 202
    assert calls == [
        (
            "POST",
            "internal/runtime/maintenance/compaction-dry-run",
            {"session_name": "general"},
            None,
        )
    ]


def test_compaction_dry_run_rejects_a_missing_session_name(client):
    test_client, calls = client

    assert (
        test_client.post(
            "/api/settings/maintenance/compaction-dry-run", json={}
        ).status_code
        == 422
    )
    assert calls == []


def test_create_backup_posts_with_no_body_of_its_own(client):
    test_client, calls = client

    assert test_client.post("/api/settings/backups").status_code == 200

    assert calls == [("POST", "internal/runtime/backups", {}, None)]


def test_delete_backup_names_the_snapshot_in_the_operation(client):
    test_client, calls = client

    response = test_client.delete(
        "/api/settings/backups/marm-memory-20260101-000000.db"
    )

    assert response.status_code == 200
    assert calls == [
        (
            "DELETE",
            "internal/runtime/backups/marm-memory-20260101-000000.db",
            None,
            None,
        )
    ]


def test_profile_route_forwards_profile_and_rpm(client):
    test_client, calls = client

    response = test_client.put(
        "/api/settings/profile", json={"profile": "swarm", "rate_limit_rpm": 45}
    )

    assert response.status_code == 200
    assert calls == [
        (
            "PUT",
            "internal/runtime/settings/profile",
            {"profile": "swarm", "rate_limit_rpm": 45},
            None,
        )
    ]


def test_profile_route_rejects_an_unknown_profile(client):
    test_client, calls = client

    assert (
        test_client.put("/api/settings/profile", json={"profile": "turbo"}).status_code
        == 422
    )
    assert calls == []


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/settings/maintenance", "get"),
        ("/api/settings/doctor", "get"),
        ("/api/settings/backups", "get"),
    ],
)
def test_an_unreachable_runtime_becomes_503(monkeypatch, path, method):
    def unavailable(*args, **kwargs):
        raise mcp_client.McpUnavailable("runtime is not running")

    monkeypatch.setattr(mcp_client, "get", unavailable)
    app = FastAPI()
    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        assert getattr(test_client, method)(path).status_code == 503


def test_a_runtime_error_keeps_its_status_code(monkeypatch):
    """McpRequestError subclasses McpUnavailable, so handler order decides 404 versus 503."""

    def not_found(*args, **kwargs):
        raise mcp_client.McpRequestError(404, "No such snapshot.")

    monkeypatch.setattr(mcp_client, "delete", not_found)
    app = FastAPI()
    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.delete(
            "/api/settings/backups/marm-memory-20200101-000000.db"
        )

    assert response.status_code == 404


def test_dry_run_status_route_names_the_job(client):
    test_client, calls = client

    response = test_client.get("/api/settings/maintenance/compaction-dry-run/abc-123")

    assert response.status_code == 200
    assert calls == [
        ("GET", "internal/runtime/maintenance/compaction-dry-run/abc-123", None, None)
    ]


def test_reload_docs_queues_a_job_rather_than_calling_the_agent_tool(client):
    """The public marm_reload_docs tool stays synchronous for agents; the Console queues."""
    test_client, calls = client

    assert test_client.post("/api/settings/maintenance/reload-docs").status_code == 202

    assert calls == [("POST", "internal/runtime/maintenance/reload-docs", {}, None)]


def test_reload_docs_status_route_names_the_job(client):
    test_client, calls = client

    response = test_client.get("/api/settings/maintenance/reload-docs/xyz-789")

    assert response.status_code == 200
    assert calls == [
        ("GET", "internal/runtime/maintenance/reload-docs/xyz-789", None, None)
    ]
