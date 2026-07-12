import importlib

import pytest

from conftest import load_isolated_server, local_client, remote_client


def test_readiness_exposes_http_endpoints_without_websocket(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["endpoints"]["mcp"] == "http://localhost:8001/mcp"
    assert body["endpoints"]["docs"] == "http://localhost:8001/docs"
    assert "websocket" not in body["endpoints"]
    assert client.get("/mcp/ws").status_code == 404


def test_api_key_mode_rejects_missing_or_wrong_bearer_and_accepts_correct_one(
    monkeypatch, tmp_path
):
    server = load_isolated_server(monkeypatch, tmp_path, api_key="test-key-123")
    client = local_client(server.app)

    missing = client.get("/marm_log_show", params={"session_name": "main"})
    wrong = client.get(
        "/marm_log_show",
        params={"session_name": "main"},
        headers={"Authorization": "Bearer wrong"},
    )
    correct = client.get(
        "/marm_log_show",
        params={"session_name": "main"},
        headers={"Authorization": "Bearer test-key-123"},
    )

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert correct.status_code == 200


def test_unauthorized_mcp_tool_call_does_not_lazy_load_docs(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path, api_key="test-key-123")
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")
    client = local_client(server.app)

    assert not doc_module.docs_are_loaded()

    response = client.post(
        "/mcp",
        content=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}',
        headers={
            "content-type": "application/json",
            "Authorization": "Bearer wrong",
        },
    )

    assert response.status_code == 401
    assert not doc_module.docs_are_loaded()


def test_no_key_mode_allows_loopback_but_blocks_remote_clients(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)

    local = local_client(server.app)
    remote = remote_client(server.app)

    assert (
        local.get("/marm_log_show", params={"session_name": "main"}).status_code == 200
    )

    blocked = remote.get("/marm_log_show", params={"session_name": "main"})
    assert blocked.status_code == 401
    assert "Set MARM_API_KEY" in blocked.json()["message"]


def test_public_health_docs_and_openapi_do_not_require_bearer_token(
    monkeypatch, tmp_path
):
    server = load_isolated_server(monkeypatch, tmp_path, api_key="test-key-123")
    client = remote_client(server.app)

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_health_endpoint_returns_correct_response_shape(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["service"] == "MARM MCP Server"
    assert body["version"] == server.SERVER_VERSION
    assert "timestamp" in body
    assert body["database"] == "connected"
    assert body["semantic_search"] in ("available", "text_only")


def test_dashboard_mount_reachable_but_absent_from_tools_list(monkeypatch, tmp_path):
    """Docker packaging unification's mount-visibility guarantee, in one test:
    a mounted dashboard route is reachable over plain HTTP AND absent from
    the MCP tool surface, so a future refactor can't silently satisfy one
    side while breaking the other.

    Requires marm_dashboard installed -- a docker-only extra, absent from
    the plain pip/CI install path by design.
    """
    pytest.importorskip("marm_dashboard")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.get("/dashboard/health")
    assert response.status_code == 200
    # dashboard's own /health shape, not marm-mcp-server's
    assert response.json()["status"] == "ok"

    names = {t.name for t in server.mcp.tools}
    assert len(names) == 14
    assert "health" not in names


def test_dashboard_mount_is_exempt_from_marm_mcp_servers_own_bearer_gate(
    monkeypatch, tmp_path
):
    """Root `auth_middleware` wraps the whole ASGI app, including routing into
    mounted sub-apps -- if /dashboard weren't exempt, setting MARM_API_KEY on
    marm-mcp-server would block unauthenticated /dashboard requests before
    dashboard's own independent auth gate ever ran, and a plain browser
    navigation could never reach dashboard's own unlock screen.

    /dashboard is exempt from this gate (PUBLIC_PREFIXES) precisely so
    dashboard's own MARM_API_KEY check is the only gate -- no double auth,
    but still gated, not open.

    Requires marm_dashboard installed -- see skip note above.
    """
    pytest.importorskip("marm_dashboard")
    server = load_isolated_server(monkeypatch, tmp_path, api_key="test-key-123")
    client = local_client(server.app)

    unauthenticated_page = client.get("/dashboard/")
    assert unauthenticated_page.status_code == 200

    unauthenticated_health = client.get("/dashboard/health")
    assert unauthenticated_health.status_code == 200

    unauthenticated_api = client.get("/dashboard/api/summary")
    assert unauthenticated_api.status_code == 401

    authenticated_api = client.get(
        "/dashboard/api/summary", headers={"Authorization": "Bearer test-key-123"}
    )
    assert authenticated_api.status_code == 200


def test_dashboard_mount_reads_and_writes_the_same_db_as_marm_mcp_server(
    monkeypatch, tmp_path
):
    """Dashboard keeps reading/writing the same marm_memory.db when mounted --
    a log entry created through marm-mcp-server's own tool must be visible
    through the dashboard's own REST API under /dashboard, and a memory
    created through the dashboard's own REST API must be readable back the
    same way. No separate DB, no HTTP hop between the two.

    Requires marm_dashboard installed -- see skip note above.
    """
    pytest.importorskip("marm_dashboard")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    log_response = client.post(
        "/marm_log_entry",
        json={"session_name": "mount-smoke", "entry": "dashboard mount smoke test"},
    )
    assert log_response.status_code == 200

    summary = client.get("/dashboard/api/summary")
    assert summary.status_code == 200
    assert summary.json()["counts"]["log_entries"] == 1

    create = client.post(
        "/dashboard/api/memories",
        json={
            "content": "hello from the dashboard mount",
            "session_name": "mount-smoke",
            "context_type": "general",
        },
    )
    assert create.status_code == 201

    # 2 memories: the log entry's dual-written semantic memory + the
    # dashboard-created one
    listing = client.get("/dashboard/api/memories", params={"session": "mount-smoke"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 2


def test_dashboard_mount_without_trailing_slash_redirects(monkeypatch, tmp_path):
    """/dashboard (no trailing slash) must redirect to /dashboard/ -- otherwise
    the dashboard's relative asset/api URLs would resolve one level too high
    (e.g. api/summary -> /api/summary instead of /dashboard/api/summary).

    Requires marm_dashboard installed -- see skip note above.
    """
    pytest.importorskip("marm_dashboard")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.get("/dashboard", follow_redirects=False)

    assert response.status_code in (307, 308)
    assert response.headers["location"].endswith("/dashboard/")


def test_dashboard_exemption_does_not_match_lookalike_paths(monkeypatch, tmp_path):
    """The /dashboard auth exemption must match /dashboard and /dashboard/*
    only -- a naive startswith("/dashboard") would also exempt an unrelated
    route like /dashboardevil, which isn't part of the mount at all.
    """
    server = load_isolated_server(monkeypatch, tmp_path, api_key="test-key-123")
    client = remote_client(server.app)

    response = client.get("/dashboardevil")

    assert response.status_code == 401
