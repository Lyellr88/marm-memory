"""Compaction worker — Layer 3 cluster detection and dry-run reporting (V1), staging (V2)."""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory import MARMMemory

from ..config import settings


COMPACTION_PROMPT_TEMPLATE = (
    "You are summarizing a cluster of related memories from a MARM memory session.\n\n"
    "Rules:\n"
    "- Do not discard original content without traceability\n"
    "- Do not invent facts outside the provided context window\n"
    "- Preserve all key entities, dates, and decisions\n"
    "- Output a single concise summary that captures all distinct information\n\n"
    "Source memories:\n{memories}\n\n"
    "Write a single-paragraph summary that preserves all key facts from the memories above."
)


def _cosine_similarity(a: bytes, b: bytes) -> float:
    import numpy as np
    va = np.frombuffer(a, dtype=np.float32)
    vb = np.frombuffer(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def _connected_components(n: int, edges: list) -> list:
    """Union-find connected components on n nodes with the given edge list."""
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in edges:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    groups: dict = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def find_compaction_candidates(memory: "MARMMemory", session_name: str) -> list:
    """Query session memories, group by similarity, return candidate clusters.

    Returns empty list if no qualifying embedded clusters are found.
    """
    min_age_cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=settings.COMPACTION_MIN_AGE_HOURS)
    ).isoformat()

    with memory.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, content, embedding, timestamp, metadata, compaction_role
            FROM memories
            WHERE session_name = ?
              AND session_name != 'marm_system'
              AND timestamp < ?
              AND embedding IS NOT NULL
            """,
            (session_name, min_age_cutoff),
        ).fetchall()

    if not rows:
        return []

    candidates = []
    for row_id, content, embedding, timestamp, metadata_json, col_role in rows:
        metadata = json.loads(metadata_json) if metadata_json else {}
        # col_role is authoritative (V3 writes here); fall back to metadata JSON for legacy rows
        effective_role = col_role or metadata.get("compaction_role")
        if effective_role in ("source", "summary"):
            continue
        candidates.append({
            "id": row_id,
            "content": content,
            "embedding": embedding,
            "timestamp": timestamp,
        })

    if len(candidates) < settings.COMPACTION_MIN_CLUSTER_SIZE:
        return []

    threshold = settings.COMPACTION_SIMILARITY_THRESHOLD
    edges = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if _cosine_similarity(candidates[i]["embedding"], candidates[j]["embedding"]) >= threshold:
                edges.append((i, j))

    components = _connected_components(len(candidates), edges)

    result = []
    for component in components:
        if len(component) < settings.COMPACTION_MIN_CLUSTER_SIZE:
            continue

        cluster = [candidates[i] for i in component]
        timestamps = [r["timestamp"] for r in cluster]

        pair_sims = [
            _cosine_similarity(cluster[i]["embedding"], cluster[j]["embedding"])
            for i in range(len(cluster))
            for j in range(i + 1, len(cluster))
        ]
        avg_sim = sum(pair_sims) / len(pair_sims) if pair_sims else 0.0

        result.append({
            "session_name": session_name,
            "source_memory_ids": [r["id"] for r in cluster],
            "reason": "semantic_cluster",
            "avg_similarity": round(avg_sim, 4),
            "oldest_timestamp": min(timestamps),
            "newest_timestamp": max(timestamps),
            "preview": [r["content"][:120] for r in cluster],
            "suggested_summary": None,
        })

    return result


def _write_report(candidates: list, session_name: str) -> "Path | None":
    """Write candidates to a JSON report file. Returns the path, or None if no candidates."""
    if not candidates:
        return None
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_session = session_name.replace("/", "_").replace("\\", "_")
    report_dir = Path.cwd() / "scripts" / "out" / "compaction"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"compaction-report-{safe_session}-{timestamp_str}.json"
    serializable = {
        "candidates": [
            {k: v for k, v in c.items() if k != "embedding"}
            for c in candidates
        ]
    }
    try:
        report_path.write_text(json.dumps(serializable, indent=2))
        return report_path
    except Exception as e:
        print(f"[compaction] failed to write report: {e}")
        return None


def run_compaction_dry_run(memory: "MARMMemory", session_name: str) -> dict:
    """Find compaction candidates and write a JSON report. No DB mutations."""
    candidates = find_compaction_candidates(memory, session_name)
    _write_report(candidates, session_name)
    return {"candidates": candidates}


# --- V2: staging helpers ---

def _compute_candidate_hash(source_memory_ids: list) -> str:
    """SHA-256 of sorted source memory IDs — used to detect duplicate staging on re-scan."""
    payload = json.dumps(sorted(source_memory_ids), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_source_snapshot(conn, source_ids: list) -> dict:
    """Return {memory_id: content_hash} for the given source IDs (staleness fingerprint)."""
    placeholders = ",".join("?" * len(source_ids))
    rows = conn.execute(
        f"SELECT id, content_hash FROM memories WHERE id IN ({placeholders})",
        source_ids,
    ).fetchall()
    return {row_id: content_hash for row_id, content_hash in rows}


def persist_candidates_to_staging(memory: "MARMMemory", candidates: list) -> None:
    """Insert new compaction candidates into staging table, skipping duplicates.

    Uses candidate_hash to detect clusters that are already active in staging
    (pending_summary or summary_staged). Does not re-insert applied/discarded/stale rows.
    """
    if not candidates:
        return

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=settings.COMPACTION_STAGING_TTL_HOURS)).isoformat()
    now_iso = now.isoformat()

    with memory.get_connection() as conn:
        for candidate in candidates:
            source_ids = candidate["source_memory_ids"]
            candidate_hash = _compute_candidate_hash(source_ids)

            existing = conn.execute(
                "SELECT id FROM compaction_staging "
                "WHERE candidate_hash = ? AND status IN ('pending_summary', 'summary_staged')",
                (candidate_hash,),
            ).fetchone()
            if existing:
                continue

            snapshot = _get_source_snapshot(conn, source_ids)
            row_id = str(uuid.uuid4())

            conn.execute(
                """
                INSERT INTO compaction_staging
                    (id, session_name, source_memory_ids, preview, suggested_summary,
                     status, candidate_hash, source_updated_at_snapshot,
                     expires_at, created_at, updated_at, reviewed_at)
                VALUES (?, ?, ?, ?, NULL, 'pending_summary', ?, ?, ?, ?, ?, NULL)
                """,
                (
                    row_id,
                    candidate["session_name"],
                    json.dumps(source_ids),
                    json.dumps(candidate["preview"]),
                    candidate_hash,
                    json.dumps(snapshot),
                    expires_at,
                    now_iso,
                    now_iso,
                ),
            )


def mark_stale_candidates(memory: "MARMMemory", session_name: str) -> None:
    """Mark expired or invalidated staging rows as stale before a new scan.

    Checks:
    - candidates past expires_at
    - source rows that have changed (content_hash mismatch)
    - source rows that were already compacted (compaction_role set)
    - source rows that no longer exist
    """
    now = datetime.now(timezone.utc).isoformat()

    with memory.get_connection() as conn:
        active_rows = conn.execute(
            """
            SELECT id, source_memory_ids, source_updated_at_snapshot, expires_at
            FROM compaction_staging
            WHERE session_name = ? AND status IN ('pending_summary', 'summary_staged')
            """,
            (session_name,),
        ).fetchall()

        for row_id, source_ids_json, snapshot_json, expires_at in active_rows:
            if expires_at and now > expires_at:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                    (now, row_id),
                )
                continue

            source_ids = json.loads(source_ids_json)
            snapshot = json.loads(snapshot_json)

            placeholders = ",".join("?" * len(source_ids))
            current_rows = conn.execute(
                f"SELECT id, content_hash, compaction_role FROM memories "
                f"WHERE id IN ({placeholders})",
                source_ids,
            ).fetchall()

            # Any missing source row = stale
            if len(current_rows) != len(source_ids):
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                    (now, row_id),
                )
                continue

            stale = False
            for mem_id, content_hash, compaction_role in current_rows:
                if compaction_role is not None:
                    stale = True
                    break
                if snapshot.get(mem_id) != content_hash:
                    stale = True
                    break

            if stale:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                    (now, row_id),
                )


def _truncate_utf8(text: str, byte_budget: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= byte_budget:
        return text
    if byte_budget <= 3:
        return "..."[:byte_budget]
    return encoded[: byte_budget - 3].decode("utf-8", errors="ignore") + "..."


def _build_compaction_prompt_block(row: tuple, byte_budget: int) -> dict:
    (
        candidate_id,
        session_name,
        source_ids_json,
        preview_json,
        created_at,
        expires_at,
        nudge_count,
    ) = row
    source_ids = json.loads(source_ids_json)
    preview = json.loads(preview_json)

    header = (
        "[MARM COMPACTION REQUEST]\n\n"
        "MARM found related memories that should be compacted. Generate one concise "
        "summary using only the source previews below, then call:\n\n"
        "marm_compaction(action=\"stage\", summaries=[{"
        "\"candidate_id\": \"<candidate_id>\", "
        "\"suggested_summary\": \"...\""
        "}])\n\n"
        f"candidate_id: {candidate_id}\n"
        f"session_name: {session_name}\n"
        f"source_memory_ids: {json.dumps(source_ids)}\n"
        f"created_at: {created_at}\n"
        f"expires_at: {expires_at}\n"
        f"nudge_count: {nudge_count}\n\n"
        "Source previews:\n"
    )
    footer = "\n\nDo not invent facts. Preserve entities, dates, decisions, and traceability."
    footer_size = len(footer.encode("utf-8"))
    if byte_budget <= footer_size:
        return {"type": "text", "text": _truncate_utf8(footer, byte_budget)}

    header_budget = byte_budget - footer_size
    fitted_header = _truncate_utf8(header, header_budget)
    remaining = max(byte_budget - len((fitted_header + footer).encode("utf-8")), 0)
    preview_text = "\n".join(f"- {item}" for item in preview)
    text = fitted_header + _truncate_utf8(preview_text, remaining) + footer
    return {"type": "text", "text": text}


def claim_pending_compaction_prompt(memory: "MARMMemory", session_name: str | None = None) -> dict | None:
    """Claim one pending compaction candidate for response injection.

    Uses a BEGIN IMMEDIATE transaction plus rowcount checks instead of SQLite
    RETURNING so older bundled sqlite3 versions remain compatible.
    """
    if not settings.COMPACTION_ENABLED:
        return None

    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    cutoff = (
        now_dt - timedelta(seconds=settings.COMPACTION_NUDGE_COOLDOWN_SECONDS)
    ).isoformat()
    max_nudges = settings.COMPACTION_MAX_NUDGES
    byte_budget = settings.COMPACTION_INJECTION_BYTE_BUDGET

    with memory.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                UPDATE compaction_staging
                SET status = 'stale', updated_at = ?
                WHERE status = 'pending_summary' AND expires_at <= ?
                """,
                (now, now),
            )
            conn.execute(
                """
                UPDATE compaction_staging
                SET status = 'nudge_exhausted', updated_at = ?
                WHERE status = 'pending_summary' AND nudge_count >= ?
                """,
                (now, max_nudges),
            )
            _session_filter = " AND session_name = ?" if session_name else ""
            _row_params = (now, max_nudges, cutoff) if not session_name else (now, max_nudges, cutoff, session_name)
            row = conn.execute(
                f"""
                SELECT id, session_name, source_memory_ids, preview, created_at,
                       expires_at, nudge_count
                FROM compaction_staging
                WHERE status = 'pending_summary'
                  AND expires_at > ?
                  AND nudge_count < ?
                  AND (last_nudged_at IS NULL OR last_nudged_at < ?)
                  {_session_filter}
                ORDER BY created_at ASC
                LIMIT 1
                """,
                _row_params,
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None

            candidate_id = row[0]
            cur = conn.execute(
                """
                UPDATE compaction_staging
                SET nudge_count = nudge_count + 1,
                    last_nudged_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'pending_summary'
                  AND nudge_count < ?
                  AND (last_nudged_at IS NULL OR last_nudged_at < ?)
                """,
                (now, now, candidate_id, max_nudges, cutoff),
            )
            if cur.rowcount == 0:
                conn.execute("COMMIT")
                return None

            claimed = conn.execute(
                """
                SELECT id, session_name, source_memory_ids, preview, created_at,
                       expires_at, nudge_count
                FROM compaction_staging
                WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    return _build_compaction_prompt_block(claimed, byte_budget) if claimed else None


async def _delayed_scan(memory: "MARMMemory", session_name: str) -> None:
    delay = settings.COMPACTION_ACTIVE_SESSION_GRACE_MINUTES * 60
    await asyncio.sleep(delay)
    try:
        mark_stale_candidates(memory, session_name)
        candidates = find_compaction_candidates(memory, session_name)
        persist_candidates_to_staging(memory, candidates)
    except Exception as e:
        print(f"[compaction] scan error for session '{session_name}': {e}")
    finally:
        # Only remove if this task is still the current one — a newer scan may
        # have been scheduled between cancellation and this finally running.
        if memory._pending_compaction_scans.get(session_name) is asyncio.current_task():
            memory._pending_compaction_scans.pop(session_name, None)


def trigger_compaction(memory: "MARMMemory", session_name: str) -> None:
    """Reset write counter and schedule a delayed dry-run scan for this session."""
    memory._session_write_counts[session_name] = 0
    try:
        loop = asyncio.get_running_loop()
        existing = memory._pending_compaction_scans.get(session_name)
        if existing and not existing.done():
            existing.cancel()
        task = loop.create_task(_delayed_scan(memory, session_name))
        memory._pending_compaction_scans[session_name] = task
    except RuntimeError:
        pass
