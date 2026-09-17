"""Composed code-context endpoint for MARM Console.

The Console renders the same answer an agent receives from `marm_code_context`:
`markdown` is the agent-facing text, and the structured fields beside it are
what the page lays out, so neither side re-derives the other.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

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
