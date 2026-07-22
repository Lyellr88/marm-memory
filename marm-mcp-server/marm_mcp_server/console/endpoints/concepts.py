"""Concept graph endpoints for MARM Console."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .. import concept_store, mcp_client, memory_store
from ..core import _concepts_payload, _now_iso, get_concept_db_path, get_memory_db_path
from ..models import ConceptBuildPayload

router = APIRouter()

_CONCEPT_BUILD_STALE_SECONDS = 300
_CONCEPT_BUILD_LAUNCH_TTL_SECONDS = 300
_launching_concept_builds: dict[str, tuple[dict, float]] = {}
_launching_concept_builds_lock = threading.Lock()


def _prune_launching_concept_builds() -> None:
    cutoff = time.monotonic() - _CONCEPT_BUILD_LAUNCH_TTL_SECONDS
    with _launching_concept_builds_lock:
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


@router.get("/api/concepts/summary")
def get_concepts_summary() -> dict:
    return _concepts_payload()


@router.get("/api/concepts/search")
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


@router.get("/api/concepts/graph")
def get_concept_graph() -> dict:
    return concept_store.graph_overview(get_concept_db_path())


@router.get("/api/concepts/{entity_id}")
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


@router.get("/api/concepts/{entity_id}/neighborhood")
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


@router.post("/api/concepts/build")
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
    with _launching_concept_builds_lock:
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
        with _launching_concept_builds_lock:
            launch = _launching_concept_builds.get(job_id)
            if launch:
                failed, _ = launch
                failed.update(
                    status="error",
                    error_code="mcp_unavailable",
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )


@router.get("/api/concepts/builds/{job_id}")
def get_concept_build(job_id: str) -> dict:
    _prune_launching_concept_builds()
    job = concept_store.get_build_run(get_concept_db_path(), job_id)
    if job is None:
        with _launching_concept_builds_lock:
            launch = _launching_concept_builds.get(job_id)
            # Copy while locked -- the background build thread can still
            # mutate this same dict object after the lock releases.
            job = dict(launch[0]) if launch else None
    if job is None:
        raise HTTPException(status_code=404, detail="Concept build not found")
    return _stale_build_result(job)


@router.get("/api/concepts/duplicates")
def get_concept_duplicates() -> list[dict]:
    return concept_store.duplicates(get_concept_db_path())
