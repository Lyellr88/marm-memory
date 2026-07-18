"""Standalone localhost API host for MARM Console.

The Console is intentionally separate from marm-mcp-server. It reads the
local MARM stores through its own bounded REST surface and never extends the
public MCP tool list.
"""

from __future__ import annotations

import os
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


app = FastAPI(
    title="MARM Console",
    description="Standalone local control plane for marm-memory.",
    version="0.1.0",
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


def _warm_project_cache() -> None:
    try:
        mcp_client.list_projects()
    except mcp_client.McpUnavailable:
        pass


@app.on_event("startup")
def warm_optional_graph_data() -> None:
    threading.Thread(target=_warm_project_cache, daemon=True).start()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "marm-console"}
