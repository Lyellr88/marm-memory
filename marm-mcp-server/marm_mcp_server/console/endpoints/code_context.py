"""Composed code-context endpoint for MARM Console.

The Console renders the same answer an agent receives from `marm_code_context`:
`markdown` is the agent-facing text, and the structured fields beside it are
what the page lays out, so neither side re-derives the other.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import mcp_client
from ..models import CodeContextPayload

router = APIRouter()


@router.post("/api/code-context")
def build_code_context(payload: CodeContextPayload) -> dict:
    """Rank the symbols that matter for a task and return them with their source.

    The composition is slow relative to a plain lookup -- it reads source from
    disk and joins memory -- so the timeout is the graph timeout, not the
    default, and an over-budget task fails loudly rather than returning a
    truncated answer that looks complete.
    """
    try:
        # Generation is the slow step and it runs after composition, so a
        # request that asks for an answer needs a ceiling that covers both. A
        # composition alone stays on the shorter one rather than paying for a
        # timeout it will never use.
        result = mcp_client.post(
            "marm_code_context",
            payload.model_dump(),
            timeout=150.0 if payload.answer else 60.0,
        )
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result.get("status") == "error":
        raise HTTPException(
            status_code=503, detail=result.get("message", "Code context failed.")
        )
    return result


@router.post("/api/code-context/answer")
def stream_answer(payload: CodeContextPayload) -> StreamingResponse:
    """Pass the grounded answer through to the browser as it is written.

    The Console is a pipe here. Composition still happens server-side and the
    ranked context still comes back from `/api/code-context` as one JSON body;
    this carries only the answer, which is the part that takes seconds.

    Splitting the two is the point. Before, a reader waited 8.6 s for
    everything at once. Now the ranked symbols land in ~380 ms and the answer
    starts arriving ~300 ms after that, into a pane that is already on screen.
    """

    def relay() -> Iterator[bytes]:
        try:
            yield from mcp_client.stream(
                "internal/code-context/answer", payload.model_dump()
            )
        except mcp_client.McpUnavailable as exc:
            yield (
                f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"
            ).encode()

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
