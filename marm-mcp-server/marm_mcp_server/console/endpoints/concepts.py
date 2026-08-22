"""Concept graph endpoints for MARM Console."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...core import concept_review
from ...core.concept_build_lock import (
    MANUAL_BUILD_LOCK_SECONDS,
    ConceptBuildBusy,
    run_exclusive,
)
from ...core.concept_db import inspect_concept_schema
from .. import concept_store, mcp_client, memory_store
from ..concept_graph_overview import graph_overview
from ..concept_neighborhood import neighborhood
from ..core import _concepts_payload, _now_iso, get_concept_db_path, get_memory_db_path
from ..models import ConceptBuildPayload, ConceptGraphResetPayload

router = APIRouter()

_CONCEPT_BUILD_STALE_SECONDS = 300
_CONCEPT_BUILD_LAUNCH_TTL_SECONDS = 300
_launching_concept_builds: dict[str, tuple[dict, float]] = {}
_launching_concept_builds_lock = threading.Lock()


class DuplicatePairPayload(BaseModel):
    entity_a_id: int
    entity_b_id: int


class MergeDuplicatePayload(DuplicatePairPayload):
    keep: Literal["a", "b"]


def _prune_launching_concept_builds() -> None:
    cutoff = time.monotonic() - _CONCEPT_BUILD_LAUNCH_TTL_SECONDS
    with _launching_concept_builds_lock:
        for job_id, (_, launched_at) in list(_launching_concept_builds.items()):
            if launched_at < cutoff:
                _launching_concept_builds.pop(job_id, None)


def _stale_build_result(job: dict) -> dict:
    if job.get("status") not in {"queued", "running"}:
        return job
    timestamp = (
        job.get("last_progress_at") or job.get("started_at") or job.get("created_at")
    )
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
def get_concept_graph(
    full: bool = Query(False),
    project: str | None = None,
    session: str | None = None,
) -> dict:
    if project is not None and session is not None:
        raise HTTPException(
            status_code=422,
            detail="Choose either a project or session scope, not both.",
        )
    return graph_overview(
        get_concept_db_path(), force_full=full, project=project, session=session
    )


@router.get("/api/concepts/graph/version")
def get_concept_graph_version() -> dict:
    """Polled while the Explorer is open so background indexing shows up
    without a reload. Deliberately cheap: the atlas is only refetched when
    this value moves."""
    return concept_store.graph_version(get_concept_db_path())


@router.get("/api/concepts/duplicates")
def get_concept_duplicates(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
) -> dict:
    return concept_store.duplicate_report(
        get_concept_db_path(), offset=offset, limit=limit
    )


async def _run_review_action(
    purpose: str, action: Callable[..., dict[str, Any]], *args: Any
) -> dict[str, Any]:
    lease_lost = threading.Event()

    def protected_action(db_path: str, *action_args: Any) -> dict[str, Any]:
        return action(db_path, *action_args, lease_lost=lease_lost)

    try:
        return await run_exclusive(
            purpose,
            protected_action,
            get_concept_db_path(),
            *args,
            ttl_seconds=MANUAL_BUILD_LOCK_SECONDS,
            lease_lost=lease_lost,
        )
    except ConceptBuildBusy as exc:
        raise HTTPException(
            status_code=409,
            detail="A concept build is running. Try again after it finishes.",
        ) from exc
    except concept_review.ConceptReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/concepts/duplicates/dismiss")
async def dismiss_concept_duplicate(payload: DuplicatePairPayload) -> dict:
    return await _run_review_action(
        "duplicate_dismiss",
        concept_review.dismiss_duplicate,
        payload.entity_a_id,
        payload.entity_b_id,
    )


@router.post("/api/concepts/duplicates/merge")
async def merge_concept_duplicate(payload: MergeDuplicatePayload) -> dict:
    return await _run_review_action(
        "duplicate_merge",
        concept_review.merge_entities,
        payload.entity_a_id,
        payload.entity_b_id,
        payload.keep,
    )


@router.delete("/api/concepts/entities/{entity_id}")
async def remove_concept_entity(entity_id: int) -> dict:
    return await _run_review_action(
        "entity_remove", concept_review.remove_entity, entity_id
    )


@router.get("/api/concepts/{entity_id:int}")
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
    result = neighborhood(
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
def build_concepts(payload: ConceptBuildPayload) -> JSONResponse:
    if not (payload.session_name or payload.project or payload.search_all):
        raise HTTPException(
            status_code=422, detail="Choose a session, project, or all memory scope."
        )
    return _launch_concept_build(payload)


def _launch_concept_build(payload: ConceptBuildPayload) -> JSONResponse:
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
                "memories_total": 0,
                "entities_extracted": 0,
                "relationships_created": 0,
                "code_links_created": 0,
                "duplicate_candidates": 0,
                "duration_ms": None,
                "error_code": None,
                "created_at": _now_iso(),
                "started_at": None,
                "last_progress_at": None,
                "cancel_requested_at": None,
                "cancelled_at": None,
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
    except (mcp_client.McpUnavailable, mcp_client.McpRequestError) as exc:
        with _launching_concept_builds_lock:
            launch = _launching_concept_builds.get(job_id)
            if launch:
                failed, _ = launch
                failed.update(
                    status="error",
                    error_code=(
                        "mcp_request_error"
                        if isinstance(exc, mcp_client.McpRequestError)
                        else "mcp_unavailable"
                    ),
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


@router.get("/api/concepts/builds")
def list_concept_builds() -> list[dict]:
    _prune_launching_concept_builds()
    persisted = concept_store.build_runs(get_concept_db_path(), limit=100)
    persisted_ids = {run["id"] for run in persisted}
    with _launching_concept_builds_lock:
        launches = [
            dict(launch)
            for job_id, (launch, _) in _launching_concept_builds.items()
            if job_id not in persisted_ids
        ]
    return [
        _stale_build_result(job)
        for job in sorted(
            [*persisted, *launches],
            key=lambda job: str(job.get("created_at") or ""),
            reverse=True,
        )
    ]


@router.post("/api/concepts/builds/{run_id}/stop")
def stop_concept_build(run_id: str) -> dict:
    try:
        return mcp_client.post(f"internal/concepts/builds/{run_id}/stop", {})
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/concepts/builds/{run_id}/retry")
def retry_concept_build(run_id: str) -> JSONResponse:
    build_run = concept_store.get_build_run(get_concept_db_path(), run_id)
    if build_run is None:
        raise HTTPException(status_code=404, detail="Concept build not found")
    if build_run["status"] not in {"error", "degraded", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail="Only failed, degraded, or cancelled concept builds can be retried.",
        )
    if (
        build_run["scope_type"] != "all"
        and inspect_concept_schema(str(get_concept_db_path())) == "rebuild_required"
    ):
        raise HTTPException(
            status_code=409,
            detail="This graph needs an All memory (global) rebuild before scoped builds can run.",
        )
    scope_type = build_run["scope_type"]
    payload = ConceptBuildPayload(
        session_name=build_run["scope_value"] if scope_type == "session" else None,
        project=build_run["scope_value"] if scope_type == "project" else None,
        search_all=scope_type == "all",
    )
    return _launch_concept_build(payload)


@router.delete("/api/concepts/graph")
def delete_concept_graph(payload: ConceptGraphResetPayload) -> dict:
    try:
        return mcp_client.delete(
            "internal/concepts/graph", payload.model_dump(), timeout=60.0
        )
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
