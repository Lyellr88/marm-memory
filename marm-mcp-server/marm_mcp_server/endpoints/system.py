import logging
import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..config.settings import (
    CONCEPTS_AVAILABLE,
    SEMANTIC_SEARCH_AVAILABLE,
    SERVER_VERSION,
)
from ..core import runtime_flags
from ..core.graph_supervisor import graph_supervisor
from ..core.memory import memory
from ..core.shutdown_manager import shutdown_manager
from ..services.documentation import reload_marm_documentation
from ..services.runtime_status import knowledge_status, maintenance_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["System"])


class RuntimeAutomationRequest(BaseModel):
    scope: Literal["graph", "concept"]
    enabled: bool


def _automation_status() -> dict:
    graph_key = runtime_flags.AUTO_INDEX_GRAPH
    concept_key = runtime_flags.AUTO_INDEX_CONCEPT
    return {
        "graph": {
            "enabled": runtime_flags.get_bool(graph_key, settings.GRAPH_AUTO_INDEX),
            "source": runtime_flags.source(graph_key),
            "environment_default": settings.GRAPH_AUTO_INDEX,
            "suppressed_projects": runtime_flags.suppressed_watches(),
            "unindexable_projects": runtime_flags.unindexable_watches(),
        },
        "concept": {
            "enabled": runtime_flags.get_bool(concept_key, settings.CONCEPT_AUTO_INDEX),
            "source": runtime_flags.source(concept_key),
            "environment_default": settings.CONCEPT_AUTO_INDEX,
        },
    }


@router.get("/health", include_in_schema=False)
async def health_check() -> dict:
    """Health check endpoint for Docker and monitoring"""
    try:
        with memory.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()

        return {
            "status": "healthy",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "connected",
            "semantic_search": (
                "available" if SEMANTIC_SEARCH_AVAILABLE else "text_only"
            ),
            "concept_extraction": "available" if CONCEPTS_AVAILABLE else "unavailable",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e!s}", exc_info=True)

        return {
            "status": "unhealthy",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "Service temporarily unavailable",
        }


@router.get("/ready", include_in_schema=False)
async def readiness_check() -> dict:
    """Readiness check endpoint - service ready to handle requests"""
    try:
        with memory.get_connection() as conn:
            conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            conn.execute("SELECT COUNT(*) FROM sessions").fetchone()

        return {
            "status": "ready",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoints": {
                "mcp": "http://localhost:8001/mcp",
                "docs": "http://localhost:8001/docs",
            },
        }
    except Exception as e:
        logger.error(f"Readiness check failed: {e!s}", exc_info=True)

        return {
            "status": "not_ready",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "Service not ready",
        }


@router.get("/internal/runtime/status", include_in_schema=False)
async def runtime_status() -> dict:
    queue = memory._write_queue
    return {
        "status": "ready",
        "service": "marm-memory-runtime",
        "runtime_id": os.environ.get("MARM_RUNTIME_ID"),
        "pid": os.getpid(),
        "version": SERVER_VERSION,
        "profile": os.environ.get("MARM_RUNTIME_PROFILE", "standard"),
        "write_queue": {
            "enabled": settings.WRITE_QUEUE_ENABLED,
            "running": bool(
                queue and queue._worker_task and not queue._worker_task.done()
            ),
            "depth": queue.queue.qsize() if queue else 0,
            "capacity": queue.queue.maxsize if queue else settings.MAX_QUEUE_SIZE,
            "stopping": queue._stopping if queue else False,
        },
        "graph": graph_supervisor.snapshot(),
    }


@router.get("/internal/runtime/settings", include_in_schema=False)
async def runtime_settings() -> dict:
    """Console-only diagnostics and durable automatic-indexing controls.

    The values are deliberately derived from the same database-backed runtime
    flags the workers read every cycle. This is not a second configuration path.
    """
    runtime = await runtime_status()
    knowledge = knowledge_status()
    maintenance = maintenance_status()
    return {
        **runtime,
        "automation": _automation_status(),
        "knowledge": {
            "state": knowledge["state"],
            "schema": knowledge["schema"],
            "index_queue": knowledge["index_queue"],
        },
        "storage": {
            "memory": maintenance["memory_database"],
            "concept": knowledge["database"],
        },
        "embedding": maintenance["embedding"],
    }


@router.put("/internal/runtime/settings/automation", include_in_schema=False)
async def update_runtime_automation(req: RuntimeAutomationRequest) -> dict:
    key = (
        runtime_flags.AUTO_INDEX_GRAPH
        if req.scope == "graph"
        else runtime_flags.AUTO_INDEX_CONCEPT
    )
    runtime_flags.set_bool(key, req.enabled)
    return {
        "status": "success",
        "scope": req.scope,
        "enabled": req.enabled,
        "effective": "next cycle",
        "automation": _automation_status(),
    }


@router.post("/internal/runtime/shutdown", include_in_schema=False)
async def runtime_shutdown() -> dict:
    shutdown_manager.request_shutdown()
    return {"status": "stopping"}


@router.post(
    "/marm_reload_docs", operation_id="marm_reload_docs", include_in_schema=False
)
async def marm_reload_docs() -> dict:
    """
    📚 Reload MARM documentation into memory system

    Refreshes all documentation files and core knowledge in the database
    """
    try:
        await reload_marm_documentation()
        return {
            "status": "success",
            "message": "📚 MARM documentation reloaded successfully",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to reload documentation: {e!s}"
        ) from e
