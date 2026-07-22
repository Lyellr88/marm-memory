from fastapi.testclient import TestClient

from marm_mcp_server.console.app import STATIC_DIR, app


def test_bundled_console_serves_ui_and_preserves_api_404s():
    assert (STATIC_DIR / "index.html").exists()
    with TestClient(app) as client:
        index = client.get("/")
        deep_link = client.get("/knowledge")
        missing_api = client.get("/api/not-a-real-route")

    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert deep_link.status_code == 200
    assert missing_api.status_code == 404
