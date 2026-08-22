"""Response contracts for the Console's runtime settings façade."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from marm_mcp_server.console import mcp_client
from marm_mcp_server.console.endpoints.settings import router as settings_router


def test_runtime_settings_routes_preserve_the_console_contract(monkeypatch):
    status = {
        "status": "ready",
        "version": "2.39.0",
        "automation": {
            "graph": {"enabled": True, "source": "environment"},
            "concept": {"enabled": False, "source": "saved_override"},
        },
        "storage": {"memory": {"exists": True}, "concept": {"exists": True}},
    }
    calls: list[tuple[str, dict | None]] = []

    def fake_get(path, **kwargs):
        calls.append((path, None))
        return status

    def fake_put(path, payload=None, **kwargs):
        calls.append((path, payload))
        return {
            "status": "success",
            "scope": payload["scope"],
            "enabled": payload["enabled"],
            "effective": "next cycle",
        }

    monkeypatch.setattr(mcp_client, "get", fake_get)
    monkeypatch.setattr(mcp_client, "put", fake_put)
    app = FastAPI()
    app.include_router(settings_router)

    with TestClient(app) as client:
        settings = client.get("/api/settings/runtime")
        update = client.put(
            "/api/settings/automation", json={"scope": "concept", "enabled": True}
        )

    assert settings.status_code == update.status_code == 200
    assert settings.json() == status
    assert update.json()["effective"] == "next cycle"
    assert calls == [
        ("internal/runtime/settings", None),
        (
            "internal/runtime/settings/automation",
            {"scope": "concept", "enabled": True},
        ),
    ]
