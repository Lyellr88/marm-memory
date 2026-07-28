"""
MARM MCP Server - Memory Accurate Response Mode for Model Context Protocol

This server integrates all modular components of the MARM protocol into a single
FastAPI application, compliant with the MCP protocol via FastApiMCP.

Author: Lyell - marm-memory
Version: 2.32.0
"""

import os
from contextlib import asynccontextmanager

import psutil
import structlog
from fastapi import FastAPI
from fastapi_mcp import FastApiMCP

from .config.settings import (
    ANALYTICS_DB_PATH,
    DEFAULT_DB_PATH,
    SERVER_VERSION,
)
from .core.compaction_scheduler import _maybe_start_compaction_scheduler
from .core.graph_supervisor import graph_supervisor  # noqa: F401
from .core.memory import memory
from .endpoints.compaction import router as compaction_router
from .endpoints.concepts import router as concepts_router
from .endpoints.graph import router as graph_router
from .endpoints.logging import router as logging_router
from .endpoints.memory import router as memory_router
from .endpoints.notebook import router as notebook_router
from .endpoints.reasoning import router as reasoning_router
from .endpoints.session import router as session_router
from .endpoints.system import router as system_router
from .middleware.auth import auth_middleware
from .middleware.protocol_injection import _mcp_tool_call_tracker
from .middleware.rate_limiting import rate_limit_middleware
from .services.analytics import track_usage
from .services.automation import register_event_handlers
from .utils import logging_filters  # noqa: F401
from .utils.embedding_state import check_embedding_compatibility
from .utils.multiprocess_guard import _warn_if_multi_process_requested

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan management for startup and shutdown"""
    logger.info("Initializing MARM MCP Server", version=SERVER_VERSION)
    _warn_if_multi_process_requested()

    memory_before = get_memory_usage()
    logger.info("Initial memory usage", memory_mb=f"{memory_before:.1f}")

    logger.info(
        "Database locations", memory_db=DEFAULT_DB_PATH, analytics_db=ANALYTICS_DB_PATH
    )
    check_embedding_compatibility(warn=lambda message: logger.warning(message))

    register_event_handlers()
    await memory.start_write_queue()
    memory.restore_active_session()

    _compaction_scheduler = _maybe_start_compaction_scheduler()

    memory_after = get_memory_usage()
    logger.info("Memory usage after startup", memory_mb=f"{memory_after:.1f}")

    memory_increase = memory_after - memory_before
    logger.info("Startup memory increase", increase_mb=f"{memory_increase:.1f}")

    logger.info("MARM MCP Server initialization complete")

    track_usage("server_startup", user_data={"version": SERVER_VERSION})

    yield

    logger.info("Shutting down MARM MCP Server")
    if _compaction_scheduler and _compaction_scheduler.running:
        _compaction_scheduler.shutdown(wait=False)
    from .core.shutdown_manager import shutdown_manager

    await shutdown_manager.graceful_shutdown()
    track_usage("server_shutdown")


app = FastAPI(
    title="MARM MCP Server",
    description="Memory Accurate Response Mode - Complete Protocol Implementation",
    version=SERVER_VERSION,
    lifespan=lifespan,
)


app.middleware("http")(_mcp_tool_call_tracker)
app.middleware("http")(auth_middleware)
app.middleware("http")(rate_limit_middleware)


def get_memory_usage():
    """Get current memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


app.include_router(session_router)
app.include_router(logging_router)
app.include_router(reasoning_router)
app.include_router(notebook_router)
app.include_router(memory_router)
app.include_router(system_router)
app.include_router(compaction_router)
app.include_router(graph_router)
app.include_router(concepts_router)


# Explicit whitelist as defense-in-depth: marm-graph/internal routes must not
# appear in FastApiMCP's OpenAPI-derived tool list unless intentionally exposed.
MCP_TOOL_OPERATIONS = [
    "marm_smart_recall",
    "marm_log_entry",
    "marm_log_show",
    "marm_delete",
    "marm_summary",
    "marm_notebook",
    "marm_compaction",
    "marm_graph_index",
    "marm_code_lookup",
    "marm_graph_trace",
    "marm_graph_architecture",
    "marm_graph_impact",
    "marm_concept_build",
    "marm_concept_recall",
]

mcp = FastApiMCP(app, include_operations=MCP_TOOL_OPERATIONS)
mcp.mount_http()


# Preserve direct imports from server.py while the installed CLI resolves
# through cli.py and the MCP server entry point continues to use create_server.
from .cli import create_server, main  # noqa: E402,F401

if __name__ == "__main__":
    main()
