"""Notebook CRUD endpoints for MARM Console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import memory_store
from ..core import _mcp_tool_mutation, _now_iso, get_memory_db_path
from ..models import (
    NotebookBulkDeletePayload,
    NotebookDeletePayload,
    NotebookMutationPayload,
)

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


@router.post("/api/notebook/bulk-delete")
def delete_selected_notebook_entries(payload: NotebookBulkDeletePayload) -> dict:
    deleted_entries = 0
    failed_entries: list[dict] = []
    unique_entries = {
        (entry.name, entry.session_name, entry.project, entry.platform): entry
        for entry in payload.entries
    }
    for entry in unique_entries.values():
        try:
            result = _mcp_tool_mutation(
                "marm_delete",
                {
                    "type": "notebook",
                    "target": entry.name,
                    "session_name": entry.session_name.strip() or "main",
                    "project": entry.project,
                    "platform": entry.platform,
                },
            )
        except HTTPException as exc:
            failed_entries.append(
                {
                    "name": entry.name,
                    "session_name": entry.session_name,
                    "project": entry.project,
                    "platform": entry.platform,
                    "status_code": exc.status_code,
                    "message": str(exc.detail),
                }
            )
            continue
        if not result.get("deleted", True):
            failed_entries.append(
                {
                    "name": entry.name,
                    "session_name": entry.session_name,
                    "project": entry.project,
                    "platform": entry.platform,
                    "status_code": 404,
                    "message": "Notebook entry not found.",
                }
            )
            continue
        deleted_entries += 1
    return {
        "status": "partial_success" if failed_entries else "success",
        "deleted_entries": deleted_entries,
        "failed_entries": failed_entries,
    }
