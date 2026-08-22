"""Log CRUD endpoints for MARM Console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import memory_store
from ..core import _mcp_tool_mutation, get_memory_db_path
from ..models import BulkDeletePayload, LogBulkDeletePayload, LogDeletePayload

router = APIRouter()


@router.get("/api/logs")
def get_logs(
    q: str | None = None,
    session: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    try:
        return memory_store.list_logs(
            get_memory_db_path(), q=q, session=session, limit=limit, offset=offset
        )
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/api/logs/{log_id}")
def delete_log(log_id: str, payload: LogDeletePayload) -> dict:
    result = _mcp_tool_mutation(
        "marm_delete",
        {
            "type": "log",
            "target": log_id,
            "session_name": payload.session_name,
        },
    )
    deleted_count = result.get("deleted_count", 0)
    if not deleted_count:
        raise HTTPException(status_code=404, detail="Log entry not found.")
    return {
        "log_id": log_id,
        "session_name": payload.session_name,
        "deleted_count": deleted_count,
        "memories_deleted": result.get("memories_deleted", 0),
    }


@router.post("/api/logs/bulk-delete")
def delete_selected_logs(payload: LogBulkDeletePayload) -> dict:
    deleted_logs = 0
    deleted_memories = 0
    failed_logs: list[dict] = []
    unique_logs = {(log.id, log.session_name): log for log in payload.logs}
    for log in unique_logs.values():
        try:
            result = _mcp_tool_mutation(
                "marm_delete",
                {
                    "type": "log",
                    "target": log.id,
                    "session_name": log.session_name,
                },
            )
        except HTTPException as exc:
            failed_logs.append(
                {
                    "log_id": log.id,
                    "session_name": log.session_name,
                    "status_code": exc.status_code,
                    "message": str(exc.detail),
                }
            )
            continue
        if not result.get("deleted_count", 0):
            failed_logs.append(
                {
                    "log_id": log.id,
                    "session_name": log.session_name,
                    "status_code": 404,
                    "message": "Log entry not found.",
                }
            )
            continue
        deleted_logs += int(result.get("deleted_count", 0) or 0)
        deleted_memories += int(result.get("memories_deleted", 0) or 0)
    return {
        "status": "partial_success" if failed_logs else "success",
        "deleted_count": deleted_logs,
        "memories_deleted": deleted_memories,
        "failed_logs": failed_logs,
    }


@router.delete("/api/logs")
def delete_all_logs(payload: BulkDeletePayload) -> dict:
    _ = payload
    try:
        logs = memory_store.list_log_refs(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    deleted_logs = 0
    deleted_memories = 0
    failed_logs: list[dict] = []
    for log in logs:
        try:
            result = _mcp_tool_mutation(
                "marm_delete",
                {
                    "type": "log",
                    "target": log["id"],
                    "session_name": log["session_name"],
                },
            )
        except HTTPException as exc:
            failed_logs.append(
                {
                    "log_id": log["id"],
                    "status_code": exc.status_code,
                    "message": str(exc.detail),
                }
            )
            continue
        deleted_logs += int(result.get("deleted_count", 0) or 0)
        deleted_memories += int(result.get("memories_deleted", 0) or 0)
    return {
        "status": "partial_success" if failed_logs else "success",
        "deleted_count": deleted_logs,
        "memories_deleted": deleted_memories,
        "failed_logs": failed_logs,
    }
