"""The Console's LLM settings route forwards every field the server accepts."""

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(monkeypatch):
    settings = importlib.import_module("marm_mcp_server.console.endpoints.settings")
    sent = []

    def put(operation, payload, *, timeout):
        sent.append((operation, payload))
        return {"status": "success"}

    monkeypatch.setattr(settings.mcp_client, "put", put)
    app = FastAPI()
    app.include_router(settings.router)
    return TestClient(app), sent


def test_the_auto_apply_switch_reaches_the_server(monkeypatch):
    client, sent = _client(monkeypatch)
    for value in (True, False, ""):
        response = client.put("/api/settings/llm", json={"auto_apply": value})
        assert response.status_code == 200, response.text
    assert [payload for _op, payload in sent] == [
        {"auto_apply": True},
        {"auto_apply": False},
        {"auto_apply": ""},
    ]


def test_an_unset_switch_is_not_forwarded(monkeypatch):
    client, sent = _client(monkeypatch)
    client.put("/api/settings/llm", json={"profile": "small"})
    assert sent == [("internal/runtime/settings/llm", {"profile": "small"})]
