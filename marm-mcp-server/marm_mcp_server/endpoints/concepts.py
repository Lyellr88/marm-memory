"""Concept graph endpoints — marm_concept_build, marm_concept_recall.

Orchestration layer: build reads memory rows directly (never through
marm_smart_recall's ranked/limited recall path — see marm-index-spec.md's
"Build reads the memory DB layer directly" section), runs spaCy extraction,
writes to the concept graph's own SQLite file, and soft-links against
marm-graph. Recall reads the concept graph tables and infers lookup vs
related-to intent from query shape.
"""

import asyncio
import itertools
import threading
import time
import uuid
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter

from ..config.settings import (
    CONCEPT_BUILD_ROW_CAP,
    CONCEPTS_AVAILABLE,
    CONCEPT_DUPLICATE_SIMILARITY_THRESHOLD,
)
from ..core.concept_db import (
    ConceptDB,
    backup_and_reset_concept_database,
    get_concept_db_path,
    inspect_concept_schema,
)
from ..core import concept_queue
from ..core.concept_build_lock import (
    MANUAL_BUILD_LOCK_SECONDS,
    ConceptBuildBusy,
    concept_build_lock,
)
from ..core.concept_extraction import extract_entities
from ..core.graph_client import find_code_match, is_graph_available
from ..core.memory import memory
from ..core.memory_utils import _embedding_to_bytes, _safe_print
from ..core.models import ConceptBuildRequest, ConceptRecallRequest
from ..services.graph_context import get_graph_context, traverse_graph

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="", tags=["Concepts"])

_concept_db: Optional[ConceptDB] = None
_concept_db_lock = threading.Lock()
_concept_build_lock = asyncio.Lock()

MemoryRow = tuple[str, str, Optional[str], Optional[str], Optional[str]]
MemoryPage = list[MemoryRow]

# Shared by the scope path and the targeted path so the two can never drift
# into indexing different corpora. A compaction source owns its concepts and
# the generated summary restates them, so extracting both double-counts every
# entity in a compacted session. Recall makes the opposite choice on purpose:
# it wants the summary, the graph wants the originals.
_BUILD_ROW_FILTERS = (
    "session_name != 'marm_system'",
    "content IS NOT NULL",
    "content != ''",
    "(compaction_role IS NULL OR compaction_role != 'summary')",
)


def _get_concept_db() -> ConceptDB:
    """Lazy singleton, mirrors memory.py's own lazy-init style for optional
    subsystems — the concept DB file is only created on first real use.
    Both tools dispatch via asyncio.to_thread, so first-use is genuinely
    concurrent-capable; the lock mirrors graph_supervisor.py's own
    double-checked lazy-init pattern to avoid two concurrent first calls
    each constructing (and one leaking) a ConceptDB/connection pool."""
    global _concept_db
    if _concept_db is not None:
        return _concept_db
    with _concept_db_lock:
        if _concept_db is None:
            _concept_db = ConceptDB()
    return _concept_db


_MISSING_BUILD_SCOPE_MESSAGE = (
    "marm_concept_build requires session_name, project, or "
    "search_all=True to scope the build."
)

_CONCEPTS_UNAVAILABLE_MESSAGE = (
    "Concept extraction is unavailable. Reinstall marm-mcp-server and run "
    "marm-memory knowledge status to verify the local installation."
)


def _fetch_memory_pages(
    session_name: Optional[str], project: Optional[str], search_all: bool
) -> Iterator[MemoryPage]:
    """Deterministic read from the memory DB layer directly, paged rather
    than truncated. Never goes through marm_smart_recall — no ranking here.

    Requires at least one of session_name/project/search_all -- without this,
    an omitted session_name silently fell through to scanning every memory
    in the DB, making search_all's "explicit opt-in for everything"
    meaningless. Validated before the generator is built so the caller still
    gets the ValueError at call time, not on first iteration."""
    if not (session_name or project or search_all):
        raise ValueError(_MISSING_BUILD_SCOPE_MESSAGE)

    conditions = list(_BUILD_ROW_FILTERS)
    params: list = []

    if not search_all:
        if session_name:
            conditions.append("session_name = ?")
            params.append(session_name)
        if project:
            conditions.append("project = ?")
            params.append(project)

    return _paged_memory_rows(conditions, params)


