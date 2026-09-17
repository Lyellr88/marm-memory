"""Console code-context API contract tests with the MCP adapter stubbed."""

import pytest
from fastapi.testclient import TestClient
from marm_mcp_server.console import app as console_app
from marm_mcp_server.console import mcp_client

SUCCESS = {
    "status": "success",
    "project": "marm-memory",
    "task": "how does recall rank",
    "markdown": "# Code context\n\n## rank_memories",
    "symbols": [
        {
            "name": "rank_memories",
            "qualified_name": "marm.recall.rank_memories",
            "label": "Function",
            "file_path": "marm/recall.py",
            "start_line": 10,
            "end_line": 40,
            "score": 0.07157,
            "seeded": True,
            "truncated": False,
            "provenance": None,
        }
    ],
    "memories": [{"content": "ranking is personalised PageRank"}],
    "links": [],
    "graph_nodes": 34,
    "notes": [],
}


def _client(monkeypatch, responder):
    monkeypatch.setattr(console_app.mcp_client, "post", responder)
    return TestClient(console_app.app)


def test_code_context_passes_the_request_through_and_returns_the_composition(
    monkeypatch,
):
    seen = {}

    def fake_post(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
        seen["operation"] = operation
        seen["payload"] = payload
        seen["timeout"] = timeout
        return SUCCESS

    with _client(monkeypatch, fake_post) as client:
        response = client.post(
            "/api/code-context",
            json={"task": "how does recall rank", "project": "marm-memory"},
        )

    assert response.status_code == 200
    assert response.json() == SUCCESS
    assert seen["operation"] == "marm_code_context"
    assert seen["payload"]["task"] == "how does recall rank"
    assert seen["payload"]["project"] == "marm-memory"
    assert seen["payload"]["budget"] == 12000
    # Off unless the caller asks: the edge list is several KB only a visualiser
    # reads, and an agent reads `markdown` and stops.
    assert seen["payload"]["include_graph"] is False
    # Composition reads source from disk and joins memory, so it must not be
    # held to the default 10s used by plain lookups.
    assert seen["timeout"] == 60.0


def test_no_project_is_an_answer_not_an_error(monkeypatch):
    """`no_project` carries the next step to take, so the page must receive it
    rather than a 503 that discards the hint."""
    payload = {
        "status": "no_project",
        "message": "no indexed project matches this directory",
        "hint": "Call marm_graph_index(action='list') to see indexed projects.",
    }

    with _client(monkeypatch, lambda *a, **k: payload) as client:
        response = client.post("/api/code-context", json={"task": "anything"})

    assert response.status_code == 200
    assert response.json() == payload


def test_graph_unavailable_becomes_503(monkeypatch):
    def boom(*args, **kwargs):
        raise mcp_client.McpUnavailable("MARM MCP server is unavailable.")

    with _client(monkeypatch, boom) as client:
        response = client.post("/api/code-context", json={"task": "anything"})

    assert response.status_code == 503


def test_include_graph_is_passed_through_when_asked_for(monkeypatch):
    seen = {}

    def fake_post(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
        seen.update(payload)
        return SUCCESS

    with _client(monkeypatch, fake_post) as client:
        client.post("/api/code-context", json={"task": "t", "include_graph": True})

    assert seen["include_graph"] is True


@pytest.mark.parametrize(
    "body",
    [
        {"task": ""},
        {"task": "x", "budget": 10},
        {"task": "x", "budget": 10**9},
        {},
    ],
)
def test_invalid_requests_are_rejected_before_reaching_the_server(monkeypatch, body):
    def unreached(*args, **kwargs):
        raise AssertionError("an invalid request must not reach the MCP server")

    with _client(monkeypatch, unreached) as client:
        response = client.post("/api/code-context", json=body)

    assert response.status_code == 422
