import asyncio
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, ContextManager, Protocol

from .runtime_manager import runtime_dir

if TYPE_CHECKING:
    from .memory import MARMMemory

from ..config import settings


class _ConnectionSource(Protocol):
    """What find_compaction_candidates and run_compaction_dry_run actually need:
    a MARMMemory, or any read-only stand-in shaped the same way."""

    def get_connection(self) -> ContextManager[Any]: ...


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


def find_compaction_candidates(memory: _ConnectionSource, session_name: str) -> list:
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
        effective_role = col_role or metadata.get("compaction_role")
        if effective_role in ("source", "summary"):
            continue
        candidates.append(
            {
                "id": row_id,
                "content": content,
                "embedding": embedding,
                "timestamp": timestamp,
            }
        )

    if len(candidates) < settings.COMPACTION_MIN_CLUSTER_SIZE:
        return []

    threshold = settings.COMPACTION_SIMILARITY_THRESHOLD
    edges = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if (
                _cosine_similarity(
                    candidates[i]["embedding"], candidates[j]["embedding"]
                )
                >= threshold
            ):
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

        result.append(
            {
                "session_name": session_name,
                "source_memory_ids": [r["id"] for r in cluster],
                "reason": "semantic_cluster",
                "avg_similarity": round(avg_sim, 4),
                "oldest_timestamp": min(timestamps),
                "newest_timestamp": max(timestamps),
                "preview": [r["content"][:120] for r in cluster],
                "suggested_summary": None,
            }
        )

    return result


def _write_report(candidates: list, session_name: str) -> "Path | None":
    """Write candidates to a JSON report file. Returns the path, or None if no candidates
    or the write failed."""
    if not candidates:
        return None
    serializable = {
        "candidates": [
            {k: v for k, v in c.items() if k != "embedding"} for c in candidates
        ]
    }
    try:
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_session = re.sub(r"[^A-Za-z0-9_-]", "_", session_name) or "session"
        report_dir = runtime_dir() / "compaction-reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = (
            report_dir / f"compaction-report-{safe_session}-{timestamp_str}.json"
        )
        report_path.write_text(json.dumps(serializable, indent=2))
        return report_path
    except Exception as e:
        print(f"[compaction] failed to write report: {e}", file=sys.stderr)
        return None


def run_compaction_dry_run(memory: _ConnectionSource, session_name: str) -> dict:
    """Find compaction candidates and write a JSON report. No DB mutations."""
    candidates = find_compaction_candidates(memory, session_name)
    report_path = _write_report(candidates, session_name)
    return {
        "candidates": candidates,
        "report_path": str(report_path) if report_path else None,
    }


def _compute_candidate_hash(source_memory_ids: list) -> str:
    """SHA-256 of sorted source memory IDs — used to detect duplicate staging on re-scan."""
    payload = json.dumps(sorted(source_memory_ids), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_source_snapshot(conn: sqlite3.Connection, source_ids: list) -> dict:
    """Return {memory_id: content_hash} for the given source IDs (staleness fingerprint)."""
    placeholders = ",".join("?" * len(source_ids))
    rows = conn.execute(
        f"SELECT id, content_hash FROM memories WHERE id IN ({placeholders})",
        source_ids,
    ).fetchall()
    return dict(rows)


def persist_candidates_to_staging(memory: "MARMMemory", candidates: list) -> int:
    """Insert new compaction candidates into staging, skipping ones already seen.

    Returns the number of rows ACTUALLY inserted, which is not the number of
    candidates passed in: a cluster whose hash has already been put to a reviewer
    is skipped. Callers that report a count must use this rather than
    `len(candidates)`, or they claim to have staged work they de-duplicated away.
    """
    if not candidates:
        return 0

    now = datetime.now(timezone.utc)
    expires_at = (
        now + timedelta(hours=settings.COMPACTION_STAGING_TTL_HOURS)
    ).isoformat()
    now_iso = now.isoformat()
    inserted = 0

    with memory.get_connection() as conn:
        for candidate in candidates:
            source_ids = candidate["source_memory_ids"]
            candidate_hash = _compute_candidate_hash(source_ids)

            # 'discarded' is included because `discard` writes nothing to
            # `memories`: the sources stay eligible, so every later scan would
            # re-offer a rejected cluster. 'stale' is excluded because changed
            # sources are precisely what deserves a fresh look, and 'applied'
            # because apply marks its sources with compaction_role, which takes
            # the cluster out of find_compaction_candidates anyway.
            existing = conn.execute(
                "SELECT id FROM compaction_staging WHERE candidate_hash = ? "
                "AND status IN ('pending_summary', 'summary_staged', 'discarded')",
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
            inserted += 1

    return inserted


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
        'marm_compaction(action="stage", summaries=[{'
        '"candidate_id": "<candidate_id>", '
        '"suggested_summary": "..."'
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


def claim_pending_compaction_prompt(
    memory: "MARMMemory", session_name: str | None = None
) -> dict | None:
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
            _row_params = (
                (now, max_nudges, cutoff)
                if not session_name
                else (now, max_nudges, cutoff, session_name)
            )
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


def _sessions_needing_scan(memory: "MARMMemory") -> list:
    """Sessions whose compaction-eligible memories have changed since the last scan.

    The cheap pre-check that makes an hourly scan affordable: finding candidates
    is O(n^2) in a session's memory count.

    A session qualifies when at least MIN_CLUSTER_SIZE memories are past the age
    gate and the fingerprint of that set, `<count>:<newest eligible timestamp>`,
    differs from the one recorded at the last scan. Never scanned counts as
    differing.

    The fingerprint describes the SET rather than asking "did anything become
    eligible since the last scan?", because the latter answers no for a
    backdated insert -- memories imported with their original timestamps arrive
    already past the age gate.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=settings.COMPACTION_MIN_AGE_HOURS)).isoformat()

    with memory.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT m.session_name,
                   COUNT(*)                   AS eligible,
                   MAX(m.timestamp)           AS newest_eligible,
                   s.last_scan_fingerprint    AS fingerprint
            FROM memories AS m
            LEFT JOIN compaction_session_state AS s
                   ON s.session_name = m.session_name
            WHERE m.session_name != 'marm_system'
              AND m.timestamp < ?
              AND m.embedding IS NOT NULL
              AND (m.compaction_role IS NULL
                   OR m.compaction_role NOT IN ('source', 'summary'))
            GROUP BY m.session_name
            HAVING eligible >= ?
            """,
            (cutoff, settings.COMPACTION_MIN_CLUSTER_SIZE),
        ).fetchall()

    return [
        (session_name, f"{eligible}:{newest_eligible}")
        for session_name, eligible, newest_eligible, fingerprint in rows
        if fingerprint != f"{eligible}:{newest_eligible}"
    ]


def _sessions_with_active_candidates(memory: "MARMMemory") -> list:
    """Sessions holding a staged candidate that has not been resolved yet."""
    with memory.get_connection() as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT session_name FROM compaction_staging "
                "WHERE status IN ('pending_summary', 'summary_staged')"
            ).fetchall()
        ]


