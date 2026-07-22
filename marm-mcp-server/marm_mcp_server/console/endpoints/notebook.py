"""Notebook CRUD endpoints for MARM Console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import memory_store
from ..core import _mcp_tool_mutation, _now_iso, get_memory_db_path
from ..models import NotebookDeletePayload, NotebookMutationPayload

router = APIRouter()


@router.get("/api/notebook")
def get_notebook() -> list[dict]:
    try:
        return memory_store.list_notebook(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/notebook")
def upsert_notebook(payload: NotebookMutationPayload) -> dict:
    name = payload.name.strip()
    content = payload.content.strip()
    session_name = (payload.session_name or "main").strip() or "main"
    if not name or not content:
        raise HTTPException(status_code=422, detail="Name and content are required.")
    _mcp_tool_mutation(
        "marm_notebook",
        {
            "action": "add",
            "name": name,
            "data": content,
            "session_name": session_name,
            "project": payload.project,
            "platform": payload.platform,
        },
    )
    try:
        for entry in memory_store.list_notebook(get_memory_db_path()):
            if (
                entry["name"] == name
                and entry.get("session_name") == session_name
                and entry.get("project") == payload.project
                and entry.get("platform") == payload.platform
            ):
                return entry
    except memory_store.MemoryStoreUnavailable:
        pass
    return {
        "name": name,
        "content": content,
        "session_name": session_name,
        "project": payload.project,
        "platform": payload.platform,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


@router.delete("/api/notebook/{name}")
def delete_notebook(name: str, payload: NotebookDeletePayload) -> dict:
    session_name = (payload.session_name or "main").strip() or "main"
    result = _mcp_tool_mutation(
        "marm_delete",
        {
            "type": "notebook",
            "target": name,
            "session_name": session_name,
            "project": payload.project,
            "platform": payload.platform,
        },
    )
    return {
        "name": name,
        "deleted": bool(result.get("deleted", True)),
    }
