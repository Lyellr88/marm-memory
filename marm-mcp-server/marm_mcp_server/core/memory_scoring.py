"""Vector scoring and DB fetch-and-score operations for the MARM memory system."""

import sqlite3
from typing import Any, Protocol, Sequence

import numpy as np

from ..config.settings import FTS_LONE_HIT_SCORE


class _Row(Protocol):
    """The row shape the scorers index into. Not sqlite3.Row: the chunk-scoring
    tests pass plain dicts carrying the same keys, and pinning the concrete class
    would make those call sites type errors."""

    def __getitem__(self, key: str, /) -> Any: ...


def _normalize_bm25(
    raw_scores: list[float], *, lone_hit_score: float = 1.0
) -> list[float]:
    """Map raw BM25 scores (more-negative = better) to [0, 1] with 1.0 best.

    Min-max needs a spread, so single-row and all-equal sets get lone_hit_score.
    The caller sets it because the evidence a lone hit represents depends on how
    its MATCH was built: strict AND means every term was present, a wide OR can
    mean one shared word.
    """
    if not raw_scores:
        return []
    min_s, max_s = min(raw_scores), max(raw_scores)
    if max_s == min_s:
        return [lone_hit_score for _ in raw_scores]
    span = max_s - min_s
    return [(max_s - s) / span for s in raw_scores]


def _score_embedding_rows(
    rows: Sequence[sqlite3.Row], query_embedding: np.ndarray, limit: int
) -> tuple[list[tuple[sqlite3.Row, float]], int]:
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
    memories: Sequence[_Row],
    chunks_by_id: dict[str, list],
    query_embedding: np.ndarray,
) -> tuple[list[tuple[_Row, float]], int]:
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
    vectors: list[np.ndarray] = []
    owners: list[int] = []

    for mem_index, mem in enumerate(memories):
        chunk_embs = chunks_by_id.get(mem["id"])
        # Chunked memories score max-over-chunks; unchunked fall back to the
        # parent embedding. A memory never mixes both.
        candidate_embs = chunk_embs if chunk_embs else [mem["embedding"]]

        for emb_bytes in candidate_embs:
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
            vectors.append(vec / norm)
            owners.append(mem_index)

    if not vectors:
        return [], dim_skipped

    matrix = np.vstack(vectors).astype(np.float32, copy=False)
    scores = matrix @ normalized_query

    # Collapse to one score per memory (max over its chunk rows).
    owner_arr = np.asarray(owners)
    best_scores = np.full(len(memories), -np.inf, dtype=np.float32)
    np.maximum.at(best_scores, owner_arr, scores)

    results = [
        (memories[i], float(best_scores[i]))
        for i in range(len(memories))
        if best_scores[i] != -np.inf
    ]
    results.sort(key=lambda x: x[1], reverse=True)
    return results, dim_skipped


def _fetch_and_score_embedding_rows(
    db_path: str,
    session: str | None,
    scan_limit: int,
    query_embedding: np.ndarray,
    limit: int,
    project: str | None = None,
    platform: str | None = None,
) -> tuple[list[tuple[_Row, float]], int, bool]:
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
    *,
    lone_hit_score: float = 1.0,
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
        base += " ORDER BY score, m.id LIMIT ?"
        params.append(limit)
        rows = conn.execute(base, params).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    normalized = _normalize_bm25(
        [row["score"] for row in rows], lone_hit_score=lone_hit_score
    )
    return list(zip(rows, normalized))


def _fetch_fts_candidate_ids(
    db_path: str,
    session: str | None,
    fts_query: str,
    limit: int,
    project: str | None = None,
    platform: str | None = None,
) -> list[tuple[str, float]]:
    """Return top N (memory_id, normalized_bm25) from FTS5 by BM25 rank.

    The BM25 score is normalized to [0, 1] (1.0 = best lexical match) so callers
    can fuse the lexical signal into the semantic blend instead of discarding it.
    """
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        base = """
            SELECT m.id, bm25(memories_fts) AS score
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
        # m.id breaks BM25 ties so the LIMIT cutoff is reproducible. Measured on
        # the LoCoMo corpus: 53.7% of queries have a tie straddling the 50-row
        # boundary, and without a tiebreak SQLite's row order there varied
        # between processes -- identical configs scored up to 0.5pp apart, which
        # is larger than several of the effects this pool is used to measure.
        base += " ORDER BY bm25(memories_fts), m.id LIMIT ?"
        params.append(limit)
        rows = conn.execute(base, params).fetchall()
    finally:
        conn.close()

    normalized = _normalize_bm25(
        [row[1] for row in rows], lone_hit_score=FTS_LONE_HIT_SCORE
    )
    return [(row[0], score) for row, score in zip(rows, normalized)]


def _fetch_and_score_by_ids(
    db_path: str,
    memory_ids: list[str],
    query_embedding: np.ndarray,
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
