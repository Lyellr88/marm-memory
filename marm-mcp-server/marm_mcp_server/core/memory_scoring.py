"""Vector scoring and DB fetch-and-score operations for the MARM memory system."""

import sqlite3
import numpy as np


def _score_embedding_rows(rows, query_embedding, limit: int):
    """Score embedding rows in one NumPy batch instead of a Python cosine loop."""
    if limit <= 0:
        return [], 0

    query_vec = np.asarray(query_embedding, dtype=np.float32)
    expected_dim = query_vec.shape[0]
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return [], 0
    normalized_query = query_vec / query_norm

    vectors = []
    kept_rows = []
    dim_skipped = 0

    for row in rows:
        try:
            vector = np.frombuffer(row[3], dtype=np.float32)
        except Exception:
            continue
        if vector.shape[0] != expected_dim:
            dim_skipped += 1
            continue
        vectors.append(vector)
        kept_rows.append(row)

    if not vectors:
        return [], dim_skipped

    matrix = np.vstack(vectors).astype(np.float32, copy=False)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / (norms + 1e-12)
    scores = matrix @ normalized_query

    top_count = min(limit, scores.shape[0])
    if top_count == 0:
        return [], dim_skipped

    top_indices = np.argpartition(scores, -top_count)[-top_count:]
    top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
    return [
        (kept_rows[index], float(scores[index])) for index in top_indices
    ], dim_skipped


def _score_chunk_aware(
    memories,
    chunks_by_id: dict,
    query_embedding,
) -> tuple[list[tuple], int]:
    """Score memories using chunk embeddings where available, parent embedding otherwise.

    Deduplicates to one (memory_row, best_score) per memory_id before returning.
    """
    query_vec = np.asarray(query_embedding, dtype=np.float32)
    expected_dim = query_vec.shape[0]
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return [], 0
    normalized_query = query_vec / query_norm

    dim_skipped = 0
    results = []

    for mem in memories:
        mem_id = mem["id"]
        chunk_embs = chunks_by_id.get(mem_id)

        if chunk_embs:
            best_score = None
            for emb_bytes in chunk_embs:
                try:
                    vec = np.frombuffer(emb_bytes, dtype=np.float32)
                except Exception:
                    continue
                if vec.shape[0] != expected_dim:
                    dim_skipped += 1
                    continue
                norm = np.linalg.norm(vec)
                if norm == 0:
                    continue
                score = float(np.dot(vec / norm, normalized_query))
                if best_score is None or score > best_score:
                    best_score = score
            if best_score is not None:
                results.append((mem, best_score))
        else:
            emb_bytes = mem["embedding"]
            if emb_bytes is None:
                continue
            try:
                vec = np.frombuffer(emb_bytes, dtype=np.float32)
            except Exception:
                continue
            if vec.shape[0] != expected_dim:
                dim_skipped += 1
                continue
            norm = np.linalg.norm(vec)
            if norm == 0:
                continue
            results.append((mem, float(np.dot(vec / norm, normalized_query))))

    results.sort(key=lambda x: x[1], reverse=True)
    return results, dim_skipped


def _fetch_and_score_embedding_rows(
    db_path: str,
    session: str | None,
    scan_limit: int,
    query_embedding,
    limit: int,
    project: str | None = None,
    platform: str | None = None,
):
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        base = """
            SELECT id, session_name, content, embedding, timestamp, context_type, metadata, project, platform
            FROM memories
            WHERE embedding IS NOT NULL
              AND (compaction_role IS NULL OR compaction_role != 'source')
        """
        params: list = []
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
        params.append(scan_limit + 1)
        memories = conn.execute(base, params).fetchall()

        scan_truncated = len(memories) > scan_limit
        memories = memories[:scan_limit]

        chunks_by_id: dict[str, list] = {}
        if memories:
            ids = [m["id"] for m in memories]
            placeholders = ",".join("?" * len(ids))
            for row in conn.execute(
                f"SELECT memory_id, embedding FROM memory_chunks WHERE memory_id IN ({placeholders})",
                ids,
            ).fetchall():
                chunks_by_id.setdefault(row[0], []).append(row[1])
    finally:
        conn.close()

    similarities, dim_skipped = _score_chunk_aware(
        memories, chunks_by_id, query_embedding
    )
    return similarities[:limit], dim_skipped, scan_truncated


def _fetch_and_score_fts_rows(
    db_path: str,
    session: str | None,
    fts_query: str,
    limit: int,
    project: str | None = None,
    platform: str | None = None,
) -> list[tuple]:
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        base = """
            SELECT m.id, m.session_name, m.content, m.timestamp,
                   m.context_type, m.metadata, m.project, m.platform,
                   bm25(memories_fts) AS score
            FROM memories_fts
            JOIN memories m ON memories_fts.rowid = m.rowid
            WHERE memories_fts MATCH ?
              AND (m.compaction_role IS NULL OR m.compaction_role != 'source')
        """
        params: list = [fts_query]
        if session is not None:
            base += " AND m.session_name = ?"
            params.append(session)
        if project is not None:
            base += " AND m.project = ?"
            params.append(project)
        if platform is not None:
            base += " AND m.platform = ?"
            params.append(platform)
        base += " ORDER BY score LIMIT ?"
        params.append(limit)
        rows = conn.execute(base, params).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    raw_scores = [row["score"] for row in rows]
    min_s, max_s = min(raw_scores), max(raw_scores)
    if max_s == min_s:
        normalized = [1.0 for _ in raw_scores]
    else:
        span = max_s - min_s
        normalized = [(max_s - s) / span for s in raw_scores]
    return list(zip(rows, normalized))


def _fetch_fts_candidate_ids(
    db_path: str,
    session: str | None,
    fts_query: str,
    limit: int,
    project: str | None = None,
    platform: str | None = None,
) -> list[str]:
    """Return top N memory IDs from FTS5 by BM25 rank. No scoring needed."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        base = """
            SELECT m.id
            FROM memories_fts
            JOIN memories m ON memories_fts.rowid = m.rowid
            WHERE memories_fts MATCH ?
              AND (m.compaction_role IS NULL OR m.compaction_role != 'source')
        """
        params: list = [fts_query]
        if session is not None:
            base += " AND m.session_name = ?"
            params.append(session)
        if project is not None:
            base += " AND m.project = ?"
            params.append(project)
        if platform is not None:
            base += " AND m.platform = ?"
            params.append(platform)
        base += " ORDER BY bm25(memories_fts) LIMIT ?"
        params.append(limit)
        rows = conn.execute(base, params).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def _fetch_and_score_by_ids(
    db_path: str,
    memory_ids: list[str],
    query_embedding,
) -> tuple[list[tuple], int]:
    """Fetch specific memories by ID and score their embeddings.

    Returns (similarities, dim_skipped). No scan_truncated -- ID-bounded
    fetch has no truncation concept.
    """
    if not memory_ids:
        return [], 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" * len(memory_ids))
        memories = conn.execute(
            f"""
            SELECT id, session_name, content, embedding, timestamp, context_type, metadata, project, platform
            FROM memories
            WHERE id IN ({placeholders})
              AND (compaction_role IS NULL OR compaction_role != 'source')
            """,
            memory_ids,
        ).fetchall()

        chunks_by_id: dict[str, list] = {}
        for row in conn.execute(
            f"SELECT memory_id, embedding FROM memory_chunks WHERE memory_id IN ({placeholders})",
            memory_ids,
        ).fetchall():
            chunks_by_id.setdefault(row[0], []).append(row[1])
    finally:
        conn.close()

    return _score_chunk_aware(memories, chunks_by_id, query_embedding)
