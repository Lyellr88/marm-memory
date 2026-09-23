import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict

import structlog

from ..config.settings import (
    CONSOLIDATION_ENABLED,
    CONSOLIDATION_THRESHOLD,
    MARM_PLATFORM,
    MARM_PROJECT,
)
from .concept_queue import enqueue as enqueue_concept_index
from .consolidation import (
    compute_content_hash,
    find_exact_duplicate,
    find_semantic_duplicate,
    normalize_content,
)
from .memory_utils import (
    DOC_CHUNK_OVERLAP_WORDS,
    DOC_CHUNK_TARGET_WORDS,
    DOC_CHUNK_THRESHOLD_WORDS,
    MEMORY_CHUNK_OVERLAP_WORDS,
    MEMORY_CHUNK_TARGET_WORDS,
    MEMORY_CHUNK_THRESHOLD_WORDS,
    _chunk_text,
    _embedding_to_bytes,
    _safe_print,
    _spawn_chunk_write,
    sanitize_content,
)

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from .memory import MARMMemory


async def _update_memory(mem: "MARMMemory", memory_id: str, new_content: str) -> bool:
    """Append new_content into an existing memory and record the merge in metadata.

    Recomputes content_hash and embedding so Layer 1 dedup and semantic recall
    stay accurate after the merge. Returns False (no write happened) if the
    row was deleted or changed concurrently between the pre-read and the
    write lock, or if the merge would not fit -- callers must not assume the
    merge landed just because this returned without raising. The caller then
    stores the memory separately, which is the point: consolidation exists to
    avoid a duplicate row, never to destroy text.
    """
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT content, metadata FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
    if row is None:
        return False
    existing_content, metadata_json = row
    original_existing_content = existing_content
    metadata = json.loads(metadata_json) if metadata_json else {}
    _MAX = 10000
    _MARKER = "\n[merged] "
    # Refuse a merge that does not fit rather than truncating to make it fit.
    #
    # This used to give `new_content` the budget first and cut `existing_content`
    # down to whatever was left, so each merge could evict bodies merged
    # earlier -- a record would sit at exactly _MAX and silently hold only its
    # head and the most recent arrivals. Nothing reported the loss: the
    # merge_history kept growing while the text it pointed at was gone, and a
    # later query returned a neighbouring memory's body as if it were the
    # answer.
    #
    # Returning False is already the "no write happened" contract, and the
    # caller's fallback is to store the memory as its own row. Two rows the
    # scorer can tell apart beat one row with half the evidence missing.
    if len(existing_content) + len(_MARKER) + len(new_content) > _MAX:
        # Logged, because a silent refusal has the same shape as the silent
        # truncation it replaces: both end with the caller believing
        # consolidation did something reasonable. `merge_refused_oversize`
        # separates "not similar enough to merge" from "similar, but
        # preserving the evidence needed its own row" in an audit.
        logger.info(
            "consolidation.merge_refused_oversize",
            memory_id=memory_id,
            existing_chars=len(existing_content),
            incoming_chars=len(new_content),
            limit=_MAX,
        )
        return False
    merged_content = f"{existing_content}{_MARKER}{new_content}"
    merged_at = datetime.now(timezone.utc).isoformat()
    if "merge_history" not in metadata:
        metadata["merge_history"] = []
    metadata["merge_history"].append(
        {
            "merged_at": merged_at,
            "content_preview": new_content[:100],
        }
    )

    merged_hash = compute_content_hash(merged_content)

    merged_embedding_bytes = None
    encoder_ok = merged_content.strip() and mem._load_encoder_lazily()
    if encoder_ok:
        try:
            merged_vec = await asyncio.to_thread(mem._encode_sync, merged_content)
            merged_embedding_bytes = _embedding_to_bytes(merged_vec)
        except Exception as e:
            _safe_print(f"Failed to regenerate embedding after merge: {e}")

    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute(
                "SELECT content, metadata FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if (
                current is None
                or current[0] != original_existing_content
                or current[1] != metadata_json
            ):
                conn.execute("ROLLBACK")
                return False

            if merged_embedding_bytes is not None:
                conn.execute(
                    "UPDATE memories SET content = ?, metadata = ?, content_hash = ?, embedding = ?, timestamp = ? WHERE id = ?",
                    (
                        merged_content,
                        json.dumps(metadata),
                        merged_hash,
                        merged_embedding_bytes,
                        merged_at,
                        memory_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE memories SET content = ?, metadata = ?, content_hash = ?, embedding = NULL, timestamp = ? WHERE id = ?",
                    (
                        merged_content,
                        json.dumps(metadata),
                        merged_hash,
                        merged_at,
                        memory_id,
                    ),
                )
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
            enqueue_concept_index(conn, memory_id, merged_hash)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    chunks = _chunk_text(
        merged_content,
        threshold=MEMORY_CHUNK_THRESHOLD_WORDS,
        target_size=MEMORY_CHUNK_TARGET_WORDS,
        overlap=MEMORY_CHUNK_OVERLAP_WORDS,
    )
    if chunks and mem._load_encoder_lazily():
        _spawn_chunk_write(mem, memory_id, chunks, merged_hash)
    return True


async def _store_memory(
    mem: "MARMMemory",
    content: str,
    session: str,
    context_type: str = "general",
    metadata: Dict | None = None,
    project: str | None = None,
    platform: str | None = None,
    explicit_scope: bool = False,
) -> str:
    """Store content with vector embedding for semantic search"""
    sanitized_content = sanitize_content(content)

    if context_type == "general":
        context_type = await mem.auto_classify_content(sanitized_content)

    content_hash = compute_content_hash(sanitized_content)
    normalized_content = normalize_content(sanitized_content)
    scoped_project = project if explicit_scope else MARM_PROJECT or None
    scoped_platform = platform if explicit_scope else MARM_PLATFORM or None

    if CONSOLIDATION_ENABLED:
        with mem.get_connection() as conn:
            if explicit_scope:
                existing_id = find_exact_duplicate(
                    conn,
                    content_hash,
                    session,
                    normalized_content,
                    scoped_project,
                    scoped_platform,
                )
            else:
                existing_id = find_exact_duplicate(
                    conn, content_hash, session, normalized_content
                )
            if existing_id:
                return existing_id

    pre_embedding = None
    pre_embedding_bytes = None
    if sanitized_content.strip() and mem._load_encoder_lazily():
        try:
            pre_embedding = await asyncio.to_thread(mem._encode_sync, sanitized_content)
            pre_embedding_bytes = _embedding_to_bytes(pre_embedding)
        except Exception as e:
            _safe_print(f"Failed to generate embedding: {e}")

    if CONSOLIDATION_ENABLED:
        if explicit_scope:
            existing_id = await find_semantic_duplicate(
                mem,
                sanitized_content,
                session,
                CONSOLIDATION_THRESHOLD,
                query_vec=pre_embedding,
                project=scoped_project,
                platform=scoped_platform,
            )
        else:
            existing_id = await find_semantic_duplicate(
                mem,
                sanitized_content,
                session,
                CONSOLIDATION_THRESHOLD,
                query_vec=pre_embedding,
            )
        if existing_id:
            merged = await _update_memory(mem, existing_id, sanitized_content)
            if merged:
                mem._on_memory_written(session)
                return existing_id

    memory_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    metadata = metadata or {}

    embedding_bytes = pre_embedding_bytes

    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if CONSOLIDATION_ENABLED:
            if explicit_scope:
                under_lock_id = find_exact_duplicate(
                    conn,
                    content_hash,
                    session,
                    normalized_content,
                    scoped_project,
                    scoped_platform,
                )
            else:
                under_lock_id = find_exact_duplicate(
                    conn, content_hash, session, normalized_content
                )
            if under_lock_id:
                conn.execute("ROLLBACK")
                return under_lock_id

        conn.execute(
            """
            INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata, project, platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                memory_id,
                session,
                sanitized_content,
                embedding_bytes,
                content_hash,
                timestamp,
                context_type,
                json.dumps(metadata),
                scoped_project,
                scoped_platform,
            ),
        )

        enqueue_concept_index(conn, memory_id, content_hash)

        conn.execute(
            """
            INSERT INTO sessions (session_name, last_accessed)
            VALUES (?, ?)
            ON CONFLICT(session_name) DO UPDATE SET last_accessed = excluded.last_accessed
        """,
            (session, timestamp),
        )

    mem._on_memory_written(session)

    chunks = _chunk_text(
        sanitized_content,
        threshold=MEMORY_CHUNK_THRESHOLD_WORDS,
        target_size=MEMORY_CHUNK_TARGET_WORDS,
        overlap=MEMORY_CHUNK_OVERLAP_WORDS,
    )
    if chunks and mem._load_encoder_lazily():
        _spawn_chunk_write(mem, memory_id, chunks, content_hash)

    return memory_id


async def _replace_memory(
    mem: "MARMMemory",
    memory_id: str,
    content: str,
    session: str,
    context_type: str,
    metadata: Dict,
    project: str | None,
    platform: str | None,
) -> bool:
    sanitized_content = sanitize_content(content)
    content_hash = compute_content_hash(sanitized_content)
    embedding = None
    if sanitized_content.strip() and mem._load_encoder_lazily():
        try:
            embedding = _embedding_to_bytes(
                await asyncio.to_thread(mem._encode_sync, sanitized_content)
            )
        except Exception as exc:
            _safe_print(f"Failed to generate replacement embedding: {exc}")
    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # `timestamp` is WHEN THE MEMORY IS FROM, not when the row was last
        # written -- `created_at` already records the insert. Every consumer
        # reads it that way: compaction's age gate selects `timestamp < cutoff`,
        # and recall's fallback scan takes `ORDER BY timestamp DESC LIMIT ?`.
        #
        # Stamping `now` on every replace therefore made an edit look like a new
        # memory: it reset the compaction age gate by a full
        # COMPACTION_MIN_AGE_HOURS, and moved the memory to the front of the
        # recall scan window, displacing something genuinely recent out of it.
        # For a metadata-only change -- re-scoping a project, correcting a
        # session -- the content is not even different.
        #
        # So it moves only when the CONTENT moves, which is the one case where
        # "this says something new as of now" is true, and which is also what
        # keeps compaction's per-session fingerprint (count + newest eligible
        # timestamp) changing so an edited session is re-scanned.
        #
        # `content_hash` was added to `memories` by ALTER TABLE with no
        # backfill, so any row written before that migration carries NULL.
        # The stored content is the authority and the column is a cache of
        # it, so hash the content when the column holds nothing -- otherwise
        # an upgraded database restamps every pre-migration memory and keeps
        # the defect this fixes.
        previous = conn.execute(
            "SELECT content_hash, content, timestamp FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if previous is None:
            conn.execute("ROLLBACK")
            return False
        previous_hash, previous_content, previous_timestamp = previous
        if previous_hash is None:
            previous_hash = compute_content_hash(previous_content or "")
        # `written_at` is when THIS write happened, and the rows below are
        # about the write rather than about the memory: a staging row going
        # stale, and a session being touched. Only `memories.timestamp` may
        # be historical -- reusing it for those would backdate them, and
        # `last_accessed` in particular decides which session is current
        # (`memory.py`: ORDER BY last_accessed DESC LIMIT 1) and orders the
        # Console's session list.
        written_at = datetime.now(timezone.utc).isoformat()
        timestamp = previous_timestamp if previous_hash == content_hash else written_at
        cursor = conn.execute(
            """UPDATE memories SET content = ?, session_name = ?, context_type = ?, metadata = ?,
               project = ?, platform = ?, content_hash = ?, embedding = ?, timestamp = ? WHERE id = ?""",
            (
                sanitized_content,
                session,
                context_type,
                json.dumps(metadata or {}),
                project,
                platform,
                content_hash,
                embedding,
                timestamp,
                memory_id,
            ),
        )
        if not cursor.rowcount:
            conn.execute("ROLLBACK")
            return False
        conn.execute(
            """
            UPDATE compaction_staging
            SET status = 'stale', updated_at = ?
            WHERE status != 'applied'
              AND EXISTS (
                  SELECT 1 FROM json_each(compaction_staging.source_memory_ids)
                  WHERE value = ?
              )
            """,
            (written_at, memory_id),
        )
        conn.execute(
            """
            INSERT INTO sessions (session_name, last_accessed)
            VALUES (?, ?)
            ON CONFLICT(session_name) DO UPDATE SET last_accessed = excluded.last_accessed
            """,
            (session, written_at),
        )
        conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
        enqueue_concept_index(conn, memory_id, content_hash)
    chunks = _chunk_text(
        sanitized_content,
        threshold=MEMORY_CHUNK_THRESHOLD_WORDS,
        target_size=MEMORY_CHUNK_TARGET_WORDS,
        overlap=MEMORY_CHUNK_OVERLAP_WORDS,
    )
    if chunks and mem._load_encoder_lazily():
        _spawn_chunk_write(mem, memory_id, chunks, content_hash)
    mem._on_memory_written(session)
    return True


async def _store_doc_mirror(
    mem: "MARMMemory",
    content: str,
    session: str,
    project: str | None,
    platform: str | None,
    metadata: Dict,
    existing_memory_id: str | None = None,
) -> str:
    """Create or replace a stable, non-consolidating mirror row for a
    promoted doc (services/notebook.py's action='save').

    Bypasses consolidation entirely -- a doc's own dedup/versioning
    already lives in docs_db.save_doc, so an exact/semantic duplicate
    check here would be redundant and could accidentally merge a doc's
    mirror into an unrelated memory. Uses the doc chunk profile instead
    of the memory profile. If existing_memory_id is provided and its row
    still exists, the row is replaced in place (keeps its id stable, so
    a routine resave never needs to touch docs.memory_id). Without a usable
    id, or with one that no longer resolves, the doc's existing mirror is
    resolved by metadata.doc_id, so the write is idempotent per doc even when
    the caller lost the id. Only when neither locates a row is a fresh one
    created with a new id -- that is the repair path for a doc whose prior
    mirror was deleted out from under it (e.g. via a direct Console delete).
    """
    sanitized_content = sanitize_content(content)
    content_hash = compute_content_hash(sanitized_content)

    embedding_bytes = None
    if sanitized_content.strip() and mem._load_encoder_lazily():
        try:
            vec = await asyncio.to_thread(mem._encode_sync, sanitized_content)
            embedding_bytes = _embedding_to_bytes(vec)
        except Exception as e:
            _safe_print(f"Failed to generate doc mirror embedding: {e}")

    timestamp = datetime.now(timezone.utc).isoformat()

    with mem.get_connection() as conn:

        def _replace_in_place(row_id: str) -> bool:
            cursor = conn.execute(
                """
                UPDATE memories SET content = ?, session_name = ?, embedding = ?,
                   content_hash = ?, timestamp = ?, context_type = 'doc',
                   metadata = ?, project = ?, platform = ?
                WHERE id = ?
                """,
                (
                    sanitized_content,
                    session,
                    embedding_bytes,
                    content_hash,
                    timestamp,
                    json.dumps(metadata),
                    project,
                    platform,
                    row_id,
                ),
            )
            return cursor.rowcount > 0

        conn.execute("BEGIN IMMEDIATE")
        try:
            replaced = False
            if existing_memory_id:
                replaced = _replace_in_place(existing_memory_id)

            if not replaced and metadata.get("doc_id") is not None:
                orphan = conn.execute(
                    """
                    SELECT id FROM memories
                    WHERE context_type = 'doc'
                      AND json_extract(metadata, '$.doc_id') = ?
                    ORDER BY id LIMIT 1
                    """,
                    (metadata["doc_id"],),
                ).fetchone()
                if orphan is not None:
                    existing_memory_id = orphan[0]
                    replaced = _replace_in_place(orphan[0])

            if replaced:
                assert existing_memory_id is not None
                memory_id = existing_memory_id
                conn.execute(
                    """
                    UPDATE compaction_staging
                    SET status = 'stale', updated_at = ?
                    WHERE status != 'applied'
                      AND EXISTS (
                          SELECT 1 FROM json_each(compaction_staging.source_memory_ids)
                          WHERE value = ?
                      )
                    """,
                    (timestamp, memory_id),
                )
            else:
                memory_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO memories
                        (id, session_name, content, embedding, content_hash, timestamp,
                         context_type, metadata, project, platform)
                    VALUES (?, ?, ?, ?, ?, ?, 'doc', ?, ?, ?)
                    """,
                    (
                        memory_id,
                        session,
                        sanitized_content,
                        embedding_bytes,
                        content_hash,
                        timestamp,
                        json.dumps(metadata),
                        project,
                        platform,
                    ),
                )

            conn.execute(
                """
                INSERT INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
                ON CONFLICT(session_name) DO UPDATE SET last_accessed = excluded.last_accessed
                """,
                (session, timestamp),
            )
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
            enqueue_concept_index(conn, memory_id, content_hash)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    chunks = _chunk_text(
        sanitized_content,
        threshold=DOC_CHUNK_THRESHOLD_WORDS,
        target_size=DOC_CHUNK_TARGET_WORDS,
        overlap=DOC_CHUNK_OVERLAP_WORDS,
    )
    if chunks and mem._load_encoder_lazily():
        _spawn_chunk_write(mem, memory_id, chunks, content_hash)

    mem._on_memory_written(session)
    return memory_id
