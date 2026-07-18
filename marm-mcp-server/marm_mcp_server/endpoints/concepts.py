"""Concept graph endpoints — marm_concept_build, marm_concept_recall.

Orchestration layer: build reads memory rows directly (never through
marm_smart_recall's ranked/limited recall path — see marm-index-spec.md's
"Build reads the memory DB layer directly" section), runs spaCy extraction,
writes to the concept graph's own SQLite file, and soft-links against
marm-graph. Recall reads the concept graph tables and infers lookup vs
related-to intent from query shape.
"""

import asyncio
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter

from ..config.settings import (
    CONCEPT_BUILD_ROW_CAP,
    CONCEPTS_AVAILABLE,
    CONCEPT_DUPLICATE_SIMILARITY_THRESHOLD,
)
from ..core.concept_db import ConceptDB
from ..core.concept_extraction import extract_entities
from ..core.graph_client import find_code_match, is_graph_available
from ..core.memory import memory
from ..core.memory_utils import _embedding_to_bytes, _safe_print
from ..core.models import ConceptBuildRequest, ConceptRecallRequest

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="", tags=["Concepts"])

_RELATED_PREFIXES = (
    "related to ",
    "related-to ",
    "relationships of ",
    "connected to ",
    "connections of ",
)

_concept_db: Optional[ConceptDB] = None
_concept_db_lock = threading.Lock()


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
    "Concept extraction is unavailable. Install: "
    "pip install marm-mcp-server[concepts] && python -m spacy download en_core_web_sm"
)


def _fetch_memory_rows(
    session_name: Optional[str], project: Optional[str], search_all: bool
) -> list[tuple[str, str, Optional[str], Optional[str]]]:
    """Deterministic row-bounded read from the memory DB layer directly.
    Never goes through marm_smart_recall — no ranking/truncation here.

    Requires at least one of session_name/project/search_all -- without this,
    an omitted session_name silently fell through to scanning every memory
    in the DB (up to the row cap), making search_all's "explicit opt-in for
    everything" meaningless."""
    if not (session_name or project or search_all):
        raise ValueError(_MISSING_BUILD_SCOPE_MESSAGE)

    conditions = [
        "session_name != 'marm_system'",
        "content IS NOT NULL",
        "content != ''",
        "(compaction_role IS NULL OR compaction_role != 'source')",
    ]
    params: list = []

    if not search_all:
        if session_name:
            conditions.append("session_name = ?")
            params.append(session_name)
        if project:
            conditions.append("project = ?")
            params.append(project)

    query = (
        f"SELECT id, content, session_name, project FROM memories "
        f"WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ?"
    )
    params.append(CONCEPT_BUILD_ROW_CAP)

    with memory.get_connection() as conn:
        return conn.execute(query, params).fetchall()


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


