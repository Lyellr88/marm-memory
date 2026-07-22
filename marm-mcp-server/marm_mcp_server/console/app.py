"""Standalone localhost API host for MARM Console.

The Console is intentionally separate from marm-mcp-server. It reads the
local MARM stores through its own bounded REST surface and never extends the
public MCP tool list.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import mcp_client
from .endpoints import (
    compaction,
    concepts,
    logs,
    memory,
    notebook,
    overview,
    projects,
    sessions,
)


def _allowed_origins() -> list[str]:
    configured = os.environ.get("MARM_CONSOLE_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or ["http://127.0.0.1:5173", "http://localhost:5173"]


logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _warm_project_cache() -> None:
    try:
        mcp_client.list_projects()
    except mcp_client.McpUnavailable:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "marm-console"}


if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def console_index():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        status_code=503,
        content={"detail": "MARM Console frontend assets are missing."},
    )


@app.get("/{path:path}", include_in_schema=False)
def console_spa_fallback(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    candidate = (STATIC_DIR / path).resolve()
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not Found") from None
    if candidate.is_file():
        return FileResponse(candidate)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        status_code=503,
        content={"detail": "MARM Console frontend assets are missing."},
    )
