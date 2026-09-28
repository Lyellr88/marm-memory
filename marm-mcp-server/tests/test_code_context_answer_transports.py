"""The grounding verdict, through the public surfaces rather than the service.

One HTTP request per answer route and one STDIO tool call. The graph and the
model are stubbed; the transports, request models and routing are real.
"""

import asyncio
import importlib
import json

import pytest
from conftest import load_isolated_server, local_client
from mcp.shared.memory import create_connected_server_and_client_session

GROUNDED = "apply takes the row first [apply], via [`claim_row`]."
INVENTED = "apply takes the row first [apply], then calls [persist_all_rows]."


def _stub(monkeypatch, reply: str) -> list[str]:
    """Stub the graph and the model where the live modules will look them up."""
    cc = importlib.import_module("marm_mcp_server.services.code_context")
    local_llm = importlib.import_module("marm_mcp_server.services.local_llm")
    from marm_mcp_server.services.code_context.compose import Context, Symbol

    composed: list[str] = []

    async def build(_backend, task, **_kw):
        composed.append(task)
        return Context(
            project={"name": "p", "root_path": "/x/proj"},
            task=task,
            symbols=[
                Symbol("svc.apply", "apply", "Function", "svc.py", 10, 40, seeded=True),
                Symbol("svc.claim_row", "claim_row", "Function", "svc.py", 50, 60),
            ],
        )

    def stream(*_a, finished=None, **_k):
        if finished is not None:
            finished["reason"] = "stop"
        yield from (reply[i : i + 9] for i in range(0, len(reply), 9))

    monkeypatch.setattr(cc, "build", build)
    monkeypatch.setattr(cc, "LocalBackend", lambda: object())
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "stub-model")
    monkeypatch.setattr(local_llm, "complete", lambda *a, **k: reply)
    monkeypatch.setattr(local_llm, "stream", stream)
    return composed


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.mark.parametrize(
    ("reply", "status"), [(GROUNDED, "ok"), (INVENTED, "unverified")]
)
def test_http_tool_reports_the_verdict(monkeypatch, tmp_path, reply, status):
    client = local_client(load_isolated_server(monkeypatch, tmp_path).app)
    _stub(monkeypatch, reply)

    body = client.post(
        "/marm_code_context", json={"task": "how", "project": "p", "answer": True}
    ).json()

    assert body["answer_status"] == status
    if status == "unverified":
        assert body["answer_unresolved"] == ["persist_all_rows"]


@pytest.mark.parametrize(
    ("reply", "status"), [(GROUNDED, "ok"), (INVENTED, "unverified")]
)
def test_http_stream_sends_one_composition_then_the_verdict(
    monkeypatch, tmp_path, reply, status
):
    client = local_client(load_isolated_server(monkeypatch, tmp_path).app)
    composed = _stub(monkeypatch, reply)

    response = client.post(
        "/internal/code-context/answer",
        json={"task": "how", "project": "p", "include_graph": True, "detail": 3},
    )
    events = _events(response.text)

    assert composed == ["how"], "one request composes once"
    assert events[0][0] == "context"
    assert [s["name"] for s in events[0][1]["symbols"]] == ["apply", "claim_row"]
    assert events[-1][0] == "done"
    assert events[-1][1]["status"] == status


@pytest.mark.parametrize(
    ("reply", "status"), [(GROUNDED, "ok"), (INVENTED, "unverified")]
)
def test_stdio_tool_reports_the_verdict(monkeypatch, tmp_path, reply, status):
    from test_stdio_transport import _isolated_stdio

    stdio = _isolated_stdio(monkeypatch, tmp_path)
    _stub(monkeypatch, reply)

    async def run():
        async with create_connected_server_and_client_session(stdio.mcp) as client:
            return await client.call_tool(
                "marm_code_context", {"task": "how", "project": "p", "answer": True}
            )

    result = asyncio.run(run())
    payload = json.loads(result.content[0].text)

    assert payload["answer_status"] == status
