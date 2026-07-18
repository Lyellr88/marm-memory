"""Overview and filters endpoints for MARM Console."""

from __future__ import annotations

import json
import os
import time
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException

from .. import mcp_client, memory_store
from ..core import _concepts_payload, get_concept_db_path, get_memory_db_path

router = APIRouter()


def _mcp_status() -> dict:
    url = (
        os.environ.get("MARM_MCP_URL", "http://127.0.0.1:8001").rstrip("/") + "/health"
    )
    started = time.perf_counter()
    try:
        with urlopen(url, timeout=1.5) as response:
            payload = json.load(response)
        return {
            "reachable": response.status == 200 and payload.get("status") == "healthy",
            "status": payload.get("status"),
            "version": payload.get("version"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "last_checked": payload.get("timestamp"),
            "concept_extraction": payload.get("concept_extraction"),
        }
    except (URLError, OSError, ValueError):
        return {"reachable": False}


def _concept_status(mcp_status: dict) -> str:
    if mcp_status.get("concept_extraction") == "unavailable":
        return "unavailable"
    return "ready" if get_concept_db_path().exists() else "not_built"


@router.get("/api/overview")
def get_overview() -> dict:
    try:
        memory = memory_store.overview(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    projects = mcp_client.cached_projects()
    graph_status = "ready" if projects is not None else "starting"
    mcp_status = _mcp_status()
    return {
        "memory": memory,
        "concepts": {
            "status": _concept_status(mcp_status),
            **_concepts_payload(),
        },
        "graph": {"status": graph_status, "projects": projects or []},
        "runtime_mode": "standalone",
        "mcp_status": mcp_status,
    }


@router.get("/api/filters")
def get_filters() -> dict:
    try:
        return memory_store.filters(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
