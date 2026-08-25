import asyncio
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config.settings import CONCEPTS_AVAILABLE
from ..core import concept_queue
from ..core.concept_build_lock import (
    MANUAL_BUILD_LOCK_SECONDS,
    ConceptBuildBusy,
    concept_build_lock,
    run_exclusive,
)
from ..core.concept_db import (
    get_concept_db_path,
    inspect_concept_schema,
    mark_schema_current,
)
from ..core.models import ConceptBuildRequest, ConceptRecallRequest
from ..services.concept_build_engine import (
    _MISSING_BUILD_SCOPE_MESSAGE,
    _build_for_memory_ids_sync,
    _fetch_memory_pages,
    _get_concept_db,
    _run_build,
    count_memory_rows,
    reset_and_rebuild_concept_db,
)
from ..services.graph_context import get_graph_context

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="", tags=["Concepts"])

_concept_build_lock = asyncio.Lock()

_CONCEPTS_UNAVAILABLE_MESSAGE = (
    "Concept extraction is unavailable. Reinstall marm-mcp-server and run "
    "marm-memory knowledge status to verify the local installation."
)


class ConceptGraphResetRequest(BaseModel):
    confirm: Literal["DELETE_GRAPH"]


def _scope_for_build(req: ConceptBuildRequest) -> tuple[str, Optional[str]]:
    if req.session_name:
        return "session", req.session_name
    if req.project:
        return "project", req.project
    return "all", None


def _create_build_run(req: ConceptBuildRequest, run_id: str, created_at: str) -> None:
    scope_type, scope_value = _scope_for_build(req)
    concept_db = _get_concept_db()
    with concept_db.get_connection() as conn:
        concept_db.create_build_run(
            conn,
            run_id=run_id,
            scope_type=scope_type,
            scope_value=scope_value,
            created_at=created_at,
        )


def _finish_build_run(
    run_id: str,
    *,
    only_statuses: tuple[str, ...] | None = None,
    require_cancellation: bool | None = None,
    **fields: object,
) -> bool:
    concept_db = _get_concept_db()
    with concept_db.get_connection() as conn:
        return concept_db.update_build_run(
            conn,
            run_id,
            only_statuses=only_statuses,
            require_cancellation=require_cancellation,
            **fields,
        )


def _record_build_progress(
    run_id: str,
    memories_processed: int,
    entities_extracted: int,
    relationships_created: int,
    code_links_created: int,
) -> None:
    try:
        _finish_build_run(
            run_id,
            memories_processed=memories_processed,
            entities_extracted=entities_extracted,
            relationships_created=relationships_created,
            code_links_created=code_links_created,
        )
    except Exception as e:
        logger.warning("concepts.build_progress_update_error", error=str(e))


def _is_build_cancellation_requested(run_id: str) -> bool:
    try:
        concept_db = _get_concept_db()
        with concept_db.get_connection() as conn:
            return concept_db.is_build_cancellation_requested(conn, run_id)
    except Exception as exc:
        logger.warning("concepts.build_cancel_check_error", error=str(exc))
        return False


def _request_build_cancellation(run_id: str) -> tuple[dict | None, bool]:
    concept_db = _get_concept_db()
    with concept_db.get_connection() as conn:
        return concept_db.request_build_cancellation(
            conn, run_id, datetime.now(timezone.utc).isoformat()
        )


def _reset_concept_graph() -> str:
    concept_db = _get_concept_db()
    with concept_db.get_connection() as conn:
        concept_db.abandon_unowned_build_runs(
            conn, datetime.now(timezone.utc).isoformat()
        )
    return reset_and_rebuild_concept_db(get_concept_db_path())


def _prepare_build_schema(req: ConceptBuildRequest) -> bool:
    """Return whether a historical graph was backed up and reset."""
    db_path = get_concept_db_path()
    state = inspect_concept_schema(db_path)
    if state == "unavailable":
        raise RuntimeError("concept database unavailable")
    if state != "rebuild_required":
        return False
    if not req.search_all:
        raise ValueError("rebuild_required")

    reset_and_rebuild_concept_db(db_path)
    return True


