"""Synchronous concept-build engine: fetch memory rows and extract entities,
relationships, and code links into the concept graph.

Runs entirely off the event loop via asyncio.to_thread from endpoints/concepts.py
-- the manual marm_concept_build route and the background indexing worker's
build_for_memory_ids both drive this same engine, one via a page generator over
a scope, the other via a targeted batch of memory ids.
"""

import threading
from collections.abc import Callable, Iterable, Iterator
from typing import Optional

from ..config.settings import (
    CONCEPT_BUILD_ROW_CAP,
    CONCEPT_DUPLICATE_SIMILARITY_THRESHOLD,
)
from ..core.concept_db import ConceptDB, backup_and_reset_concept_database
from ..core.concept_extraction import extract_entities
from ..core.graph_client import (
    find_code_match,
    indexed_project_names,
    is_graph_available,
)
from ..core.memory import memory
from ..core.memory_utils import _embedding_to_bytes, _safe_print

_concept_db: Optional[ConceptDB] = None
_concept_db_lock = threading.Lock()

MemoryRow = tuple[str, str, Optional[str], Optional[str], Optional[str]]
MemoryPage = list[MemoryRow]
BuildProgressCallback = Callable[[int, int, int, int], None]
_PROGRESS_UPDATE_INTERVAL = 25


def _report_progress(
    progress_callback: Optional[BuildProgressCallback],
    memories_processed: int,
    entities_extracted: int,
    relationships_created: int,
    code_links_created: int,
) -> None:
    """Report progress without turning a healthy build into an error."""
    if progress_callback is None:
        return
    try:
        progress_callback(
            memories_processed,
            entities_extracted,
            relationships_created,
            code_links_created,
        )
    except Exception as e:
        _safe_print(f"Concept build progress report failed: {e}")


def _report_progress_if_due(
    progress_callback: Optional[BuildProgressCallback],
    memories_processed: int,
    entities_extracted: int,
    relationships_created: int,
    code_links_created: int,
    last_progress_reported: int,
) -> int:
    if memories_processed - last_progress_reported < _PROGRESS_UPDATE_INTERVAL:
        return last_progress_reported
    _report_progress(
        progress_callback,
        memories_processed,
        entities_extracted,
        relationships_created,
        code_links_created,
    )
    return memories_processed


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

