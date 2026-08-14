"""Logging endpoints for MARM MCP Server."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..core.models import DeleteRequest, LogEntryRequest
from ..services.log_entry import (
    create_log_entry,
    delete_log_or_notebook_entry,
    list_log_entries,
)

router = APIRouter(prefix="", tags=["Logging"])


@router.post("/marm_log_entry", operation_id="marm_log_entry")
async def marm_log_entry(request: LogEntryRequest) -> dict:
    """
    📝 Add structured log entry for milestones or decisions

    Start with "Session: [name]" or "Topic: [name]" to switch active session.
    The backend auto-tags the date. All subsequent entries route to that session.
    Entries are also stored as semantic memories so marm_smart_recall can find them.
    Equivalent to /log entry: [YYYY-MM-DD-topic-summary] command
    """
    return await create_log_entry(request.entry, request.session_name)


@router.get("/marm_log_show", operation_id="marm_log_show")
async def marm_log_show(
    session_name: Optional[str] = Query(
        None, description="Session to show logs for. If omitted, lists all sessions."
    ),
) -> dict:
    """
    📋 Display all entries and sessions logged

    Equivalent to /log show: [session] command
    """
    return await list_log_entries(session_name)


@router.post("/marm_delete", operation_id="marm_delete")
async def marm_delete(request: DeleteRequest) -> dict:
    """
    🗑️ Delete a log session, log entry, or notebook entry

    type="log" + session_name: delete specific entry by id or topic
    type="log" (no session_name): delete entire session and all its entries
    type="notebook": delete notebook entry by name
    """
    if request.type not in ("log", "notebook"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid type '{request.type}'. Must be 'log' or 'notebook'.",
        )
    return await delete_log_or_notebook_entry(
        request.type,
        request.target,
        request.session_name,
        project=request.project,
        platform=request.platform,
        scoped_notebook=(
            request.type == "notebook"
            and bool({"project", "platform"} & request.model_fields_set)
        ),
    )