def _run_build(rows: list[tuple[str, str, Optional[str], Optional[str]]]) -> dict:
    concept_db = _get_concept_db()
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
        for mem_id, content, mem_session, mem_project in rows:
            try:
                result = extract_entities(content)
            except Exception as e:
                _safe_print(f"Concept extraction failed for memory {mem_id}: {e}")
                continue

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
                    )
                except Exception as e:
                    _safe_print(f"Concept entity write failed for memory {mem_id}: {e}")
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
                        conn, id_a, id_b, predicate, mem_id, mem_project
                    ):
                        relationships_created += 1
                except Exception as e:
                    _safe_print(
                        f"Concept relationship write failed for memory {mem_id}: {e}"
                    )

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

    return {
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


def _traverse(
    conn, seed_ids: list[int], depth: int, direction: str, limit: int
) -> list[dict]:
    """Bounded BFS over entities/relationships -- single connection, one
    batched SQL query per hop-level, matches this codebase's established
    IN (...)-in-a-Python-loop convention (compaction.py, memory_delete.py; zero
    WITH RECURSIVE uses anywhere in this repo). At depth=1 this reproduces
    the original one-hop outgoing+incoming+union+truncate behavior exactly.

    Two separate sets, not one -- an earlier version pre-seeded a single
    `visited` set with every seed id, which silently suppressed direct edges
    *between* two seeds (recall's `name LIKE '%query%'` routinely matches a
    cluster of related entities that are themselves directly connected --
    those edges are exactly the most relevant ones to surface). `emitted`
    tracks what's already in `results` and is NOT pre-seeded, so a seed can
    be emitted as another seed's hop-1 neighbor. `expanded` IS pre-seeded
    with every seed id and prevents re-querying from a node whose
    relationships we've already fetched -- this is what stops multi-node
    cycles (A->B->C->A) from looping/duplicate-exploding. The `hop > 1`
    guard is the key: at hop 1, `expanded` never blocks emission (frontier
    *is* the seed set, so every hop-1 row is by definition a direct edge
    between two seeds or a seed and a fresh neighbor); from hop 2 onward,
    re-reaching anything already in `expanded` (including an original seed
    via a cycle) is genuinely old information, not a new discovery, and is
    excluded. ORDER BY r.id makes which parent "wins" for path
    reconstruction deterministic when a node is reachable from two frontier
    members in the same hop."""
    emitted: set[int] = set()
    expanded: set[int] = set(seed_ids)
    paths: dict[int, list[dict]] = {eid: [] for eid in seed_ids}
    frontier = list(seed_ids)
    results: list[dict] = []

    for hop in range(1, depth + 1):
        if not frontier or len(results) >= limit:
            break
        placeholders = ",".join("?" * len(frontier))
        rows = []
        if direction in ("outgoing", "both"):
            rows += conn.execute(
                f"""SELECT r.source_id, e.id, e.name, e.type, r.predicate FROM relationships r
                    JOIN entities e ON e.id = r.target_id
                    WHERE r.source_id IN ({placeholders}) ORDER BY r.id""",
                frontier,
            ).fetchall()
        if direction in ("incoming", "both"):
            rows += conn.execute(
                f"""SELECT r.target_id, e.id, e.name, e.type, r.predicate FROM relationships r
                    JOIN entities e ON e.id = r.source_id
                    WHERE r.target_id IN ({placeholders}) ORDER BY r.id""",
                frontier,
            ).fetchall()

        next_frontier = []
        for from_id, neighbor_id, name, entity_type, predicate in rows:
            if neighbor_id in emitted:
                continue
            if hop > 1 and neighbor_id in expanded:
                continue
            emitted.add(neighbor_id)
            paths[neighbor_id] = paths[from_id] + [
                {"predicate": predicate, "name": name}
            ]
            entry = {
                "name": name,
                "type": entity_type,
                "predicate": predicate,
                "hop": hop,
            }
            if depth > 1:
                entry["path"] = paths[neighbor_id]
            results.append(entry)
            if neighbor_id not in expanded:
                expanded.add(neighbor_id)
                next_frontier.append(neighbor_id)
            if len(results) >= limit:
                break
        frontier = next_frontier

    return results


def _run_recall(
    query: str,
    session_name: Optional[str],
    limit: int,
    depth: int = 1,
    direction: str = "both",
    project: Optional[str] = None,
) -> dict:
    concept_db = _get_concept_db()

    target_name = query
    for prefix in _RELATED_PREFIXES:
        if query.lower().startswith(prefix):
            target_name = query[len(prefix) :].strip()
            break

    entities: list[dict] = []
    related_entities: list[dict] = []
    linked_code: list[dict] = []

    with concept_db.get_connection() as conn:
        conditions = ["name LIKE ?"]
        params: list = [f"%{target_name}%"]
        if session_name:
            conditions.append("session_name = ?")
            params.append(session_name)
        if project:
            conditions.append("project = ?")
            params.append(project)

        rows = conn.execute(
            f"SELECT id, name, type, source_memory_ids FROM entities "
            f"WHERE {' AND '.join(conditions)} LIMIT ?",
            [*params, limit],
        ).fetchall()

        entity_ids = []
        for entity_id, name, entity_type, source_ids_json in rows:
            try:
                mention_count = len(json.loads(source_ids_json))
            except (TypeError, ValueError):
                mention_count = 0
            entities.append(
                {"name": name, "type": entity_type, "mention_count": mention_count}
            )
            entity_ids.append(entity_id)

        if entity_ids:
            placeholders = ",".join("?" * len(entity_ids))

            related_entities = _traverse(conn, entity_ids, depth, direction, limit)

            code_rows = conn.execute(
                f"""SELECT graph_qualified_name, label, file_path FROM entity_code_links
                    WHERE entity_id IN ({placeholders}) LIMIT ?""",
                [*entity_ids, limit],
            ).fetchall()
            for qualified_name, label, file_path in code_rows:
                linked_code.append(
                    {
                        "qualified_name": qualified_name,
                        "label": label,
                        "file_path": file_path,
                    }
                )

    return {
        "entities": entities,
        "related_entities": related_entities,
        "linked_code": linked_code,
    }


@router.post("/marm_concept_build", operation_id="marm_concept_build")
async def marm_concept_build(req: ConceptBuildRequest) -> dict:
    """🕸️ Extract entities/relationships from memory content into the concept graph.

    Scope with session_name or project for a targeted build, or pass
    search_all=True for everything (row-capped). Links extracted entities to
    marm-graph code symbols when available. Call this before marm_concept_recall
    — there's no data until a build has run at least once.
    """
    if not (req.session_name or req.project or req.search_all):
        return {"status": "error", "message": _MISSING_BUILD_SCOPE_MESSAGE}

    run_id = req.run_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        await asyncio.to_thread(_create_build_run, req, run_id, created_at)
    except Exception as e:
        logger.warning("concepts.build_run_create_error", error=str(e))
        return {"status": "error", "message": "Concept build failed."}

    if not CONCEPTS_AVAILABLE:
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

    start = time.monotonic()
    try:
        await asyncio.to_thread(
            _finish_build_run,
            run_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        rows = await asyncio.to_thread(
            _fetch_memory_rows, req.session_name, req.project, req.search_all
        )
        result = await asyncio.to_thread(_run_build, rows)
    except ValueError:
        # _fetch_memory_rows raises exactly one ValueError, always this
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
    await asyncio.to_thread(
        _finish_build_run,
        run_id,
        status="success",
        memories_processed=len(rows),
        entities_extracted=result["entities_extracted"],
        relationships_created=result["relationships_created"],
        code_links_created=result["code_links_created"],
        duplicate_candidates=len(result["possible_duplicates"]),
        duration_ms=result["duration_ms"],
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    result["build_run_id"] = run_id
    return result


@router.post("/marm_concept_recall", operation_id="marm_concept_recall")
async def marm_concept_recall(req: ConceptRecallRequest) -> dict:
    """🔎 Search the concept graph: entities, their relationships, and linked code.

    Query as a bare concept name for a lookup, or phrase it as "related to X"
    to emphasize traversal — both route from query shape alone. Pass depth
    to traverse multiple hops (default 1 = direct neighbors only), direction
    to scope traversal (outgoing/incoming/both), project to scope to one
    project (entities with the same name in different projects are distinct
    nodes -- omit to search across all). Returns empty lists (not an error)
    when marm_concept_build hasn't run yet or marm-graph has no matching
    code symbols.
    """
    try:
        return await asyncio.to_thread(
            _run_recall,
            req.query,
            req.session_name,
            req.limit,
            req.depth,
            req.direction,
            req.project,
        )
    except Exception as e:
        logger.warning("concepts.recall_error", error=str(e))
        return {"status": "error", "message": "Concept recall failed."}
