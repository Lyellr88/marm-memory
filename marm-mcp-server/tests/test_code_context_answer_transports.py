"""The grounding verdict, through the public surfaces rather than the service.

One HTTP request per answer route and one STDIO tool call. The graph and the
model are stubbed; the transports, request models and routing are real.
"""

import asyncio
import importlib
import inspect
import json
import sys
import types

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
                Symbol(
                    "svc.apply",
                    "apply",
                    "Function",
                    "svc.py",
                    10,
                    40,
                    seeded=True,
                    source="def apply(row):\n    # take the row first\n    claim_row(row)\n",
                ),
                Symbol(
                    "svc.claim_row",
                    "claim_row",
                    "Function",
                    "svc.py",
                    50,
                    60,
                    source="def claim_row(row):\n    return row\n",
                ),
            ],
        )

    def stream(*_a, finished=None, **_k):
        if finished is not None:
            finished["reason"] = "stop"
        yield from (reply[i : i + 9] for i in range(0, len(reply), 9))

    def complete(*_a, finished=None, **_k):
        if finished is not None:
            finished["reason"] = "stop"
        return reply

    for space in _every_code_context_namespace(cc):
        monkeypatch.setitem(space, "build", build)
        monkeypatch.setitem(space, "LocalBackend", lambda: object())
    for llm in _every_local_llm(local_llm):
        monkeypatch.setattr(llm, "available", lambda *a, **k: "stub-model")
        monkeypatch.setattr(llm, "endpoint_source", lambda: "environment")
        monkeypatch.setattr(llm, "complete", complete)
        monkeypatch.setattr(llm, "stream", stream)
    return composed


def _every_code_context_namespace(current):
    """The globals of every loaded copy of build_code_context, live or stale.

    A tool module that imported build_code_context keeps the copy it was loaded
    with, and that function reads build and LocalBackend from its own globals.
    """
    found = {id(current.__dict__): current.__dict__}
    for mod in list(sys.modules.values()):
        if not isinstance(mod, types.ModuleType):
            continue
        fn = vars(mod).get("build_code_context")
        space = fn.__globals__ if inspect.isfunction(fn) else None
        if space is not None and space.get("__name__") == current.__name__:
            found[id(space)] = space
    return list(found.values())


def _every_local_llm(current):
    """Each generation of `local_llm` a loaded module refers to.

    Modules that import `local_llm` at load time keep the generation they were
    loaded with, and an earlier test's isolated server load can leave one
    behind. Stubbing only the current module would miss the model call.
    """
    found = {id(current): current}
    for mod in list(sys.modules.values()):
        ref = getattr(mod, "local_llm", None)
        if isinstance(ref, types.ModuleType) and ref.__name__ == current.__name__:
            found[id(ref)] = ref
    return list(found.values())


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.mark.parametrize(
    ("reply", "status"), [(GROUNDED, "ok"), (INVENTED, "rejected")]
)
def test_http_tool_reports_the_verdict(monkeypatch, tmp_path, reply, status):
    client = local_client(load_isolated_server(monkeypatch, tmp_path).app)
    _stub(monkeypatch, reply)

    body = client.post(
        "/marm_code_context", json={"task": "how", "project": "p", "answer": True}
    ).json()

    assert body["answer_status"] == status
    if status == "rejected":
        assert body["answer_unresolved"] == ["persist_all_rows"]


@pytest.mark.parametrize(
    ("reply", "status"), [(GROUNDED, "ok"), (INVENTED, "rejected")]
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
    ("reply", "status"), [(GROUNDED, "ok"), (INVENTED, "rejected")]
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
