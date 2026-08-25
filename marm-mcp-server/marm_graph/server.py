import sys
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi_mcp import FastApiMCP

from .config import settings
from .core import backend
from .core.backend import AI_OPERATIONS
from .core.deps import get_client, reset_client
from .endpoints.graph_ai import router as ai_router
from .endpoints.graph_ui import router as ui_router
from .middleware.auth import auth_middleware

logger = structlog.get_logger(__name__)

_check_schema = backend.check_schema
_EXPECTED_UPSTREAM_TOOLS = backend._EXPECTED_UPSTREAM_TOOLS

_LOOPBACK = ("127.0.0.1", "::1", "localhost")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "marm-graph starting",
        version=settings.SERVER_VERSION,
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
    )
    try:
        backend.verify_and_start(get_client())
    except Exception:
        reset_client()
        raise
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
