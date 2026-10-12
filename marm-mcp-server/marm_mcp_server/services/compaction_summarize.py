import asyncio
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

import numpy as np

from ..config.settings import COMPACTION_ENABLED
from ..core.compaction import _numeric_facts, _polarity, _tokens
from ..core.memory import MARMMemory, _safe_print
from ..core.redaction import redact_secrets


def _literal_copy(short: str, long: str) -> bool:
    return (
        bool(short.strip())
        and re.search(
            r"(?<!\w)(?<!\w[._#/-])" + re.escape(short) + r"(?!\w)(?![._#/-]\w)",
            long,
        )
        is not None
    )


def centroid_extract_summary(
    memories: list[tuple[str, bytes | None]],
    top_n: int = 5,
    dedup_threshold: float = 0.85,
    timestamps: list[str | None] | None = None,
) -> str:
    """Rank up to top_n memories by centroid similarity, then timestamp.

    Only a literal containing copy may replace a source, with numeric and
    known-polarity preservation. Different statements retain their history;
    top_n still bounds the number selected, not the number of facts preserved.
    """
    if timestamps is not None and len(timestamps) != len(memories):
        raise ValueError("timestamps must align with memories")

    def recorded_at(index: int) -> float:
        value = timestamps[index] if timestamps is not None else None
        try:
            date = datetime.fromisoformat(value or "")
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return date.timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            return float("-inf")

    parsed: list[tuple[str, np.ndarray, float]] = []
    unembedded: list[str] = []
    for index, (content, e) in enumerate(memories):
        if not e:
            unembedded.append(content)
            continue
        try:
            parsed.append(
                (content, np.frombuffer(e, dtype=np.float32), recorded_at(index))
            )
        except Exception:
            unembedded.append(content)

    if not parsed:
        return "\n\n".join(unembedded[:top_n])

    dims = [v.shape[0] for _, v, _ in parsed]
    expected_dim = max(set(dims), key=dims.count)
    embedded = [(c, v, t) for c, v, t in parsed if v.shape[0] == expected_dim]
    unembedded.extend(c for c, v, _ in parsed if v.shape[0] != expected_dim)

    contents = [c for c, _, _ in embedded]
    vecs = np.array([v for _, v, _ in embedded], dtype=np.float32)

    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    vecs_norm = vecs / norms

    centroid = vecs_norm.mean(axis=0)
    centroid_mag = np.linalg.norm(centroid)
    if centroid_mag > 0:
        centroid = centroid / centroid_mag

    scores = vecs_norm @ centroid
    ranked = sorted(
        range(len(embedded)),
        key=lambda i: (float(scores[i]), embedded[i][2]),
        reverse=True,
    )

    numeric_facts = [_numeric_facts(content) for content in contents]
    tokens = [_tokens(content) for content in contents]
    selected: list[int] = []
    # Repeat until nothing changes: a memory dropped as a near-copy of one
    # that was later replaced must be judged again against what is kept.
    # Replacements only lengthen a slot, so this terminates.
    changed = True
    while changed:
        changed = False
        for idx in ranked:
            if idx in selected:
                continue
            vec = vecs_norm[idx]
            duplicate_of = next(
                (
                    k
                    for k, chosen in enumerate(selected)
                    if float(vecs_norm[chosen] @ vec) > dedup_threshold
                    and bool(contents[chosen].strip())
                    and bool(contents[idx].strip())
                    and _polarity(tokens[chosen]) == _polarity(tokens[idx])
                    and (
                        (
                            _literal_copy(contents[chosen], contents[idx])
                            and numeric_facts[chosen] <= numeric_facts[idx]
                        )
                        or (
                            _literal_copy(contents[idx], contents[chosen])
                            and numeric_facts[idx] <= numeric_facts[chosen]
                        )
                    )
                ),
                None,
            )
            if duplicate_of is not None:
                # The summary replaces its sources, so of two near-copies keep
                # the one that says more.
                if len(contents[idx]) > len(contents[selected[duplicate_of]]):
                    selected[duplicate_of] = idx
                    changed = True
                continue
            if len(selected) < top_n:
                selected.append(idx)
                changed = True

    selected_content = [contents[idx] for idx in selected]

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
                    "SELECT content, embedding, timestamp FROM memories "
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
                timestamps=[row[2] for row in memory_rows],
            )

            now_inner = datetime.now(timezone.utc).isoformat()
            with memory_store.get_connection() as conn:
                cur = conn.execute(
                    "UPDATE compaction_staging "
                    "SET status = 'summary_staged', suggested_summary = ?, updated_at = ? "
                    "WHERE id = ? AND status = 'nudge_exhausted'",
                    (redact_secrets(summary)[0], now_inner, candidate_id),
                )
        except Exception as e:
            _safe_print(
                f"[compaction] server-side summarization failed for {candidate_id}: {e}"
            )
            continue

        if cur.rowcount > 0:
            processed += 1

    return processed
