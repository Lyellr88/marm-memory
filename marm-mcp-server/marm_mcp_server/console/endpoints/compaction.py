"""Session-summary and compaction endpoints for MARM Console."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException

from .. import memory_store
from ..core import _mcp_tool_mutation, get_memory_db_path

router = APIRouter()


@router.get("/api/summaries/{session_name}")
def get_session_summary(session_name: str) -> dict:
    try:
        return memory_store.get_summary(get_memory_db_path(), session_name)
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/compaction")
def get_compaction() -> list[dict]:
    try:
        return memory_store.list_compaction(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/compaction/{candidate_id}/{action}")
def run_compaction_action(
    candidate_id: str, action: Literal["stage", "apply", "discard"]
) -> dict:
    if action == "stage":
        try:
            candidate = memory_store.get_compaction_candidate(
                get_memory_db_path(), candidate_id
            )
        except memory_store.MemoryStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if candidate is None:
            raise HTTPException(
                status_code=404, detail="Compaction candidate not found."
            )
        result = _mcp_tool_mutation(
            "marm_compaction",
            {
                "action": "stage",
                "summaries": [
                    {
                        "candidate_id": candidate_id,
                        "source_memory_ids": candidate["source_memory_ids"],
                        "suggested_summary": candidate["proposed_summary"],
                    }
                ],
            },
            timeout=60.0,
        )
    else:
        result = _mcp_tool_mutation(
            "marm_compaction",
            {"action": action, "candidate_id": candidate_id},
            timeout=60.0,
        )
    return {
        "id": candidate_id,
        "status": "staged"
        if action == "stage"
        else "applied"
        if action == "apply"
        else "discarded",
        "result": result,
    }
