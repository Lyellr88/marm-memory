import importlib

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


def test_context_log_endpoint_persists_sanitized_memory(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    content = '<script>alert("x")</script> project milestone preserved'

    response = client.post(
        "/marm_context_log",
        json={"session_name": "http-real-db", "content": content},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "script" not in body["content"].lower()
    assert body["context_type"] == "project"

    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    with memory_module.memory.get_connection() as conn:
        row = conn.execute(
            "SELECT session_name, content, context_type FROM memories WHERE id = ?",
            (body["memory_id"],),
        ).fetchone()

    assert row == ("http-real-db", " project milestone preserved", "project")


def test_api_key_mode_rejects_missing_or_wrong_bearer_and_accepts_correct_one(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path, api_key="test-key-123")
    client = local_client(server.app)

    missing = client.get("/marm_log_show", params={"session_name": "main"})
    wrong = client.get("/marm_log_show", params={"session_name": "main"}, headers={"Authorization": "Bearer wrong"})
    correct = client.get("/marm_log_show", params={"session_name": "main"}, headers={"Authorization": "Bearer test-key-123"})

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

    assert local.get("/marm_log_show", params={"session_name": "main"}).status_code == 200

    blocked = remote.get("/marm_log_show", params={"session_name": "main"})
    assert blocked.status_code == 401
    assert "Set MARM_API_KEY" in blocked.json()["message"]


def test_public_health_docs_and_openapi_do_not_require_bearer_token(monkeypatch, tmp_path):
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