def _run_recall(
    query: str,
    session_name: Optional[str],
    limit: int,
    depth: int = 1,
    direction: str = "both",
    project: Optional[str] = None,
    platform: Optional[str] = None,
) -> dict:
    context = get_graph_context(
        query=query,
        session_name=session_name,
        project=project,
        platform=platform,
        limit=limit,
        depth=depth,
        direction=direction,
    )
    return {
        "status": context["status"],
        "entities": context["entities"],
        "related_entities": context["related_entities"],
        "linked_code": context["linked_code"],
        "truncated": context["truncated"],
    }


@router.post("/marm_concept_build", operation_id="marm_concept_build")
async def marm_concept_build(req: ConceptBuildRequest) -> dict:
    """🕸️ Extract entities/relationships from memory content into the concept graph.

    Scope with session_name or project for a targeted build, or pass
    search_all=True for everything. Links extracted entities to
    marm-graph code symbols when available. Call this before marm_concept_recall
    — there's no data until a build has run at least once.
    """
    try:
        async with concept_build_lock(
            "manual_build", MANUAL_BUILD_LOCK_SECONDS
        ) as lease:
            async with _concept_build_lock:
                return await _marm_concept_build(req, lease.lost)
    except ConceptBuildBusy:
        return {
            "status": "error",
            "error_code": "build_in_progress",
            "message": (
                "Another MARM process is writing the concept graph. "
                "Wait for it to finish and run this again."
            ),
        }


