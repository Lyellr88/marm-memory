"""Write and recall orchestration paths for the MARM memory system."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List

from ..config.settings import (
    CONSOLIDATION_ENABLED,
    CONSOLIDATION_THRESHOLD,
    RECALL_SCAN_LIMIT,
    TEMPORAL_WEIGHT,
    TEMPORAL_HALF_LIFE_DAYS,
    FTS_CANDIDATE_LIMIT,
    MARM_PROJECT,
    MARM_PLATFORM,
)
from .memory_utils import (
    _safe_print,
    _recall_debug,
    _chunk_text,
    _embedding_to_bytes,
    _write_chunks,
    sanitize_content,
    _temporal_score,
    _safe_fts_query,
    _is_exact_query,
)
from .memory_scoring import (
    _fetch_fts_candidate_ids,
    _fetch_and_score_by_ids,
    _fetch_and_score_embedding_rows,
    _fetch_and_score_fts_rows,
)
from .consolidation import (
    compute_content_hash,
    find_exact_duplicate,
    find_semantic_duplicate,
    normalize_content,
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

    chunks = _chunk_text(merged_content)
    if chunks and mem._load_encoder_lazily():
        _chunk_task = asyncio.create_task(  # noqa: RUF006
            _write_chunks(mem, mem.db_path, memory_id, chunks, merged_hash)
        )
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

    chunks = _chunk_text(sanitized_content)
    if chunks and mem._load_encoder_lazily():
        _chunk_task = asyncio.create_task(  # noqa: RUF006
            _write_chunks(mem, mem.db_path, memory_id, chunks, content_hash)
        )

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
    chunks = _chunk_text(sanitized_content)
    if chunks and mem._load_encoder_lazily():
        _chunk_task = asyncio.create_task(  # noqa: RUF006
            _write_chunks(mem, mem.db_path, memory_id, chunks, content_hash)
        )
    mem._on_memory_written(session)
    return True


async def _delete_memory(mem, memory_id: str) -> bool:
    result = await _delete_memories(mem, [memory_id])
    return bool(result["deleted_ids"])


def _delete_impact(conn, memory_id: str) -> dict:
    row = conn.execute(
        "SELECT id, compaction_role, compacted_into, metadata FROM memories WHERE id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        return {"memory_id": memory_id, "exists": False}

    metadata = json.loads(row[3]) if row[3] else {}
    staging_rows = conn.execute(
        """
        SELECT id, status FROM compaction_staging
        WHERE EXISTS (
            SELECT 1 FROM json_each(compaction_staging.source_memory_ids)
            WHERE value = ?
        )
        """,
        (memory_id,),
    ).fetchall()
    return {
        "memory_id": row[0],
        "exists": True,
        "compaction_role": row[1] or "none",
        "compacted_into": row[2],
        "summary_source_ids": metadata.get("source_memory_ids", []),
        "staging_candidates": [
            {"id": candidate_id, "status": status}
            for candidate_id, status in staging_rows
        ],
    }


def _remove_deleted_sources_from_summary(
    conn, summary_id: str, deleted_source_ids: set[str], now: str
) -> int:
    row = conn.execute(
        "SELECT metadata FROM memories WHERE id = ? AND compaction_role = 'summary'",
        (summary_id,),
    ).fetchone()
    if row is None:
        return 0
    metadata = json.loads(row[0]) if row[0] else {}
    source_ids = [str(item) for item in metadata.get("source_memory_ids", [])]
    remaining = [item for item in source_ids if item not in deleted_source_ids]
    if remaining == source_ids:
        return 0
    deleted_seen = set(
        str(item) for item in metadata.get("deleted_source_memory_ids", [])
    )
    deleted_seen.update(item for item in source_ids if item in deleted_source_ids)
    metadata["source_memory_ids"] = remaining
    metadata["source_count"] = len(remaining)
    metadata["deleted_source_memory_ids"] = sorted(deleted_seen)
    metadata["updated_at"] = now
    conn.execute(
        "UPDATE memories SET metadata = ? WHERE id = ?",
        (json.dumps(metadata), summary_id),
    )
    return 1


def _restore_sources_from_deleted_summary(
    conn, summary_id: str, deleted_ids: set[str], now: str
) -> int:
    rows = conn.execute(
        "SELECT id, metadata FROM memories WHERE compacted_into = ?",
        (summary_id,),
    ).fetchall()
    restored = 0
    for source_id, metadata_json in rows:
        if source_id in deleted_ids:
            continue
        metadata = json.loads(metadata_json) if metadata_json else {}
        metadata.pop("compaction_role", None)
        metadata.pop("compacted_into", None)
        metadata["restored_from_deleted_summary"] = summary_id
        metadata["restored_at"] = now
        conn.execute(
            "UPDATE memories SET compaction_role = NULL, compacted_into = NULL, metadata = ? WHERE id = ?",
            (json.dumps(metadata), source_id),
        )
        restored += 1
    return restored


async def _delete_memories(mem, memory_ids: list[str]) -> dict:
    unique_ids = list(dict.fromkeys(str(memory_id) for memory_id in memory_ids))
    if not unique_ids:
        return {
            "deleted_ids": [],
            "missing_ids": [],
            "impacts": [],
            "compaction_updates": {
                "staging_candidates_marked_stale": 0,
                "summaries_updated": 0,
                "sources_restored": 0,
            },
        }

    now = datetime.now(timezone.utc).isoformat()
    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        impacts = [_delete_impact(conn, memory_id) for memory_id in unique_ids]
        existing_ids = {
            str(item["memory_id"]) for item in impacts if item.get("exists")
        }
        missing_ids = [
            memory_id for memory_id in unique_ids if memory_id not in existing_ids
        ]
        if not existing_ids:
            return {
                "deleted_ids": [],
                "missing_ids": missing_ids,
                "impacts": impacts,
                "compaction_updates": {
                    "staging_candidates_marked_stale": 0,
                    "summaries_updated": 0,
                    "sources_restored": 0,
                },
            }

        source_summary_ids = {
            item.get("compacted_into")
            for item in impacts
            if item.get("exists")
            and item.get("compaction_role") == "source"
            and item.get("compacted_into")
            and item.get("compacted_into") not in existing_ids
        }
        summaries_updated = sum(
            _remove_deleted_sources_from_summary(conn, summary_id, existing_ids, now)
            for summary_id in source_summary_ids
        )

        deleted_summary_ids = [
            item["memory_id"]
            for item in impacts
            if item.get("exists") and item.get("compaction_role") == "summary"
        ]
        sources_restored = sum(
            _restore_sources_from_deleted_summary(conn, summary_id, existing_ids, now)
            for summary_id in deleted_summary_ids
        )

        placeholders = ",".join("?" for _ in existing_ids)
        stale_cursor = conn.execute(
            f"""
            UPDATE compaction_staging
            SET status = 'stale', updated_at = ?
            WHERE status != 'applied'
              AND EXISTS (
                  SELECT 1 FROM json_each(compaction_staging.source_memory_ids)
                  WHERE value IN ({placeholders})
              )
            """,
            [now, *existing_ids],
        )
        for memory_id in existing_ids:
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
        delete_cursor = conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            list(existing_ids),
        )

    return {
        "deleted_ids": sorted(existing_ids),
        "missing_ids": missing_ids,
        "impacts": impacts,
        "compaction_updates": {
            "staging_candidates_marked_stale": stale_cursor.rowcount,
            "summaries_updated": summaries_updated,
            "sources_restored": sources_restored,
        },
        "deleted_count": delete_cursor.rowcount,
    }


async def _recall_exact(
    mem,
    query,
    session=None,
    limit=5,
    project=None,
    platform=None,
) -> List[Dict]:
    """Deterministic exact/lexical recall via FTS5 BM25, with LIKE fallback.

    Unlike _recall_similar, this path never re-ranks by semantic similarity.
    Exact lexical hits are always returned in BM25 order, making it safe for
    config keys, API names, command strings, file paths, and short code snippets
    where a semantically-close-but-wrong result would be worse than no result.

    Fallback chain:
      1. FTS5 BM25 — fast, ranked, handles tokenisable queries.
      2. LIKE scan  — used when FTS5 returns no results or the query cannot
                      be sanitised into valid FTS tokens (e.g. bare operators).
      3. Empty list — returned when both paths yield nothing; callers must
                      never receive a semantic result on the exact lane.

    Each result carries ``retrieval_mode`` set to ``"exact_fts"`` or
    ``"exact_like"`` so callers and tests can confirm which path was taken.
    """
    _recall_debug(f"exact path: query='{query[:60]}', session={session}")

    # --- attempt FTS5 first ---
    fts_results = await _recall_text_search(
        mem,
        query,
        session,
        limit,
        project=project,
        platform=platform,
    )

    if fts_results:
        for r in fts_results:
            r.setdefault("retrieval_mode", "exact_fts")
        _recall_debug(f"exact_fts: {len(fts_results)} results")
        return fts_results

    # --- FTS returned nothing: fall back to LIKE scan ---
    _recall_debug("exact_fts returned 0 results → LIKE fallback")
    try:
        with mem.get_connection() as conn:
            base = """
                SELECT
                    id,
                    session_name,
                    content,
                    timestamp,
                    context_type,
                    metadata,
                    project,
                    platform
                FROM memories
                WHERE content LIKE ?
                  AND (compaction_role IS NULL OR compaction_role != 'source')
            """

            params = [f"%{query}%"]

            if session is not None:
                base += " AND session_name = ?"
                params.append(session)

            if project is not None:
                base += " AND project = ?"
                params.append(project)

            if platform is not None:
                base += " AND platform = ?"
                params.append(platform)

            base += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(base, params).fetchall()

        like_results = [
            {
                "id": row[0],
                "session_name": row[1],
                "content": row[2],
                "timestamp": row[3],
                "context_type": row[4],
                "metadata": json.loads(row[5]) if row[5] else {},
                "similarity": 0.0,
                "retrieval_mode": "exact_like",
                "project": row[6],
                "platform": row[7],
            }
            for row in rows
        ]
        _recall_debug(f"exact_like: {len(like_results)} results")
        return like_results
    except Exception as e:
        _recall_debug(f"exact_like fallback failed: {e}")
        return []


async def _recall_similar(
    mem,
    query: str,
    session: str = None,
    limit: int = 5,
    query_vec=None,
    include_scan_metadata: bool = False,
    exact_mode: str = "auto",
    project: str = None,
    platform: str = None,
):
    """Find semantically similar memories.

    exact_mode controls which retrieval lane is used:
      - "auto"     (default): automatically switches to the exact/lexical lane
                   when the query looks syntax-heavy (config keys, file paths,
                   CLI commands, API names, code snippets). Falls back to
                   semantic for natural-language queries.
      - "exact"    : always use the deterministic FTS/lexical lane. Exact or
                   lexical hits are never re-ranked by semantic similarity.
      - "semantic" : always use the semantic lane regardless of query shape.

    When include_scan_metadata=True, returns (List[Dict], dict) where the second
    element contains recall_scan_truncated and recall_scan_limit. All other callers
    receive List[Dict] as before.
    """
    scan_limit = RECALL_SCAN_LIMIT

    def _wrap(results, truncated):
        if include_scan_metadata:
            return results, {
                "recall_scan_truncated": truncated,
                "recall_scan_limit": scan_limit,
            }
        return results

    # --- Exact lane ---
    use_exact = (exact_mode == "exact") or (
        exact_mode == "auto" and _is_exact_query(query)
    )
    if use_exact:
        _recall_debug(
            f"exact lane selected (mode={exact_mode!r}, query='{query[:60]}')"
        )
        results = await _recall_exact(
            mem,
            query,
            session,
            limit,
            project=project,
            platform=platform,
        )
        return _wrap(results, False)

    if query_vec is None:
        if not mem._load_encoder_lazily():
            _recall_debug("semantic model unavailable → text-search fallback")
            return _wrap(
                await _recall_text_search(
                    mem, query, session, limit, project=project, platform=platform
                ),
                False,
            )

    try:
        if query_vec is not None:
            query_embedding = query_vec
        else:
            query_embedding = await asyncio.to_thread(mem._encode_sync, query)

        fts_query = _safe_fts_query(query)
        candidate_ids: list[str] = []
        if fts_query:
            try:
                candidate_ids = await asyncio.to_thread(
                    _fetch_fts_candidate_ids,
                    mem.db_path,
                    session,
                    fts_query,
                    max(limit, FTS_CANDIDATE_LIMIT),
                    project,
                    platform,
                )
                _recall_debug(
                    f"FTS filter: {len(candidate_ids)} candidates for '{fts_query}'"
                )
            except Exception as e:
                _safe_print(
                    f"FTS5 filter failed, falling back to bounded semantic recall: {e}"
                )
                _recall_debug("FTS filter failed → semantic fallback")

        use_semantic_fallback = True
        if candidate_ids:
            similarities, dim_skipped = await asyncio.to_thread(
                _fetch_and_score_by_ids,
                mem.db_path,
                candidate_ids,
                query_embedding,
            )
            if similarities:
                scan_truncated = False
                use_semantic_fallback = False
                _recall_debug(f"filter->rerank: scored {len(similarities)} candidates")
            else:
                _recall_debug(
                    "filter->rerank: no scoreable embeddings in FTS candidates, falling back to semantic scan"
                )

        if use_semantic_fallback:
            similarities, dim_skipped, scan_truncated = await asyncio.to_thread(
                _fetch_and_score_embedding_rows,
                mem.db_path,
                session,
                scan_limit,
                query_embedding,
                limit,
                project,
                platform,
            )
            _recall_debug(
                f"semantic fallback: {len(similarities)} candidates, scan_truncated={scan_truncated}"
            )

        if dim_skipped:
            _safe_print(
                f"recall_similar: skipped {dim_skipped} memories with wrong embedding dimension (expected {len(query_embedding)})"
            )

        combined: dict[str, tuple] = {}
        for mem_row, vec_score in similarities:
            t_score = _temporal_score(mem_row["timestamp"], TEMPORAL_HALF_LIFE_DAYS)
            combined[mem_row["id"]] = (
                mem_row,
                (1 - TEMPORAL_WEIGHT) * vec_score + TEMPORAL_WEIGHT * t_score,
            )

        ranked = sorted(combined.values(), key=lambda x: x[1], reverse=True)[:limit]

        results = []
        for memory, similarity in ranked:
            results.append(
                {
                    "id": memory["id"],
                    "session_name": memory["session_name"],
                    "content": memory["content"],
                    "timestamp": memory["timestamp"],
                    "context_type": memory["context_type"],
                    "metadata": json.loads(memory["metadata"])
                    if memory["metadata"]
                    else {},
                    "similarity": float(similarity),
                    "project": memory["project"],
                    "platform": memory["platform"],
                }
            )

        return _wrap(results, scan_truncated)

    except Exception as e:
        _safe_print(f"Semantic search failed: {e}")
        _recall_debug(f"semantic search exception → text-search fallback: {e}")
        return _wrap(
            await _recall_text_search(
                mem, query, session, limit, project=project, platform=platform
            ),
            False,
        )


async def _recall_text_search(
    mem,
    query: str,
    session: str = None,
    limit: int = 5,
    project: str = None,
    platform: str = None,
) -> List[Dict]:
    """Text search via FTS5 BM25 ranking, with LIKE fallback for unsanitizable queries."""
    _recall_debug(f"text-search path: query='{query[:50]}', session={session}")
    fts_query = _safe_fts_query(query)
    if fts_query is not None:
        try:
            fts_rows = await asyncio.to_thread(
                _fetch_and_score_fts_rows,
                mem.db_path,
                session,
                fts_query,
                limit,
                project,
                platform,
            )
            if fts_rows:
                _recall_debug(f"FTS5 returned {len(fts_rows)} results")
                return [
                    {
                        "id": row["id"],
                        "session_name": row["session_name"],
                        "content": row["content"],
                        "timestamp": row["timestamp"],
                        "context_type": row["context_type"],
                        "metadata": json.loads(row["metadata"])
                        if row["metadata"]
                        else {},
                        "similarity": float(score),
                        "project": row["project"],
                        "platform": row["platform"],
                    }
                    for row, score in fts_rows
                ]
        except Exception as e:
            _safe_print(f"FTS5 search failed, falling back to LIKE: {e}")
            _recall_debug("FTS5 failed → LIKE fallback")

    _recall_debug("FTS5 returned 0 or query unsanitizable → LIKE fallback")

    with mem.get_connection() as conn:
        base = """
            SELECT id, session_name, content, timestamp, context_type, metadata, project, platform
            FROM memories
            WHERE content LIKE ?
              AND (compaction_role IS NULL OR compaction_role != 'source')
        """
        params: list = [f"%{query}%"]
        if session is not None:
            base += " AND session_name = ?"
            params.append(session)
        if project is not None:
            base += " AND project = ?"
            params.append(project)
        if platform is not None:
            base += " AND platform = ?"
            params.append(platform)
        base += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = conn.execute(base, params)

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "id": row[0],
                    "session_name": row[1],
                    "content": row[2],
                    "timestamp": row[3],
                    "context_type": row[4],
                    "metadata": json.loads(row[5]) if row[5] else {},
                    "similarity": 0.8,
                    "project": row[6],
                    "platform": row[7],
                }
            )

        return results
