"""Standalone localhost API host for MARM Console.

The Console is intentionally separate from marm-mcp-server. It reads the
local MARM stores through its own bounded REST surface and never extends the
public MCP tool list.
"""

from __future__ import annotations

import os
import time
import json
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import concept_store, mcp_client, memory_store


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

_CONCEPT_BUILD_STALE_SECONDS = 300
_CONCEPT_BUILD_LAUNCH_TTL_SECONDS = 300
_launching_concept_builds: dict[str, tuple[dict, float]] = {}


class ConceptBuildPayload(BaseModel):
    session_name: str | None = None
    project: str | None = None
    search_all: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prune_launching_concept_builds() -> None:
    cutoff = time.monotonic() - _CONCEPT_BUILD_LAUNCH_TTL_SECONDS
    for job_id, (_, launched_at) in list(_launching_concept_builds.items()):
        if launched_at < cutoff:
            _launching_concept_builds.pop(job_id, None)


def _stale_build_result(job: dict) -> dict:
    if job.get("status") not in {"queued", "running"}:
        return job
    timestamp = job.get("started_at") or job.get("created_at")
    if not timestamp:
        return job
    try:
        started_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return job
    age_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
    if age_seconds <= _CONCEPT_BUILD_STALE_SECONDS:
        return job
    return {
        **job,
        "status": "error",
        "error_code": "stale_run",
        "finished_at": _now_iso(),
    }


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


@app.get("/api/overview")
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


@app.get("/api/filters")
def get_filters() -> dict:
    try:
        return memory_store.filters(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/memories")
def get_memories(
    q: str | None = None,
    session: str | None = None,
    project: str | None = None,
    platform: str | None = None,
    context_type: str | None = None,
    compaction_role: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    try:
        return memory_store.list_memories(
            get_memory_db_path(),
            q=q,
            session=session,
            project=project,
            platform=platform,
            context_type=context_type,
            compaction_role=compaction_role,
            limit=limit,
            offset=offset,
        )
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/memories/{memory_id}")
def get_memory(memory_id: str) -> dict:
    try:
        memory = memory_store.get_memory(get_memory_db_path(), memory_id)
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@app.get("/api/sessions")
def get_sessions() -> list[dict]:
    try:
        return memory_store.list_sessions(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/logs")
def get_logs(
    q: str | None = None,
    session: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    try:
        return memory_store.list_logs(
            get_memory_db_path(), q=q, session=session, limit=limit
        )
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/notebook")
def get_notebook() -> list[dict]:
    try:
        return memory_store.list_notebook(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/summaries/{session_name}")
def get_session_summary(session_name: str) -> dict:
    try:
        return memory_store.get_summary(get_memory_db_path(), session_name)
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/compaction")
def get_compaction() -> list[dict]:
    try:
        return memory_store.list_compaction(get_memory_db_path())
    except memory_store.MemoryStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/concepts/summary")
def get_concepts_summary() -> dict:
    return _concepts_payload()


@app.get("/api/concepts/search")
def search_concepts(
    q: str | None = None,
    project: str | None = None,
    session: str | None = None,
    type: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> list[dict]:
    return concept_store.search(
        get_concept_db_path(),
        q=q,
        project=project,
        session=session,
        entity_type=type,
        limit=limit,
    )


@app.get("/api/concepts/graph")
def get_concept_graph(limit: int = Query(150, ge=10, le=300)) -> dict:
    return concept_store.graph_overview(get_concept_db_path(), limit_nodes=limit)


@app.get("/api/concepts/{entity_id}")
def get_concept(entity_id: int) -> dict:
    entity = concept_store.get_entity(get_concept_db_path(), entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Concept not found")
    try:
        entity["source_memories"] = memory_store.get_memories_by_ids(
            get_memory_db_path(), entity["source_memory_ids"]
        )
    except memory_store.MemoryStoreUnavailable:
        entity["source_memories"] = []
    return entity


@app.get("/api/concepts/{entity_id}/neighborhood")
def get_concept_neighborhood(
    entity_id: int,
    depth: int = Query(1, ge=1, le=3),
    direction: str = Query("both", pattern="^(incoming|outgoing|both)$"),
    predicate: str | None = Query(None, max_length=100),
) -> dict:
    result = concept_store.neighborhood(
        get_concept_db_path(),
        entity_id,
        depth=depth,
        direction=direction,
        predicate=predicate,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Concept not found")
    return result


@app.post("/api/concepts/build")
def build_concepts(payload: ConceptBuildPayload) -> dict:
    if not (payload.session_name or payload.project or payload.search_all):
        raise HTTPException(
            status_code=422, detail="Choose a session, project, or all memory scope."
        )
    job_id = str(uuid.uuid4())
    _prune_launching_concept_builds()
    scope_type = (
        "session" if payload.session_name else "project" if payload.project else "all"
    )
    _launching_concept_builds[job_id] = (
        {
            "id": job_id,
            "scope_type": scope_type,
            "scope_value": payload.session_name or payload.project,
            "status": "queued",
            "memories_processed": 0,
            "entities_extracted": 0,
            "relationships_created": 0,
            "code_links_created": 0,
            "duplicate_candidates": 0,
            "duration_ms": None,
            "error_code": None,
            "created_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
        },
        time.monotonic(),
    )
    threading.Thread(
        target=_run_concept_build,
        args=(job_id, payload.model_dump(exclude_none=True)),
        daemon=True,
    ).start()
    return JSONResponse(status_code=202, content={"job_id": job_id})


def _run_concept_build(job_id: str, payload: dict) -> None:
    payload["run_id"] = job_id
    try:
        mcp_client.post("marm_concept_build", payload, timeout=120.0)
    except mcp_client.McpUnavailable:
        launch = _launching_concept_builds.get(job_id)
        if launch:
            failed, _ = launch
            failed.update(
                status="error",
                error_code="mcp_unavailable",
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )


@app.get("/api/concepts/builds/{job_id}")
def get_concept_build(job_id: str) -> dict:
    _prune_launching_concept_builds()
    job = concept_store.get_build_run(get_concept_db_path(), job_id)
    if job is None:
        launch = _launching_concept_builds.get(job_id)
        job = launch[0] if launch else None
    if job is None:
        raise HTTPException(status_code=404, detail="Concept build not found")
    return _stale_build_result(job)


@app.get("/api/concepts/duplicates")
def get_concept_duplicates() -> list[dict]:
    return concept_store.duplicates(get_concept_db_path())


@app.get("/api/projects")
def get_projects() -> list[dict]:
    try:
        return mcp_client.list_projects()
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
