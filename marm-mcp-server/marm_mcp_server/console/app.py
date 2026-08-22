"""Standalone localhost API host for MARM Console.

The Console is intentionally separate from marm-mcp-server. It reads the
local MARM stores through its own bounded REST surface and never extends the
public MCP tool list.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import auth, mcp_client
from .endpoints import (
    compaction,
    concepts,
    logs,
    memory,
    notebook,
    overview,
    projects,
    sessions,
    settings,
)


def _allowed_origins() -> list[str]:
    configured = os.environ.get("MARM_CONSOLE_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or ["http://127.0.0.1:5173", "http://localhost:5173"]


def _allowed_hosts() -> list[str]:
    configured = os.environ.get("MARM_CONSOLE_ALLOWED_HOSTS", "")
    hosts = [host.strip() for host in configured.split(",") if host.strip()]
    if hosts:
        return hosts
    bind_host = os.environ.get("MARM_CONSOLE_HOST", "127.0.0.1").strip("[]")
    hosts = ["127.0.0.1", "localhost", "::1", "testserver"]
    if bind_host not in {"", "0.0.0.0", "::"}:
        hosts.append(bind_host)
    return list(dict.fromkeys(hosts))


logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
ROOT_STATIC_ASSETS = (
    {asset.name: asset for asset in STATIC_DIR.iterdir() if asset.is_file()}
    if STATIC_DIR.is_dir()
    else {}
)


def _warm_project_cache() -> None:
    try:
        mcp_client.list_projects()
    except mcp_client.McpUnavailable:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if not (STATIC_DIR / "index.html").exists():
        logger.warning(
            "MARM Console frontend assets are missing; API remains available."
        )
    threading.Thread(target=_warm_project_cache, daemon=True).start()
    yield


app = FastAPI(
    title="MARM Console",
    description="Standalone local control plane for marm-memory.",
    version="0.1.0",
    lifespan=lifespan,
)


class _ConsoleBootstrapRequest(BaseModel):
    token: str


@app.middleware("http")
async def console_api_auth(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Apply MARM's auth policy to Console data APIs, not static SPA assets."""
    if request.method == "OPTIONS" or not request.url.path.startswith("/api/"):
        return await call_next(request)
    if request.url.path == "/api/auth/bootstrap":
        return await call_next(request)

    if auth.valid_browser_session(request.cookies.get("marm_console_session")):
        return await call_next(request)

    api_key = os.environ.get("MARM_API_KEY", "")
    if not api_key:
        from ..config.settings import MARM_API_KEY

        api_key = MARM_API_KEY
    if not api_key:
        client_ip = request.client.host if request.client else ""
        if client_ip in {"127.0.0.1", "::1", "localhost", "testclient"}:
            return await call_next(request)
    else:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and secrets.compare_digest(
            auth_header[7:], api_key
        ):
            return await call_next(request)

    return JSONResponse(
        status_code=401,
        content={"detail": "Valid MARM API authentication is required."},
        headers={"WWW-Authenticate": "Bearer"},
    )


app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


app.include_router(overview.router)
app.include_router(memory.router)
app.include_router(sessions.router)
app.include_router(logs.router)
app.include_router(notebook.router)
app.include_router(compaction.router)
app.include_router(concepts.router)
app.include_router(projects.router)
app.include_router(settings.router)


@app.post("/api/auth/bootstrap", include_in_schema=False)
def bootstrap_console_session(payload: _ConsoleBootstrapRequest) -> JSONResponse:
    """Exchange a local one-time handoff for an HttpOnly browser session."""
    from ..core.runtime_manager import runtime_dir

    if not auth.consume_bootstrap_token(runtime_dir(), payload.token):
        raise HTTPException(status_code=401, detail="Console bootstrap has expired.")
    response = JSONResponse({"status": "authenticated"})
    response.set_cookie(
        "marm_console_session",
        auth.create_browser_session(),
        max_age=8 * 60 * 60,
        httponly=True,
        samesite="strict",
        secure=False,
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "marm-console"}


if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def console_index() -> Response:
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        status_code=503,
        content={"detail": "MARM Console frontend assets are missing."},
    )


@app.get("/{path:path}", include_in_schema=False)
def console_spa_fallback(path: str) -> Response:
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    root_asset = ROOT_STATIC_ASSETS.get(path)
    if root_asset is not None and root_asset.is_file():
        return FileResponse(root_asset)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        status_code=503,
        content={"detail": "MARM Console frontend assets are missing."},
    )
