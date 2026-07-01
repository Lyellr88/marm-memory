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


async def _update_memory(mem, memory_id: str, new_content: str) -> None:
    """Append new_content into an existing memory and record the merge in metadata.

    Recomputes content_hash and embedding so Layer 1 dedup and semantic recall
    stay accurate after the merge.
    """
    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT content, metadata FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return
        existing_content, metadata_json = row
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
                merged_embedding_bytes = merged_vec.tobytes()
            except Exception as e:
                _safe_print(f"Failed to regenerate embedding after merge: {e}")

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

    with mem.get_connection() as conn:
        conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))

    chunks = _chunk_text(merged_content)
    if chunks and mem._load_encoder_lazily():
        _chunk_task = asyncio.create_task(  # noqa: RUF006
            _write_chunks(mem, mem.db_path, memory_id, chunks, merged_hash)
        )


async def _store_memory(
    mem,
    content: str,
    session: str,
    context_type: str = "general",
    metadata: Dict = None,
) -> str:
    """Store content with vector embedding for semantic search"""
    sanitized_content = sanitize_content(content)

    if context_type == "general":
        context_type = await mem.auto_classify_content(sanitized_content)

    content_hash = compute_content_hash(sanitized_content)
    normalized_content = normalize_content(sanitized_content)

    if CONSOLIDATION_ENABLED:
        with mem.get_connection() as conn:
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
            pre_embedding_bytes = pre_embedding.tobytes()
        except Exception as e:
            _safe_print(f"Failed to generate embedding: {e}")

    if CONSOLIDATION_ENABLED:
        existing_id = await find_semantic_duplicate(
            mem,
            sanitized_content,
            session,
            CONSOLIDATION_THRESHOLD,
            query_vec=pre_embedding,
        )
        if existing_id:
            await _update_memory(mem, existing_id, sanitized_content)
            mem._on_memory_written(session)
            return existing_id

    memory_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    metadata = metadata or {}

    embedding_bytes = pre_embedding_bytes

    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if CONSOLIDATION_ENABLED:
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
                MARM_PROJECT or None,
                MARM_PLATFORM or None,
            ),
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO sessions (session_name, last_accessed)
            VALUES (?, ?)
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
