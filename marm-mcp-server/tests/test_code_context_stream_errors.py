"""Code Context stream failures must not expose internal details."""

import json

from marm_mcp_server.console import mcp_client
from marm_mcp_server.console.endpoints import code_context as console_code_context
from marm_mcp_server.endpoints import code_context


class _CapturedResponse:
    def __init__(self, content, **_kwargs):
        self.content = content


def _event(body: bytes | str) -> dict:
    if isinstance(body, bytes):
        body = body.decode()
    return json.loads(body.split("data: ", 1)[1])


def test_console_answer_stream_hides_upstream_error_details(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise mcp_client.McpUnavailable("upstream secret detail")

    monkeypatch.setattr(mcp_client, "stream", unavailable)
    monkeypatch.setattr(console_code_context, "StreamingResponse", _CapturedResponse)
    response = console_code_context.stream_answer(
        console_code_context.CodeContextPayload(task="test")
    )
    body = next(response.content)

    assert _event(body) == {"message": "Code Context answer is unavailable."}
    assert b"upstream secret detail" not in body


def test_runtime_answer_stream_hides_details_when_logging_fails(monkeypatch):
    warnings: list[str] = []

    def failed(*_args, **_kwargs):
        raise RuntimeError("internal secret detail")

    def logger_failed(*_args, **_kwargs):
        raise UnicodeEncodeError("cp1252", "→", 0, 1, "unsupported")

    monkeypatch.setattr(code_context, "stream_answer", failed)
    monkeypatch.setattr(code_context.logger, "exception", logger_failed)
    monkeypatch.setattr(code_context.logger, "warning", warnings.append)
    monkeypatch.setattr(code_context, "StreamingResponse", _CapturedResponse)
    response = code_context.stream_code_context_answer(
        code_context.CodeContextRequest(task="test")
    )
    body = next(response.content)

    assert _event(body) == {"message": "Code Context answer is unavailable."}
    assert "internal secret detail" not in body
    assert warnings == ["code-context answer stream failed; diagnostics unavailable"]


def test_runtime_answer_stream_hides_graph_failure_details(monkeypatch):
    def graph_failed(*_args, **_kwargs):
        yield (
            "context",
            {
                "status": "unavailable",
                "message": "graph backend secret detail",
                "hint": "graph backend hint secret",
            },
        )
        yield (
            "error",
            {
                "message": "graph backend secret detail",
                "hint": "graph backend hint secret",
            },
        )

    monkeypatch.setattr(code_context, "stream_answer", graph_failed)
    monkeypatch.setattr(code_context, "StreamingResponse", _CapturedResponse)
    response = code_context.stream_code_context_answer(
        code_context.CodeContextRequest(task="test")
    )
    context = next(response.content)
    error = next(response.content)

    assert _event(context) == {
        "status": "unavailable",
        "message": "Code Context is unavailable.",
    }
    assert _event(error) == {"message": "Code Context is unavailable."}
    assert "graph backend secret detail" not in context
    assert "graph backend secret detail" not in error
    assert "graph backend hint secret" not in context
    assert "graph backend hint secret" not in error