def _paged_memory_rows(conditions: list[str], params: list) -> Iterator[MemoryPage]:
    """Keyset-paginated scan, CONCEPT_BUILD_ROW_CAP rows per page.

    Keyed on (created_at, id), never created_at alone: created_at defaults to
    CURRENT_TIMESTAMP, which is second-granular, so a burst of writes shares
    one value and an OFFSET or single-column keyset would skip or repeat rows
    at every page boundary. Descending order means rows written during a long
    build sort ahead of the cursor and are never revisited."""
    cursor: Optional[tuple[str, str]] = None
    while True:
        page_conditions = list(conditions)
        page_params = list(params)
        if cursor is not None:
            page_conditions.append("(created_at < ? OR (created_at = ? AND id < ?))")
            page_params.extend((cursor[0], cursor[0], cursor[1]))

        query = (
            "SELECT id, content, session_name, project, platform, created_at "
            f"FROM memories WHERE {' AND '.join(page_conditions)} "
            "ORDER BY created_at DESC, id DESC LIMIT ?"
        )
        page_params.append(CONCEPT_BUILD_ROW_CAP)

        with memory.get_connection() as conn:
            page = conn.execute(query, page_params).fetchall()

        if not page:
            return
        cursor = (page[-1][5], page[-1][0])
        yield [row[:5] for row in page]
        if len(page) < CONCEPT_BUILD_ROW_CAP:
            return


def _fetch_memory_rows_by_ids(memory_ids: list[str]) -> MemoryPage:
    """Targeted read for the incremental path. No pagination: the caller
    passes a bounded batch. Applies the same filters as a scope build, so an
    id that now points at a summary, an emptied row, or nothing at all simply
    comes back missing and the caller settles it as vanished."""
    if not memory_ids:
        return []
    placeholders = ",".join("?" * len(memory_ids))
    query = (
        "SELECT id, content, session_name, project, platform FROM memories "
        f"WHERE id IN ({placeholders}) AND {' AND '.join(_BUILD_ROW_FILTERS)}"
    )
    with memory.get_connection() as conn:
        return conn.execute(query, memory_ids).fetchall()


def _try_embed(name: str) -> Optional[bytes]:
    """Best-effort entity-name embedding for duplicate-candidate detection.
    None on any failure -- fail-open, matching find_code_match's soft-fail
    contract. This is the first place the concept graph reaches into
    memory._encoder_lock (core/memory.py:178-181, fully serialized
    process-wide) -- a large search_all=True build embedding many new
    entity names now competes for encoder time with concurrent
    marm_smart_recall/memory-write calls, a new cross-feature coupling
    that didn't exist before (spaCy extraction was fully independent of
    the memory-write path)."""
    if not memory._load_encoder_lazily():
        return None
    try:
        return _embedding_to_bytes(memory._encode_sync(name))
    except Exception as e:
        _safe_print(f"Concept entity embedding failed for {name!r}: {e}")
        return None


