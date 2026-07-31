"""Write orchestration paths for the MARM memory system (store, merge, replace)."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Dict

from ..config.settings import (
    CONSOLIDATION_ENABLED,
    CONSOLIDATION_THRESHOLD,
    MARM_PLATFORM,
    MARM_PROJECT,
)
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


async def _update_memory(mem, memory_id: str, new_content: str) -> bool:
    """Append new_content into an existing memory and record the merge in metadata.

    Recomputes content_hash and embedding so Layer 1 dedup and semantic recall
    stay accurate after the merge. Returns False (no write happened) if the
    row was deleted or changed concurrently between the pre-read and the
    write lock -- callers must not assume the merge landed just because this
    returned without raising.
    """
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT content, metadata FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
    if row is None:
        return False
    existing_content, metadata_json = row
    original_existing_content = existing_content  # unsliced, for the re-check below
    metadata = json.loads(metadata_json) if metadata_json else {}
    _MAX = 10000
    _MARKER = "\n[merged] "
    _new_budget = _MAX - len(_MARKER)
    if len(new_content) > _new_budget:
        new_content = new_content[:_new_budget]
    _existing_budget = _MAX - len(_MARKER) - len(new_content)
    existing_content = existing_content[: max(0, _existing_budget)]
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
            # Folded into the same transaction as the content update --
            # a chunk-delete failure must not leave stale chunks that
            # disagree with the (already committed) merged content, and
            # vice versa.
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
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
    mem,
    content: str,
    session: str,
    context_type: str = "general",
    metadata: Dict = None,
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
            # existing_id's row was deleted or changed concurrently between
            # the duplicate check above and _update_memory's write-lock
            # re-verification -- the merge never happened. Fall through and
            # store sanitized_content as a new memory instead of silently
            # dropping it and reporting existing_id as if it succeeded.

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
    mem,
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
    timestamp = datetime.now(timezone.utc).isoformat()
    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
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
            (timestamp, memory_id),
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
    mem,
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
    a routine resave never needs to touch docs.memory_id); otherwise a
    fresh row is created with a new id -- this also doubles as the repair
    path for a doc whose prior mirror was deleted out from under it (e.g.
    via a direct Console memory delete).
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
        conn.execute("BEGIN IMMEDIATE")
        try:
            replaced = False
            if existing_memory_id:
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
                        existing_memory_id,
                    ),
                )
                replaced = cursor.rowcount > 0

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