async def _marm_concept_build(
    req: ConceptBuildRequest, abort: Optional[threading.Event] = None
) -> dict:
    if not (req.session_name or req.project or req.search_all):
        return {"status": "error", "message": _MISSING_BUILD_SCOPE_MESSAGE}

    run_id = req.run_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    if not CONCEPTS_AVAILABLE:
        try:
            await asyncio.to_thread(_create_build_run, req, run_id, created_at)
        except Exception as e:
            logger.warning("concepts.build_run_create_error", error=str(e))
            return {"status": "error", "message": "Concept build failed."}
        degraded = {
            "status": "degraded",
            "error_code": "concepts_unavailable",
            "message": _CONCEPTS_UNAVAILABLE_MESSAGE,
            "entities_extracted": 0,
            "relationships_created": 0,
            "code_links_created": 0,
            "possible_duplicates": [],
            "duration_ms": 0,
        }
        await asyncio.to_thread(
            _finish_build_run,
            run_id,
            status="degraded",
            error_code="concepts_unavailable",
            finished_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=0,
        )
        degraded["build_run_id"] = run_id
        return degraded
    try:
        graph_rebuilt = await asyncio.to_thread(_prepare_build_schema, req)
    except ValueError:
        try:
            await asyncio.to_thread(_create_build_run, req, run_id, created_at)
            await asyncio.to_thread(
                _finish_build_run,
                run_id,
                status="error",
                error_code="rebuild_required",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logger.warning("concepts.build_run_create_error", error=str(e))
        return {
            "status": "error",
            "error_code": "rebuild_required",
            "message": (
                "The concept graph must be rebuilt with "
                "marm_concept_build(search_all=True)."
            ),
            "build_run_id": run_id,
        }
    except Exception as e:
        logger.warning("concepts.schema_prepare_error", error=str(e))
        return {
            "status": "error",
            "message": "Concept build failed.",
            "build_run_id": run_id,
        }
    try:
        await asyncio.to_thread(_create_build_run, req, run_id, created_at)
    except Exception as e:
        logger.warning("concepts.build_run_create_error", error=str(e))
        return {"status": "error", "message": "Concept build failed."}

    start = time.monotonic()
    try:
        await asyncio.to_thread(
            _finish_build_run,
            run_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        memories_total = await asyncio.to_thread(
            count_memory_rows, req.session_name, req.project, req.search_all
        )
        await asyncio.to_thread(
            _finish_build_run, run_id, memories_total=memories_total
        )
        pages = _fetch_memory_pages(req.session_name, req.project, req.search_all)
        outcomes: dict[str, str] = {}
        result = await asyncio.to_thread(
            _run_build,
            pages,
            outcomes,
            abort,
            progress_callback=lambda processed, entities, relationships, code_links: (
                _record_build_progress(
                    run_id, processed, entities, relationships, code_links
                )
            ),
            cancel_requested=lambda: _is_build_cancellation_requested(run_id),
        )
    except ValueError:
        await asyncio.to_thread(
            _finish_build_run,
            run_id,
            status="error",
            error_code="invalid_scope",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return {
            "status": "error",
            "message": _MISSING_BUILD_SCOPE_MESSAGE,
            "build_run_id": run_id,
        }
    except Exception as e:
        logger.warning("concepts.build_error", error=str(e))
        await asyncio.to_thread(
            _finish_build_run,
            run_id,
            status="error",
            error_code="build_failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return {
            "status": "error",
            "message": "Concept build failed.",
            "build_run_id": run_id,
        }

    result["duration_ms"] = int((time.monotonic() - start) * 1000)
    if result["aborted"]:
        await asyncio.to_thread(
            _finish_build_run,
            run_id,
            status="error",
            error_code="lock_lost",
            memories_processed=result["memories_processed"],
            duration_ms=result["duration_ms"],
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return {
            "status": "error",
            "error_code": "lock_lost",
            "message": (
                "This build lost the concept graph to another MARM process and "
                "stopped partway. Run it again once that one finishes."
            ),
            "memories_processed": result["memories_processed"],
            "build_run_id": run_id,
        }
    if result["cancelled"]:
        cancelled_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            _finish_build_run,
            run_id,
            status="cancelled",
            error_code="cancelled_by_user",
            memories_processed=result["memories_processed"],
            entities_extracted=result["entities_extracted"],
            relationships_created=result["relationships_created"],
            code_links_created=result["code_links_created"],
            duration_ms=result["duration_ms"],
            cancelled_at=cancelled_at,
            finished_at=cancelled_at,
        )
        return {
            "status": "cancelled",
            "error_code": "cancelled_by_user",
            "message": "The concept build was stopped after its current memory.",
            "memories_processed": result["memories_processed"],
            "build_run_id": run_id,
        }
    await _retire_queued_tasks(outcomes, created_at)
    completed = await asyncio.to_thread(
        _finish_build_run,
        run_id,
        only_statuses=("running",),
        require_cancellation=False,
        status="success",
        memories_processed=result["memories_processed"],
        entities_extracted=result["entities_extracted"],
        relationships_created=result["relationships_created"],
        code_links_created=result["code_links_created"],
        duplicate_candidates=len(result["possible_duplicates"]),
        duration_ms=result["duration_ms"],
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    if not completed:
        cancelled_at = datetime.now(timezone.utc).isoformat()
        cancelled = await asyncio.to_thread(
            _finish_build_run,
            run_id,
            only_statuses=("queued", "running"),
            require_cancellation=True,
            status="cancelled",
            error_code="cancelled_by_user",
            memories_processed=result["memories_processed"],
            entities_extracted=result["entities_extracted"],
            relationships_created=result["relationships_created"],
            code_links_created=result["code_links_created"],
            duration_ms=result["duration_ms"],
            cancelled_at=cancelled_at,
            finished_at=cancelled_at,
        )
        if cancelled:
            return {
                "status": "cancelled",
                "error_code": "cancelled_by_user",
                "message": "The concept build was stopped after its current memory.",
                "memories_processed": result["memories_processed"],
                "build_run_id": run_id,
            }
        return {
            "status": "error",
            "error_code": "build_state_conflict",
            "message": "The concept build finished in another MARM process.",
            "build_run_id": run_id,
        }
    result.pop("aborted", None)
    result.pop("cancelled", None)
    if graph_rebuilt:
        try:
            await asyncio.to_thread(mark_schema_current, get_concept_db_path())
        except Exception as e:
            logger.warning("concepts.schema_mark_failed", error=str(e))
    result["graph_rebuilt"] = graph_rebuilt
    result["build_run_id"] = run_id
    return result


@router.post("/internal/concepts/builds/{run_id}/stop")
async def stop_concept_build(run_id: str) -> dict:
    build_run, cancellation_requested = await asyncio.to_thread(
        _request_build_cancellation, run_id
    )
    if build_run is None:
        raise HTTPException(status_code=404, detail="Concept build not found")
    if not cancellation_requested:
        raise HTTPException(
            status_code=409,
            detail="Only queued or running concept builds can be stopped.",
        )
    return {
        "status": "cancellation_requested",
        "run_id": run_id,
        "cancel_requested_at": build_run["cancel_requested_at"],
    }


@router.delete("/internal/concepts/graph")
async def reset_concept_graph(payload: ConceptGraphResetRequest) -> dict:
    del payload
    try:
        backup_path = await run_exclusive(
            "manual_reset",
            _reset_concept_graph,
            ttl_seconds=MANUAL_BUILD_LOCK_SECONDS,
        )
    except ConceptBuildBusy as exc:
        raise HTTPException(
            status_code=409,
            detail="Stop the active concept build before deleting the graph.",
        ) from exc
    return {
        "status": "reset",
        "backup_created": bool(backup_path),
        "schema_status": "rebuild_required",
    }


async def _retire_queued_tasks(outcomes: dict[str, str], build_started_at: str) -> None:
    """Clear queue rows this build has already covered.

    Only ids the build actually settled, and only rows queued before it
    started: anything written or merged mid-build re-stamps enqueued_at and
    survives, and a memory whose extraction failed was never settled so its
    retry is untouched. Without this the forced rebuild in v2.36.0 would leave
    the whole corpus queued behind the build that just indexed it.
    """
    settled = [
        memory_id
        for memory_id, outcome in outcomes.items()
        if outcome in ("indexed", "no_entities")
    ]
    if not settled:
        return
    try:
        retired = await asyncio.to_thread(
            concept_queue.retire_indexed, settled, build_started_at
        )
        if retired:
            logger.info("concepts.queue_retired", tasks=retired)
    except Exception as e:
        logger.warning("concepts.queue_retire_failed", error=str(e))


async def build_for_memory_ids(
    memory_ids: list[str],
    abort: Optional[threading.Event] = None,
    finished: Optional[threading.Event] = None,
) -> dict[str, str]:
    """Index a specific set of memories. Returns one outcome per requested id:
    indexed, no_entities, failed, or vanished.

    Not a route and not an MCP tool. The background indexing worker is the
    only caller, and it settles queue tasks on these outcomes rather than on
    whether this raised. Takes _concept_build_lock, so the worker and a manual
    marm_concept_build can never write the concept DB concurrently.

    Refuses outright on an unavailable or stale graph. Writing incremental
    entities into a graph that is already flagged for rebuild would mix two
    extraction rules in one database, and settling those tasks would mean the
    rebuild never sees them.

    An empty result means the batch was abandoned partway because the graph
    lock was lost. The caller must settle nothing in that case.

    `finished` is set exactly once by the time this returns or raises, on every
    path including the refusals below. The caller's shutdown handshake blocks on
    it, so a path that skipped it would stall teardown for a full grace period
    over a build that never started."""
    try:
        if not memory_ids:
            return {}
        if not CONCEPTS_AVAILABLE:
            raise RuntimeError("concept extraction unavailable")
        state = await asyncio.to_thread(inspect_concept_schema, get_concept_db_path())
        if state == "rebuild_required":
            raise RuntimeError("rebuild_required")
        if state == "unavailable":
            raise RuntimeError("concept database unavailable")
        async with _concept_build_lock:
            return await asyncio.to_thread(
                _build_for_memory_ids_sync, memory_ids, abort, finished
            )
    finally:
        if finished is not None:
            finished.set()


@router.post("/marm_concept_recall", operation_id="marm_concept_recall")
async def marm_concept_recall(req: ConceptRecallRequest) -> dict:
    """🔎 Search the concept graph: entities, their relationships, and linked code.

    Query as a bare concept name for a lookup, or phrase it as "related to X"
    to emphasize traversal — both route from query shape alone. Pass depth
    to traverse multiple hops (default 1 = direct neighbors only), direction
    to scope traversal (outgoing/incoming/both), and project/platform to scope
    provenance (entities with the same name in different scopes are distinct
    nodes -- omit either filter to search across it). Returns empty lists (not an error)
    when marm_concept_build hasn't run yet or marm-graph has no matching
    code symbols.
    """
    try:
        args = (
            req.query,
            req.session_name,
            req.limit,
            req.depth,
            req.direction,
            req.project,
        )
        if req.platform is None:
            return await asyncio.to_thread(_run_recall, *args)
        return await asyncio.to_thread(_run_recall, *args, req.platform)
    except Exception as e:
        logger.warning("concepts.recall_error", error=str(e))
        return {"status": "error", "message": "Concept recall failed."}
