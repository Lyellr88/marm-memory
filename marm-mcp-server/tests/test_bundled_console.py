import importlib

from fastapi.testclient import TestClient

from marm_mcp_server.console import cli as console_cli
from marm_mcp_server.console.app import STATIC_DIR, app


def test_bundled_console_serves_ui_and_preserves_api_404s():
    assert (STATIC_DIR / "index.html").exists()
    with TestClient(app) as client:
        index = client.get("/")
        deep_link = client.get("/knowledge")
        root_asset = client.get("/robots.txt")
        traversal = client.get("/%2e%2e/pyproject.toml")
        missing_api = client.get("/api/not-a-real-route")

    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert deep_link.status_code == 200
    assert root_asset.status_code == 200
    assert "text/plain" in root_asset.headers["content-type"]
    assert traversal.status_code == 200
    assert "text/html" in traversal.headers["content-type"]
    assert missing_api.status_code == 404


def test_console_child_environment_inherits_runtime_api_key(monkeypatch):
    monkeypatch.delenv("MARM_API_KEY", raising=False)
    settings = importlib.import_module("marm_mcp_server.config.settings")
    monkeypatch.setattr(settings, "MARM_API_KEY", "runtime-key")

    environment = console_cli._console_environment()

    assert environment["MARM_API_KEY"] == "runtime-key"


def test_console_auth_protects_api_without_blocking_spa(monkeypatch):
    monkeypatch.setenv("MARM_API_KEY", "console-secret")

    with TestClient(app) as client:
        spa = client.get("/knowledge")
        rejected = client.get(
            "/api/not-a-real-route",
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        authorized = client.get(
            "/api/not-a-real-route",
            headers={"Authorization": "Bearer console-secret"},
        )
        preflight = client.options(
            "/api/not-a-real-route",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        untrusted_host = client.get("/", headers={"Host": "malicious.example"})

    assert spa.status_code == 200
    assert rejected.status_code == 401
    assert rejected.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert authorized.status_code == 404
    assert preflight.status_code == 200
    assert untrusted_host.status_code == 400


def test_console_serve_maintains_the_active_log(monkeypatch, tmp_path):
    runtime_manager = importlib.import_module("marm_mcp_server.core.runtime_manager")
    maintained = []
    monkeypatch.setattr(runtime_manager, "runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(
        runtime_manager, "start_log_maintenance", lambda path: maintained.append(path)
    )
    monkeypatch.setattr(console_cli.uvicorn, "run", lambda *args, **kwargs: None)

    console_cli._serve()

    assert maintained == [tmp_path / "console.log"]
