"""Console distill API contract tests with the MCP adapter stubbed."""

import pytest
from fastapi.testclient import TestClient
from marm_mcp_server.console import app as console_app
from marm_mcp_server.console import mcp_client

PROPOSED = {
    "status": "success",
    "extracted": 2,
    "staged": 1,
    "session_name": "review",
    "proposals": [
        {
            "id": "p-1",
            "content": "The code-graph daemon reparents to systemd and survives a stop.",
            "score": 1.0,
            "reasons": ["names its subject", "states rather than speculates"],
            "verdict": "new",
            "cosine": 0.41,
            "staged": True,
        },
        {
            "content": "marm_delete removes log entries only.",
            "score": 0.85,
            "reasons": ["names its subject"],
            "verdict": "duplicate",
            "cosine": 0.97,
            "neighbour_id": "m-9",
            "neighbour": "marm_delete removes log entries only, not memories.",
            "staged": False,
            "note": "already recorded; not staged",
        },
    ],
}


def _client(monkeypatch, responder):
    monkeypatch.setattr(console_app.mcp_client, "post", responder)
    return TestClient(console_app.app)


def test_propose_passes_the_request_through_and_returns_the_proposals(monkeypatch):
    seen = {}

    def fake_post(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
        seen["operation"] = operation
        seen["payload"] = payload
        seen["timeout"] = timeout
        return PROPOSED

    client = _client(monkeypatch, fake_post)
    response = client.post(
        "/api/distill",
        json={"action": "propose", "text": "a transcript", "session_name": "review"},
    )

    assert response.status_code == 200
    assert response.json() == PROPOSED
    assert seen["operation"] == "marm_distill"
    assert seen["payload"]["action"] == "propose"
    assert seen["payload"]["session_name"] == "review"
    # Extraction parses and embeds, so the proxy must outlast a default timeout.
    assert seen["timeout"] >= 60.0


def test_a_duplicate_is_reported_with_its_neighbour_and_not_staged(monkeypatch):
    """The declined duplicates are the informative half of a run.

    They are what tells a reviewer the store already knew something, so the
    route must not filter them out on the way through.
    """
    client = _client(monkeypatch, lambda *a, **k: PROPOSED)
    body = client.post(
        "/api/distill",
        json={"action": "propose", "text": "t", "session_name": "review"},
    ).json()

    duplicate = next(p for p in body["proposals"] if p["verdict"] == "duplicate")
    assert duplicate["staged"] is False
    assert duplicate["neighbour"]
    assert "id" not in duplicate


def test_review_returns_the_pending_queue(monkeypatch):
    def fake_post(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
        assert payload["action"] == "review"
        return {"status": "success", "pending": [], "count": 0}

    client = _client(monkeypatch, fake_post)
    response = client.post("/api/distill", json={"action": "review"})
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_a_tool_refusal_is_a_400_not_a_503(monkeypatch):
    """A caller's mistake and an unreachable server are different problems.

    Collapsing them would have the page tell a reviewer to retry something that
    can never succeed -- applying an already-applied proposal, for instance.
    """
    client = _client(
        monkeypatch,
        lambda *a, **k: {"status": "error", "error": "proposal p-1 is already applied"},
    )
    response = client.post(
        "/api/distill", json={"action": "apply", "proposal_id": "p-1"}
    )
    assert response.status_code == 400
    assert "already applied" in response.json()["detail"]


def test_an_unreachable_server_is_a_503(monkeypatch):
    def boom(*args, **kwargs):
        raise mcp_client.McpUnavailable("MARM is not running")

    client = _client(monkeypatch, boom)
    response = client.post("/api/distill", json={"action": "review"})
    assert response.status_code == 503


@pytest.mark.parametrize(
    "body",
    [
        {"action": "nonsense"},
        {"action": "propose", "session_name": "x", "limit": 0},
        {"action": "propose", "session_name": "x", "limit": 5000},
        {"action": "propose", "session_name": "x", "threshold": 99},
    ],
)
def test_invalid_requests_are_rejected_before_reaching_the_server(monkeypatch, body):
    def unreached(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("the request should not have reached the MCP server")

    client = _client(monkeypatch, unreached)
    assert client.post("/api/distill", json=body).status_code == 422
