"""Memory CRUD endpoints for MARM Console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import mcp_client, memory_store
from ..core import get_memory_db_path
from ..models import MemoryBulkDeletePayload, MemoryDeletePayload, MemoryMutationPayload

router = APIRouter()


@router.get("/api/memories")
def get_memories(
    q: str | None = None,
    session: str | None = None,
    project: str | None = None,
    platform: str | None = None,
    context_type: str | None = None,
    compaction_role: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    try:
        return memory_store.list_memories(
            get_memory_db_path(),
            q=q,
            session=session,
            project=project,
            platform=platform,
            context_type=context_type,
            compaction_role=compaction_role,
            limit=limit,
            offset=offset,
        )
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/memories/{memory_id}")
def get_memory(memory_id: str) -> dict:
    try:
        memory = memory_store.get_memory(get_memory_db_path(), memory_id)
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


def _memory_mutation(
    operation: str, payload: dict | None = None, method: str = "POST"
) -> dict:
    try:
        return mcp_client.request(operation, payload, method=method, timeout=30.0)
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _memory_payload(payload: MemoryMutationPayload) -> dict:
    data = payload.model_dump()
    data["context_type"] = data.get("context_type") or "general"
    return data


@router.post("/api/memories", status_code=201)
def create_memory(payload: MemoryMutationPayload) -> dict:
    return _memory_mutation("internal/memories", _memory_payload(payload))


@router.put("/api/memories/{memory_id}")
def replace_memory(memory_id: str, payload: MemoryMutationPayload) -> dict:
    return _memory_mutation(
        f"internal/memories/{memory_id}", _memory_payload(payload), method="PUT"
    )


@router.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: str, payload: MemoryDeletePayload) -> dict:
    return _memory_mutation(
        f"internal/memories/{memory_id}",
        payload.model_dump(),
        method="DELETE",
    )


@router.post("/api/memories/bulk-delete")
def bulk_delete_memories(payload: MemoryBulkDeletePayload) -> dict:
    return _memory_mutation(
        "internal/memories/bulk-delete",
        payload.model_dump(),
    )
