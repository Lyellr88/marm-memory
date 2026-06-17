"""Reasoning endpoints for MARM MCP Server."""

from fastapi import APIRouter, Query

from ..services.summary import generate_session_summary

router = APIRouter(prefix="", tags=["Reasoning"])


@router.get("/marm_summary", operation_id="marm_summary")
async def marm_summary(
    session_name: str = Query(..., description="The name of the session to summarize."),
):
    """
    📊 Generate paste-ready context block for new chats

    Equivalent to /summary: [session name] command
    Uses intelligent truncation to stay within MCP 1MB limits.
    """
    return await generate_session_summary(session_name)
