"""Server-side extractive compaction summarization using embedding centroid."""

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone

import numpy as np

from ..config.settings import COMPACTION_ENABLED
from ..core.memory import MARMMemory, _safe_print


def centroid_extract_summary(
    memories: list[tuple[str, bytes | None]],
    top_n: int = 5,
    dedup_threshold: float = 0.85,
) -> str:
    """Extractive summary via embedding centroid with cosine-distance dedup.

    Ranks source memories by similarity to their centroid, then selects
    top_n most representative — skipping any that are >dedup_threshold
    similar to an already-selected memory.
    """
    parsed: list[tuple[str, np.ndarray]] = []
    unembedded: list[str] = []
    for content, e in memories:
        if not e:
            unembedded.append(content)
            continue
        try:
            parsed.append((content, np.frombuffer(e, dtype=np.float32)))
        except Exception:
            unembedded.append(content)

    if not parsed:
        return "\n\n".join(unembedded[:top_n])

    dims = [v.shape[0] for _, v in parsed]
    expected_dim = max(set(dims), key=dims.count)
    embedded = [(c, v) for c, v in parsed if v.shape[0] == expected_dim]
    unembedded.extend(c for c, v in parsed if v.shape[0] != expected_dim)

    contents = [c for c, _ in embedded]
    vecs = np.array([v for _, v in embedded], dtype=np.float32)

    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    vecs_norm = vecs / norms

    centroid = vecs_norm.mean(axis=0)
    centroid_mag = np.linalg.norm(centroid)
    if centroid_mag > 0:
        centroid = centroid / centroid_mag

    scores = vecs_norm @ centroid
    ranked = np.argsort(scores)[::-1]

    selected_content: list[str] = []
    selected_vecs: list[np.ndarray] = []

    for idx in ranked:
        if len(selected_content) >= top_n:
            break
        vec = vecs_norm[idx]
        if selected_vecs and np.any(np.array(selected_vecs) @ vec > dedup_threshold):
            continue
        selected_content.append(contents[idx])
        selected_vecs.append(vec)

    remaining = top_n - len(selected_content)
    if remaining > 0:
        selected_content.extend(unembedded[:remaining])

    return "\n\n".join(selected_content)


def _mark_candidate_stale(memory_store: MARMMemory, candidate_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with memory_store.get_connection() as conn:
        conn.execute(
            "UPDATE compaction_staging SET status = 'stale', updated_at = ? "
            "WHERE id = ? AND status = 'nudge_exhausted'",
            (now, candidate_id),
        )


def _parse_source_ids(source_ids_json: str) -> list[str]:
    source_ids = json.loads(source_ids_json)
    if not isinstance(source_ids, list) or not source_ids:
        raise ValueError("source_memory_ids must be a non-empty list")

    parsed = []
    for source_id in source_ids:
        if not isinstance(source_id, str):
            raise TypeError("source_memory_ids entries must be strings")
        parsed.append(str(uuid.UUID(source_id)))
    return parsed


async def process_nudge_exhausted_candidates(memory_store: MARMMemory) -> int:
    """Promote nudge_exhausted compaction candidates to summary_staged using
    server-side centroid extraction. Returns count of candidates processed.

    Called by the APScheduler maintenance job before auto_apply_staged_summaries
    so promoted candidates are picked up in the same scheduler tick.
    """
    if not COMPACTION_ENABLED:
        return 0

    now = datetime.now(timezone.utc).isoformat()

    with memory_store.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, session_name, source_memory_ids FROM compaction_staging "
            "WHERE status = 'nudge_exhausted' AND expires_at > ?",
            (now,),
        ).fetchall()

    if not rows:
        return 0

    processed = 0
    for candidate_id, session_name, source_ids_json in rows:
        try:
            source_ids = _parse_source_ids(source_ids_json)
            placeholders = ",".join("?" * len(source_ids))

            with memory_store.get_connection() as conn:
                memory_rows = conn.execute(
                    "SELECT content, embedding FROM memories "
                    f"WHERE session_name = ? AND id IN ({placeholders})",
                    [session_name, *source_ids],
                ).fetchall()
        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
            sqlite3.DatabaseError,
        ) as e:
            _safe_print(f"[compaction] invalid source IDs for {candidate_id}: {e}")
            _mark_candidate_stale(memory_store, candidate_id)
            continue

        if len(memory_rows) != len(source_ids):
            _mark_candidate_stale(memory_store, candidate_id)
            continue

        try:
            summary = await asyncio.to_thread(
                centroid_extract_summary,
                [(row[0], row[1]) for row in memory_rows],
            )

            now_inner = datetime.now(timezone.utc).isoformat()
            with memory_store.get_connection() as conn:
                cur = conn.execute(
                    "UPDATE compaction_staging "
                    "SET status = 'summary_staged', suggested_summary = ?, updated_at = ? "
                    "WHERE id = ? AND status = 'nudge_exhausted'",
                    (summary, now_inner, candidate_id),
                )
        except Exception as e:
            _safe_print(
                f"[compaction] server-side summarization failed for {candidate_id}: {e}"
            )
            continue

        if cur.rowcount > 0:
            processed += 1

    return processed