def _record_scan(
    memory: "MARMMemory", session_name: str, when: str, fingerprint: str
) -> None:
    """Remember what the eligible set looked like, so an unchanged session is
    skipped next interval. Written only after a scan completes: a scan that
    raised must be retried, not recorded as done."""
    with memory.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO compaction_session_state
                (session_name, write_count, updated_at, last_scanned_at, last_scan_fingerprint)
            VALUES (?, 0, ?, ?, ?)
            ON CONFLICT(session_name) DO UPDATE SET
                updated_at = excluded.updated_at,
                last_scanned_at = excluded.last_scanned_at,
                last_scan_fingerprint = excluded.last_scan_fingerprint
            """,
            (session_name, when, when, fingerprint),
        )


def run_periodic_compaction_scan(memory: "MARMMemory") -> dict:
    """Scan quiet sessions for compaction candidates. Synchronous by design.

    The write-driven trigger cannot reach a quiet session: it fires 15 minutes
    after the last write, while candidates must first be
    COMPACTION_MIN_AGE_HOURS old, and nothing re-scans afterwards. This is the
    time-driven trigger that does.

    Synchronous because the caller runs it off the event loop; the similarity
    pass is O(n^2) and would block every request alongside it.
    """
    if not settings.COMPACTION_ENABLED:
        return {"scanned": [], "skipped": [], "staged": 0}

    pending = getattr(memory, "_pending_compaction_scans", {})
    scanned: list = []
    skipped: list = []
    staged = 0

    # Every session holding staged candidates, not only those due a scan:
    # applying a compaction marks its sources compacted, which can drop the
    # session out of _sessions_needing_scan and strand a candidate that is still
    # injectable. Cheap -- no similarity pass.
    for session_name in _sessions_with_active_candidates(memory):
        try:
            mark_stale_candidates(memory, session_name)
        except Exception as e:
            print(f"[compaction] stale re-check failed for '{session_name}': {e}")

    for session_name, fingerprint in _sessions_needing_scan(memory):
        task = pending.get(session_name)
        if task is not None and not task.done():
            # The write-driven path already owns this session.
            skipped.append(session_name)
            continue
        try:
            mark_stale_candidates(memory, session_name)
            candidates = find_compaction_candidates(memory, session_name)
            staged += persist_candidates_to_staging(memory, candidates)
            _record_scan(
                memory,
                session_name,
                datetime.now(timezone.utc).isoformat(),
                fingerprint,
            )
            scanned.append(session_name)
        except Exception as e:
            # One bad session must not stop an unattended sweep.
            print(f"[compaction] periodic scan error for '{session_name}': {e}")
            skipped.append(session_name)

    return {"scanned": scanned, "skipped": skipped, "staged": staged}


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
        if memory._pending_compaction_scans.get(session_name) is asyncio.current_task():
            memory._pending_compaction_scans.pop(session_name, None)


def trigger_compaction(memory: "MARMMemory", session_name: str) -> None:
    """Reset write counter and schedule a delayed dry-run scan for this session."""
    memory._set_compaction_write_count(session_name, 0)
    try:
        loop = asyncio.get_running_loop()
        existing = memory._pending_compaction_scans.get(session_name)
        if existing and not existing.done():
            existing.cancel()
        task = loop.create_task(_delayed_scan(memory, session_name))
        memory._pending_compaction_scans[session_name] = task
    except RuntimeError:
        pass
