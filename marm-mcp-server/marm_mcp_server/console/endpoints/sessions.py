"""Session CRUD endpoints for MARM Console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import memory_store
from ..core import _mcp_tool_mutation, get_memory_db_path
from ..models import (
    BulkDeletePayload,
    SessionBulkDeletePayload,
    SessionCreatePayload,
    SessionDeletePayload,
)

router = APIRouter()


@router.get("/api/sessions")
def get_sessions() -> list[dict]:
    try:
        return memory_store.list_sessions(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/sessions", status_code=201)
def create_session(payload: SessionCreatePayload) -> dict:
    session_name = payload.name.strip()
    if not session_name:
        raise HTTPException(status_code=422, detail="Session name is required.")
    result = _mcp_tool_mutation("marm_start", {"session_name": session_name})
    return {
        "name": result.get("session_name", session_name),
        "active": bool(result.get("marm_active", True)),
        "status": result.get("status", "success"),
    }


@router.delete("/api/sessions/{session_name}")
def delete_session(session_name: str, payload: SessionDeletePayload) -> dict:
    result = _mcp_tool_mutation(
        "marm_delete",
        {"type": "log", "target": session_name},
    )
    return {
        "session_name": session_name,
        "deleted_count": result.get("deleted_count", 0),
        "memories_deleted": result.get("memories_deleted", 0),
    }


@router.post("/api/sessions/bulk-delete")
def delete_selected_sessions(payload: SessionBulkDeletePayload) -> dict:
    deleted_sessions = 0
    deleted_logs = 0
    deleted_memories = 0
    failed_sessions: list[dict] = []
    for session_name in dict.fromkeys(payload.session_names):
        try:
            result = _mcp_tool_mutation(
                "marm_delete",
                {"type": "log", "target": session_name},
            )
        except HTTPException as exc:
            failed_sessions.append(
                {
                    "session_name": session_name,
                    "status_code": exc.status_code,
                    "message": str(exc.detail),
                }
            )
            continue
        deleted_sessions += 1
        deleted_logs += int(result.get("deleted_count", 0) or 0)
        deleted_memories += int(result.get("memories_deleted", 0) or 0)
    return {
        "status": "partial_success" if failed_sessions else "success",
        "deleted_sessions": deleted_sessions,
        "deleted_count": deleted_logs,
        "memories_deleted": deleted_memories,
        "failed_sessions": failed_sessions,
    }


@router.delete("/api/sessions")
def delete_all_sessions(payload: BulkDeletePayload) -> dict:
    _ = payload
    try:
        sessions = memory_store.list_sessions(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    deleted_sessions = 0
    deleted_logs = 0
    deleted_memories = 0
    failed_sessions: list[dict] = []
    for session in sessions:
        session_name = session["name"]
        try:
            result = _mcp_tool_mutation(
                "marm_delete",
                {"type": "log", "target": session_name},
            )
        except HTTPException as exc:
            failed_sessions.append(
                {
                    "session_name": session_name,
                    "status_code": exc.status_code,
                    "message": str(exc.detail),
                }
            )
            continue
        deleted_sessions += 1
        deleted_logs += int(result.get("deleted_count", 0) or 0)
        deleted_memories += int(result.get("memories_deleted", 0) or 0)
    return {
        "status": "partial_success" if failed_sessions else "success",
        "deleted_sessions": deleted_sessions,
        "deleted_count": deleted_logs,
        "memories_deleted": deleted_memories,
        "failed_sessions": failed_sessions,
    }