_MISSING_BUILD_SCOPE_MESSAGE = (
    "marm_concept_build requires session_name, project, or "
    "search_all=True to scope the build."
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


def reset_and_rebuild_concept_db(db_path: str) -> str:
    """Close the cached ConceptDB singleton and reset the on-disk database,
    atomically under the singleton's own lock so a concurrent _get_concept_db()
    call cannot reopen a connection to the file mid-reset."""
    global _concept_db
    with _concept_db_lock:
        if _concept_db is not None:
            _concept_db.close()
            _concept_db = None
        return backup_and_reset_concept_database(db_path)


def _fetch_memory_pages(
    session_name: Optional[str], project: Optional[str], search_all: bool
) -> Iterator[MemoryPage]:
    """Deterministic read from the memory DB layer directly, paged rather
    than truncated. Never goes through marm_smart_recall -- no ranking here.

    Requires at least one of session_name/project/search_all -- without this,
    an omitted session_name silently fell through to scanning every memory
    in the DB, making search_all's "explicit opt-in for everything"
    meaningless. Validated before the generator is built so the caller still
    gets the ValueError at call time, not on first iteration."""
    conditions, params = _build_scope_conditions(session_name, project, search_all)

    return _paged_memory_rows(conditions, params)


def count_memory_rows(
    session_name: Optional[str], project: Optional[str], search_all: bool
) -> int:
    """Count the immutable-at-start progress denominator for a manual build."""
    conditions, params = _build_scope_conditions(session_name, project, search_all)
    query = f"SELECT COUNT(*) FROM memories WHERE {' AND '.join(conditions)}"
    with memory.get_connection() as conn:
        row = conn.execute(query, params).fetchone()
    return int(row[0]) if row else 0


def _build_scope_conditions(
    session_name: Optional[str], project: Optional[str], search_all: bool
) -> tuple[list[str], list[str]]:
    if not (session_name or project or search_all):
        raise ValueError(_MISSING_BUILD_SCOPE_MESSAGE)

    conditions = list(_BUILD_ROW_FILTERS)
    params: list[str] = []
    if not search_all:
        if session_name:
            conditions.append("session_name = ?")
            params.append(session_name)
        if project:
            conditions.append("project = ?")
            params.append(project)
    return conditions, params


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
    finished: Optional[threading.Event] = None,
    progress_callback: Optional[BuildProgressCallback] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
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
    memories_processed = 0
    aborted = False
    cancelled = False
    entities_extracted = 0
    relationships_created = 0
    code_links_created = 0
    possible_duplicates: list[dict] = []
    # Memoized per build, not per call: get_or_create_entity only ever
    # stores the embedding on the INSERT branch (re-mentions ignore it), so
    # without this cache, a name repeated across many memories in one
    # search_all=True build re-runs the (process-wide, encoder-lock-
    # serialized) encode for a result that's thrown away every time but the
    # first. Same input text always produces the same embedding, so caching
    # is always safe.
    embed_cache: dict[str, Optional[bytes]] = {}

    try:
        # Setup belongs inside the try. _get_concept_db() opens a database and
        # runs DDL, so it can fail, and a failure that skipped the finally
        # below would leave the caller's shutdown handshake waiting out its
        # whole grace period and then reporting a build still running when
        # none is.
        concept_db = _get_concept_db()
        graph_available = is_graph_available()
        code_link_projects = indexed_project_names() if graph_available else set()
        last_progress_reported = 0
        with concept_db.get_connection() as conn:
            for page in pages:
                for row in page:
                    if abort is not None and abort.is_set():
                        aborted = True
                        break
                    if cancel_requested is not None and cancel_requested():
                        cancelled = True
                        break
                    mem_id, content, mem_session, mem_project = row[:4]
                    mem_platform = row[4] if len(row) > 4 else None
                    memories_processed += 1
                    try:
                        result = extract_entities(content)
                    except Exception as e:
                        _safe_print(
                            f"Concept extraction failed for memory {mem_id}: {e}"
                        )
                        if outcomes is not None:
                            outcomes[mem_id] = "failed"
                        last_progress_reported = _report_progress_if_due(
                            progress_callback,
                            memories_processed,
                            entities_extracted,
                            relationships_created,
                            code_links_created,
                            last_progress_reported,
                        )
                        continue

                    memory_failed = False
                    name_to_id: dict[str, int] = {}
                    name_to_canonical: dict[str, str] = {}
                    for entity in result.entities:
                        try:
                            canonical_name = concept_db.resolve_entity_name(
                                conn,
                                entity.name,
                                mem_session,
                                mem_project,
                                mem_platform,
                            )
                            if canonical_name is None:
                                continue
                            if canonical_name not in embed_cache:
                                embed_cache[canonical_name] = _try_embed(canonical_name)
                            emb_bytes = embed_cache[canonical_name]
                            entity_id, was_created = concept_db.get_or_create_entity(
                                conn,
                                canonical_name,
                                entity.type,
                                mem_session,
                                mem_project,
                                mem_id,
                                name_embedding=emb_bytes,
                                platform=mem_platform,
                            )
                        except Exception as e:
                            _safe_print(
                                f"Concept entity write failed for memory {mem_id}: {e}"
                            )
                            memory_failed = True
                            continue
                        name_to_id[entity.name] = entity_id
                        name_to_canonical[entity.name] = canonical_name
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
                                _safe_print(
                                    f"Concept duplicate-candidate scan failed: {e}"
                                )
                                candidates = []
                            if candidates:
                                possible_duplicates.append(
                                    {"entity": canonical_name, "candidates": candidates}
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

                    if mem_project in code_link_projects:
                        for entity in result.entities:
                            linked_entity_id = name_to_id.get(entity.name)
                            if linked_entity_id is None:
                                continue
                            try:
                                match = find_code_match(
                                    name_to_canonical[entity.name], mem_project
                                )
                            except Exception as e:
                                _safe_print(f"Concept code-link lookup failed: {e}")
                                continue
                            if match:
                                try:
                                    if concept_db.store_code_link(
                                        conn,
                                        linked_entity_id,
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
                    last_progress_reported = _report_progress_if_due(
                        progress_callback,
                        memories_processed,
                        entities_extracted,
                        relationships_created,
                        code_links_created,
                        last_progress_reported,
                    )
                if last_progress_reported != memories_processed:
                    _report_progress(
                        progress_callback,
                        memories_processed,
                        entities_extracted,
                        relationships_created,
                        code_links_created,
                    )
                    last_progress_reported = memories_processed
                if aborted or cancelled:
                    break

    finally:
        # However this exits, the thread has stopped writing the graph. The
        # caller cannot observe that any other way: cancelling the await
        # around asyncio.to_thread does not stop the thread.
        if finished is not None:
            finished.set()

    return {
        "aborted": aborted,
        "cancelled": cancelled,
        "memories_processed": memories_processed,
        "entities_extracted": entities_extracted,
        "relationships_created": relationships_created,
        "code_links_created": code_links_created,
        "possible_duplicates": possible_duplicates,
    }


def _build_for_memory_ids_sync(
    memory_ids: list[str],
    abort: Optional[threading.Event] = None,
    finished: Optional[threading.Event] = None,
) -> dict[str, str]:
    rows = _fetch_memory_rows_by_ids(memory_ids)
    outcomes: dict[str, str] = {}
    result = _run_build([rows], outcomes=outcomes, abort=abort, finished=finished)
    if result["aborted"]:
        # Half the batch may be unprocessed and the rest is no longer ours to
        # settle. Report nothing: every task stays queued and is retried.
        return {}
    for memory_id in memory_ids:
        outcomes.setdefault(memory_id, "vanished")
    return outcomes