def _run_build(
    pages: Iterable[MemoryPage],
    outcomes: Optional[dict[str, str]] = None,
    abort: Optional[threading.Event] = None,
) -> dict:
    """Consumes pages lazily so a full-corpus build never holds every row in
    memory at once. The concept connection and embed_cache stay outside the
    page loop, so both still span the whole build.

    Pass a dict as outcomes to have each memory's result recorded in it. The
    aggregate counters cannot carry that: a build in which every extraction
    failed returns success with zeros, and a caller settling queue tasks on
    that would delete work it promised to retry. It is an out-parameter rather
    than a return value so it cannot end up in the route's response, where a
    full build would attach one entry per memory to a 1MB-bounded reply.

    Pass an abort event to make the build stoppable between memories. A
    process stalled longer than its whole lease loses the cross-process lock,
    and a thread already running cannot be killed from outside; this is how it
    stops writing alongside the new owner rather than running to completion.
    The result carries `aborted` so the caller settles nothing."""
    concept_db = _get_concept_db()
    memories_processed = 0
    aborted = False
    entities_extracted = 0
    relationships_created = 0
    code_links_created = 0
    graph_available = is_graph_available()
    possible_duplicates: list[dict] = []
    # Memoized per build, not per call: get_or_create_entity only ever
    # stores the embedding on the INSERT branch (re-mentions ignore it), so
    # without this cache, a name repeated across many memories in one
    # search_all=True build re-runs the (process-wide, encoder-lock-
    # serialized) encode for a result that's thrown away every time but the
    # first. Same input text always produces the same embedding, so caching
    # is always safe.
    embed_cache: dict[str, Optional[bytes]] = {}

    with concept_db.get_connection() as conn:
        for row in itertools.chain.from_iterable(pages):
            if abort is not None and abort.is_set():
                aborted = True
                break
            mem_id, content, mem_session, mem_project = row[:4]
            mem_platform = row[4] if len(row) > 4 else None
            memories_processed += 1
            try:
                result = extract_entities(content)
            except Exception as e:
                _safe_print(f"Concept extraction failed for memory {mem_id}: {e}")
                if outcomes is not None:
                    outcomes[mem_id] = "failed"
                continue

            memory_failed = False
            name_to_id: dict[str, int] = {}
            for entity in result.entities:
                if entity.name not in embed_cache:
                    embed_cache[entity.name] = _try_embed(entity.name)
                emb_bytes = embed_cache[entity.name]
                try:
                    entity_id, was_created = concept_db.get_or_create_entity(
                        conn,
                        entity.name,
                        entity.type,
                        mem_session,
                        mem_project,
                        mem_id,
                        name_embedding=emb_bytes,
                        platform=mem_platform,
                    )
                except Exception as e:
                    _safe_print(f"Concept entity write failed for memory {mem_id}: {e}")
                    memory_failed = True
                    continue
                name_to_id[entity.name] = entity_id
                entities_extracted += 1

                if was_created and emb_bytes is not None:
                    try:
                        candidates = concept_db.find_similar_entities(
                            conn,
                            emb_bytes,
                            mem_session,
                            mem_project,
                            CONCEPT_DUPLICATE_SIMILARITY_THRESHOLD,
                            exclude_id=entity_id,
                            platform=mem_platform,
                        )
                    except Exception as e:
                        _safe_print(f"Concept duplicate-candidate scan failed: {e}")
                        candidates = []
                    if candidates:
                        possible_duplicates.append(
                            {"entity": entity.name, "candidates": candidates}
                        )

            for name_a, name_b, predicate in result.relationship_pairs:
                id_a = name_to_id.get(name_a)
                id_b = name_to_id.get(name_b)
                if id_a is None or id_b is None:
                    continue
                try:
                    if concept_db.store_relationship(
                        conn,
                        id_a,
                        id_b,
                        predicate,
                        mem_id,
                        mem_project,
                        platform=mem_platform,
                    ):
                        relationships_created += 1
                except Exception as e:
                    _safe_print(
                        f"Concept relationship write failed for memory {mem_id}: {e}"
                    )
                    memory_failed = True

            if graph_available:
                for entity in result.entities:
                    entity_id = name_to_id.get(entity.name)
                    if entity_id is None:
                        continue
                    try:
                        match = find_code_match(entity.name, mem_project)
                    except Exception as e:
                        _safe_print(f"Concept code-link lookup failed: {e}")
                        continue
                    if match:
                        try:
                            if concept_db.store_code_link(
                                conn,
                                entity_id,
                                match["qualified_name"],
                                mem_project or "",
                                label=match.get("label"),
                                file_path=match.get("file_path"),
                            ):
                                code_links_created += 1
                        except Exception as e:
                            _safe_print(f"Concept code-link write failed: {e}")

            if outcomes is not None:
                # Code links are deliberately absent from this decision. The
                # graph engine is optional and its lookups already fail open,
                # so a missing link is degradation, not a reason to re-extract
                # the memory.
                if memory_failed:
                    outcomes[mem_id] = "failed"
                elif not result.entities:
                    outcomes[mem_id] = "no_entities"
                else:
                    outcomes[mem_id] = "indexed"

    return {
        "aborted": aborted,
        "memories_processed": memories_processed,
        "entities_extracted": entities_extracted,
        "relationships_created": relationships_created,
        "code_links_created": code_links_created,
        "possible_duplicates": possible_duplicates,
    }


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


