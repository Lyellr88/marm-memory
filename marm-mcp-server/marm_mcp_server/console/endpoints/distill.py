"""Distillation review endpoint for MARM Console.

The Console is a reviewer's surface for `marm_distill`, and reviewing is the
task the tool is weakest at: a proposal carries its score, the reasons it
scored, a verdict and the memory it resembles, and comparing those by reading
JSON in a terminal is exactly the work a list UI does better.

It proxies rather than reimplements. Every decision -- what counts as durable,
what counts as a duplicate, what a discard means -- stays in the tool, so the
page cannot develop its own opinion about any of them.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import mcp_client
from ..models import DistillPayload

router = APIRouter()

# Extraction parses every sentence and embeds every candidate, so a long
# transcript is seconds of work, not milliseconds. Reviewing is cheap by
# comparison and shares the ceiling rather than earning its own.
_TIMEOUT = 120.0


@router.post("/api/distill")
def distill(payload: DistillPayload) -> dict:
    """Propose, review, apply or discard memory proposals.

    A tool-level refusal -- a missing `text`, an already-applied proposal -- is
    returned as a 400 rather than a 503. It is the caller's mistake and is
    fixable by changing the request, which is a different thing from the server
    being unable to answer, and collapsing the two would have the page tell a
    reviewer to retry something that will never succeed.
    """
    try:
        result = mcp_client.post("marm_distill", payload.model_dump(), timeout=_TIMEOUT)
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result.get("status") == "error":
        raise HTTPException(
            status_code=400,
            detail=result.get("error") or result.get("message") or "Distill failed.",
        )
    return result
