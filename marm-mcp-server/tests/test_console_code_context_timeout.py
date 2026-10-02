"""The Console waits at least as long as any analyst run may take."""

import asyncio
import importlib

from marm_mcp_server.console.models import CodeContextPayload
from marm_mcp_server.services.analyst.profile import MAX_TIME_S


def _route(monkeypatch):
    route = importlib.import_module("marm_mcp_server.console.endpoints.code_context")
    seen = {}

    def post(_op, _payload, *, timeout):
        seen["post"] = timeout
        return {}

    def stream(_op, _payload, *, timeout):
        seen["stream"] = timeout
        return iter(())

    monkeypatch.setattr(route.mcp_client, "post", post)
    monkeypatch.setattr(route.mcp_client, "stream", stream)
    return route, seen


def test_an_answer_request_outlasts_the_longest_run(monkeypatch):
    route, seen = _route(monkeypatch)
    route.build_code_context(CodeContextPayload(task="t", answer=True))
    response = route.stream_answer(CodeContextPayload(task="t", answer=True))

    async def drain():
        return [chunk async for chunk in response.body_iterator]

    asyncio.run(drain())
    assert seen["post"] > MAX_TIME_S
    assert seen["stream"] > MAX_TIME_S


def test_a_composition_alone_keeps_the_short_timeout(monkeypatch):
    route, seen = _route(monkeypatch)
    route.build_code_context(CodeContextPayload(task="t"))
    assert seen["post"] == 60.0
