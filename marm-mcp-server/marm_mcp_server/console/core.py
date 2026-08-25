from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from . import concept_store, mcp_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_memory_db_path() -> Path:
    """Match MARM's documented local DB path without importing its runtime."""
    configured = os.environ.get("MARM_DB_PATH")
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".marm" / "marm_memory.db"
    )


def get_concept_db_path() -> Path:
    configured = os.environ.get("MARM_CONCEPT_DB_PATH")
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".marm" / "index" / "marm_index.db"
    )


def _concepts_payload() -> dict:
    return {
        **concept_store.summary(get_concept_db_path()),
        "recent_builds": concept_store.build_runs(get_concept_db_path()),
    }


def _mcp_tool_mutation(operation: str, payload: dict, timeout: float = 30.0) -> dict:
    try:
        result = mcp_client.post(operation, payload, timeout=timeout)
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result.get("status") in {"error", "not_found"}:
        status_code = 404 if result.get("status") == "not_found" else 503
        raise HTTPException(
            status_code=status_code,
            detail=result.get("message", "MARM operation failed."),
        )
    return result