def _finish_build_run(run_id: str, **fields) -> None:
    concept_db = _get_concept_db()
    with concept_db.get_connection() as conn:
        concept_db.update_build_run(conn, run_id, **fields)


def _prepare_build_schema(req: ConceptBuildRequest) -> bool:
    """Return whether a historical graph was backed up and reset."""
    global _concept_db
    db_path = get_concept_db_path()
    state = inspect_concept_schema(db_path)
    if state == "unavailable":
        raise RuntimeError("concept database unavailable")
    if state != "rebuild_required":
        return False
    if not req.search_all:
        raise ValueError("rebuild_required")

    with _concept_db_lock:
        if _concept_db is not None:
            _concept_db.close()
            _concept_db = None
        backup_and_reset_concept_database(db_path)
    return True


def _traverse(
    conn, seed_ids: list[int], depth: int, direction: str, limit: int
) -> list[dict]:
    results, _, _ = traverse_graph(
        conn,
        seed_ids,
        depth=depth,
        direction=direction,
        limit=limit,
        session_name=None,
        project=None,
        platform=None,
    )
    return results


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
    # Cross-process lock outside the in-process one, in both writers, so the
    # pair can never be taken in opposite orders. A rebuild drops the graph
    # tables, and the other transport's worker must not be writing into them.
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
        result = {
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
        result["build_run_id"] = run_id
        return result
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
        pages = _fetch_memory_pages(req.session_name, req.project, req.search_all)
        outcomes: dict[str, str] = {}
        result = await asyncio.to_thread(_run_build, pages, outcomes, abort)
    except ValueError:
        # _fetch_memory_pages raises exactly one ValueError, always this
        # static, safe-to-surface message -- return the known-good literal
        # rather than str(e), so the response never carries a live exception
        # object (CodeQL: exception-info-exposure) even if this branch is
        # ever reached by a different ValueError in the future.
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
        # HTTP-facing route body -- log server-side via structured logging
        # rather than interpolating exception text into a plain print/f-string
        # (CodeQL: exception-info-exposure). The client only ever gets the
        # generic message below.
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
        # Another process owns the graph now. The partial work stays, since
        # extraction is idempotent, but nothing here may be reported as done
        # and no queue row may be retired against it.
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
    await _retire_queued_tasks(outcomes, created_at)
    await asyncio.to_thread(
        _finish_build_run,
        run_id,
        status="success",
        memories_processed=result["memories_processed"],
        entities_extracted=result["entities_extracted"],
        relationships_created=result["relationships_created"],
        code_links_created=result["code_links_created"],
        duplicate_candidates=len(result["possible_duplicates"]),
        duration_ms=result["duration_ms"],
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    result.pop("aborted", None)
    result["graph_rebuilt"] = graph_rebuilt
    result["build_run_id"] = run_id
    return result


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
        # Leaving rows queued only costs a redundant re-extraction later.
        logger.warning("concepts.queue_retire_failed", error=str(e))


def _build_for_memory_ids_sync(
    memory_ids: list[str], abort: Optional[threading.Event] = None
) -> dict[str, str]:
    rows = _fetch_memory_rows_by_ids(memory_ids)
    outcomes: dict[str, str] = {}
    result = _run_build([rows], outcomes=outcomes, abort=abort)
    if result["aborted"]:
        # Half the batch may be unprocessed and the rest is no longer ours to
        # settle. Report nothing: every task stays queued and is retried.
        return {}
    for memory_id in memory_ids:
        outcomes.setdefault(memory_id, "vanished")
    return outcomes


async def build_for_memory_ids(
    memory_ids: list[str], abort: Optional[threading.Event] = None
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
    lock was lost. The caller must settle nothing in that case."""
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
        return await asyncio.to_thread(_build_for_memory_ids_sync, memory_ids, abort)


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
