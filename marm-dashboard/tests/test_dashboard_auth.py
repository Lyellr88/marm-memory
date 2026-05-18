from conftest import load_dashboard, local_client, remote_client


def test_loopback_without_key_can_use_api_but_remote_is_blocked(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)

    local = local_client(server.app)
    remote = remote_client(server.app)

    assert local.get("/api/summary").status_code == 200
    blocked = remote.get("/api/summary")
    assert blocked.status_code == 401
    assert "MARM_API_KEY" in blocked.json()["message"]


def test_key_mode_requires_bearer_token_and_unlock_validates_key(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path, api_key="dash-key-123")
    client = local_client(server.app)

    assert client.get("/").status_code == 200
    assert client.get("/health").json()["auth_required"] is True
    assert client.post("/api/auth/unlock", json={"api_key": "wrong"}).status_code == 401
    assert client.post("/api/auth/unlock", json={"api_key": "dash-key-123"}).json() == {
        "ok": True,
        "auth_required": True,
    }

    missing = client.get("/api/summary")
    wrong = client.get("/api/summary", headers={"Authorization": "Bearer wrong"})
    correct = client.get("/api/summary", headers={"Authorization": "Bearer dash-key-123"})

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert correct.status_code == 200


def test_security_headers_are_added_to_html_api_and_errors(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path, api_key="dash-key-123")
    client = local_client(server.app)

    responses = [
        client.get("/"),
        client.get("/health"),
        client.get("/api/summary"),
    ]

    for response in responses:
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
