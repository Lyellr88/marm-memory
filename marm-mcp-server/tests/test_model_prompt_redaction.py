"""A credential never leaves in a prompt to the local model."""

import asyncio
import io
import json

import pytest

from marm_mcp_server.services import local_llm
from marm_mcp_server.services.analyst import brief as brief_mod
from marm_mcp_server.services.analyst.profile import PROFILES
from marm_mcp_server.services.code_context.compose import Context, Symbol

# Built from parts so the file itself carries no scannable secret.
SECRET = "AKIA" + "IOSFODNN7" + "EXAMPLE"


class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Every request body that would have gone to the model server."""
    bodies = []

    def open_(_watch, request, timeout):
        payload = json.loads(request.data)
        bodies.append(payload)
        if payload.get("stream"):
            chunk = {
                "choices": [{"delta": {"content": "ok [S1]"}, "finish_reason": "stop"}]
            }
            return _Reply(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
        reply = {
            "choices": [{"message": {"content": "ok [S1]"}, "finish_reason": "stop"}]
        }
        return _Reply(json.dumps(reply).encode())

    monkeypatch.setattr(local_llm._Deadline, "open", open_)
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "test-model")
    monkeypatch.setattr(local_llm, "endpoint", lambda: "http://127.0.0.1:1")
    return bodies


def _text(bodies):
    return json.dumps(bodies)


def test_complete_redacts_what_it_sends(sent):
    local_llm.complete("system", f"the key is {SECRET}")
    assert sent and SECRET not in _text(sent)
    assert "[redacted:aws-access-key]" in _text(sent)


def test_stream_redacts_what_it_sends(sent):
    list(local_llm.stream("system", f"the key is {SECRET}"))
    assert sent and SECRET not in _text(sent)


def _ctx():
    return Context(
        project={"name": "demo"},
        task=f"why does apply read {SECRET}",
        symbols=[
            Symbol(
                "pkg.apply",
                "apply",
                "Function",
                "pkg/a.py",
                1,
                3,
                source=f'def apply():\n    key = "{SECRET}"\n',
            )
        ],
        memories=[{"id": "m1", "content": f"apply uses {SECRET}"}],
    )


def test_the_json_answer_sends_no_credential(sent):
    ctx = _ctx()
    asyncio.run(brief_mod.analyse(ctx, ctx.task, profile=PROFILES["general"]))
    assert sent and SECRET not in _text(sent)


def test_the_streamed_answer_sends_no_credential(sent):
    ctx = _ctx()
    list(brief_mod.stream_analysis(ctx, ctx.task, profile=PROFILES["general"]))
    assert sent and SECRET not in _text(sent)
