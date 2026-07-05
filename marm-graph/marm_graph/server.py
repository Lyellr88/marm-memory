"""marm-graph HTTP server.

FastAPI + FastApiMCP. The MCP surface is whitelisted to exactly the 5 AI tools;
the UI router is REST-only and never mounted into MCP. Mirrors marm-mcp-server's
lifespan / router-registration / mount shape.
"""

import os
import sys
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi_mcp import FastApiMCP

from .config import settings
from .core.deps import get_client, reset_client
from .endpoints.graph_ai import router as ai_router
from .endpoints.graph_ui import router as ui_router
from .middleware.auth import auth_middleware

logger = structlog.get_logger(__name__)

# The 5 AI operation_ids that are exposed as MCP tools. A whitelist: anything not
# listed here (i.e. the entire UI router) can never appear in the AI's tools/list.
AI_OPERATIONS = [
    "marm_graph_index",
    "marm_code_lookup",
    "marm_graph_trace",
    "marm_graph_architecture",
    "marm_graph_impact",
]

_EXPECTED_UPSTREAM_TOOLS = {
    "index_repository", "search_graph", "query_graph", "trace_path",
    "get_code_snippet", "get_graph_schema", "get_architecture", "search_code",
    "list_projects", "delete_project", "index_status", "detect_changes",
    "manage_adr", "ingest_traces",
}
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _verify_backend() -> None:
    """Start the child, verify the binary trust boundary, check for schema drift."""
    client = get_client()
    if settings.CBM_BINARY_PATH and not os.path.exists(settings.CBM_BINARY_PATH):
        raise RuntimeError(
            f"CBM_BINARY_PATH does not exist: {settings.CBM_BINARY_PATH}"
        )
    client.start()
    logger.info(
        "cbm.backend_ready",
        spawn_command=settings.cbm_spawn_command(),
        pinned_pip_version=settings.PINNED_CBM_VERSION,
        binary_version=client.server_version,  # the true schema-contract version
    )
    try:
        names = {t["name"] for t in client.list_tools()}
    except Exception as e:
        raise RuntimeError(f"Could not list upstream tools to verify schema: {e}") from e
    _check_schema(names)


def _check_schema(names: set[str]) -> None:
    """Fail fast if an expected upstream tool is gone; warn on unexpected extras.

    tools/list is a fixed contract that tool_router maps by hand — a missing tool
    means a hand-written mapping is silently broken, so refuse to start. Extra
    tools are forward-compatible and only worth a warning.
    """
    missing = _EXPECTED_UPSTREAM_TOOLS - names
    extra = names - _EXPECTED_UPSTREAM_TOOLS
    if missing:
        raise RuntimeError(
            f"Upstream schema drift: expected codebase-memory-mcp tools missing "
            f"from the binary: {sorted(missing)}. The pinned contract changed — "
            f"review the router mapping before running."
        )
    if extra:
        logger.warning("cbm.schema_drift_extra", extra=sorted(extra))
    else:
        logger.info("cbm.schema_ok", tool_count=len(names))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "marm-graph starting",
        version=settings.SERVER_VERSION,
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
    )
    _verify_backend()
    yield
    logger.info("marm-graph shutting down")
    reset_client()


app = FastAPI(
    title="marm-graph",
    description="MARM code-structure graph — a thin wrapper over codebase-memory-mcp.",
    version=settings.SERVER_VERSION,
    lifespan=lifespan,
)

app.middleware("http")(auth_middleware)

app.include_router(ai_router)
app.include_router(ui_router)


@app.get("/health")
async def health() -> JSONResponse:
    client = get_client()
    return JSONResponse(
        {
            "status": "ok",
            "server_version": settings.SERVER_VERSION,
            "cbm_binary_version": client.server_version,
            "pinned_pip_version": settings.PINNED_CBM_VERSION,
        }
    )


mcp = FastApiMCP(
    app,
    name="marm-graph",
    description="Code-structure graph tools for MARM/MARMIS.",
    include_operations=AI_OPERATIONS,
)
mcp.mount_http()


def _refuse_insecure_bind() -> None:
    """Refuse to listen on a non-loopback interface without an API key."""
    if settings.SERVER_HOST not in _LOOPBACK and not settings.MARM_GRAPH_API_KEY:
        print(
            f"REFUSING TO START: SERVER_HOST={settings.SERVER_HOST} is not loopback "
            "but MARM_GRAPH_API_KEY is not set. Set an API key to expose marm-graph "
            "on a network interface, or bind to 127.0.0.1.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def main() -> None:
    _refuse_insecure_bind()
    uvicorn.run(app, host=settings.SERVER_HOST, port=settings.SERVER_PORT)


if __name__ == "__main__":
    main()
