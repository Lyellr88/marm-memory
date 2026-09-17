"""Stage distilled memory proposals, and apply the ones a reviewer keeps.

The review loop is deliberately the same shape as `marm_compaction`: propose
into a staging table, show the proposals, apply or discard by id. Nothing here
writes a memory without being asked to, for the reason given in
`core/distill.py` -- a similarity score is not good enough evidence to write
memory unattended, and this store has the false-positive numbers to prove it.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..core.consolidation import compute_content_hash
from ..core.distill import (
    DEFAULT_LIMIT,
    DEFAULT_THRESHOLD,
    extract_candidates,
    resolve,
)
from ..core.memory import MARMMemory, sanitize_content

# A proposal nobody reviewed is not worth keeping indefinitely; the transcript
# it came from is long gone and its neighbour may have moved.
TTL_HOURS = int(os.environ.get("MARM_DISTILL_TTL_HOURS") or 168)

_HASH_SEPARATOR = "\x1f"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(session_name: str, content: str) -> str:
    """Identity of a proposal: its text, within its session.

    Session-scoped on purpose. The same sentence distilled in two different
    sessions is two proposals, because the reviewer deciding about it is
    working in one session and should not have their decision silently made
    for them by the other.
    """
    return compute_content_hash(f"{session_name}{_HASH_SEPARATOR}{content}")


async def propose(
    memory: MARMMemory,
    text: str,
    *,
    session_name: str,
    project: Optional[str] = None,
    context_type: str = "general",
    threshold: float = DEFAULT_THRESHOLD,
    limit: int = DEFAULT_LIMIT,
    include_duplicates: bool = False,
) -> dict[str, Any]:
    """Extract, resolve, stage. Returns the proposals with their verdicts.

    Duplicates are reported but not staged unless asked for. The useful output
    of a distil run is "here is what is NOT yet recorded" -- a reviewer asked to
    confirm forty things the store already knows will stop reading the list,
    and the first novel item is the one they will miss.
    """
    candidates = extract_candidates(text, threshold=threshold, limit=limit)
    if not candidates:
        return {
            "status": "success",
            "proposals": [],
            "extracted": 0,
            "staged": 0,
            "session_name": session_name,
            "note": (
                "Nothing in this text reads like a durable fact. That is the "
                "usual outcome for a conversation that was mostly doing rather "
                "than concluding -- it is not an error."
            ),
        }

    resolutions = await resolve(memory, candidates, session=None, project=project)

    now = _now()
    now_iso = now.isoformat()
    expires_at = (now + timedelta(hours=TTL_HOURS)).isoformat()

    proposals: list[dict[str, Any]] = []
    staged = 0
    with memory.get_connection() as conn:
        for candidate, resolution in zip(candidates, resolutions):
            record: dict[str, Any] = {
                "content": candidate.content,
                "score": candidate.score,
                "reasons": list(candidate.reasons),
                "verdict": resolution.verdict,
                "cosine": resolution.cosine,
            }
            if resolution.neighbour_id:
                record["neighbour_id"] = resolution.neighbour_id
            if resolution.neighbour_content:
                record["neighbour"] = resolution.neighbour_content

            if resolution.verdict == "duplicate" and not include_duplicates:
                record["staged"] = False
                record["note"] = "already recorded; not staged"
                proposals.append(record)
                continue

            row_id = str(uuid.uuid4())
            # INSERT OR IGNORE against the unique hash index, rather than the
            # check-then-insert compaction uses: two agents distilling the same
            # transcript at once otherwise both see "not present" and both
            # insert. It also means a DISCARDED proposal is never proposed
            # again, which is intended -- re-offering something a reviewer has
            # already rejected is how a review queue stops being read.
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO distill_staging
                    (id, session_name, content, score, reasons, verdict, cosine,
                     neighbour_id, neighbour_content, status, candidate_hash,
                     project, context_type, applied_memory_id, expires_at,
                     created_at, updated_at, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, NULL, ?,
                        ?, ?, NULL)
                """,
                (
                    row_id,
                    session_name,
                    candidate.content,
                    candidate.score,
                    json.dumps(list(candidate.reasons)),
                    resolution.verdict,
                    resolution.cosine,
                    resolution.neighbour_id,
                    resolution.neighbour_content,
                    _hash(session_name, candidate.content),
                    project,
                    context_type,
                    expires_at,
                    now_iso,
                    now_iso,
                ),
            )
            inserted = cursor.rowcount > 0
            record["staged"] = inserted
            if inserted:
                record["id"] = row_id
                staged += 1
            else:
                record["note"] = "already proposed, or already reviewed"
            proposals.append(record)

    return {
        "status": "success",
        "proposals": proposals,
        "extracted": len(candidates),
        "staged": staged,
        "session_name": session_name,
    }


def review(
    memory: MARMMemory,
    *,
    session_name: Optional[str] = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List proposals still awaiting a decision, best-scoring first."""
    now_iso = _now().isoformat()
    clauses = ["status = 'pending'", "expires_at > ?"]
    params: list[Any] = [now_iso]
    if session_name:
        clauses.append("session_name = ?")
        params.append(session_name)
    params.append(int(limit))

    with memory.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, session_name, content, score, reasons, verdict, cosine, "
            "neighbour_id, neighbour_content, project, context_type, created_at "
            f"FROM distill_staging WHERE {' AND '.join(clauses)} "
            "ORDER BY score DESC, created_at DESC LIMIT ?",
            params,
        ).fetchall()

    pending = []
    for row in rows:
        entry: dict[str, Any] = {
            "id": row[0],
            "session_name": row[1],
            "content": row[2],
            "score": row[3],
            "reasons": json.loads(row[4] or "[]"),
            "verdict": row[5],
            "cosine": row[6],
            "project": row[9],
            "context_type": row[10],
            "created_at": row[11],
        }
        if row[7]:
            entry["neighbour_id"] = row[7]
        if row[8]:
            entry["neighbour"] = row[8]
        pending.append(entry)

    return {"status": "success", "pending": pending, "count": len(pending)}


async def apply(memory: MARMMemory, proposal_id: str) -> dict[str, Any]:
    """Write one staged proposal into memory and mark it applied.

    The staging row is claimed BEFORE the write, not after. If the write then
    fails the claim is released, so the failure mode is a proposal that can be
    retried rather than a memory written twice -- which is the right way round
    for a store whose whole problem is duplicates.
    """
    now_iso = _now().isoformat()
    with memory.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT content, session_name, context_type, project, status, "
                "expires_at FROM distill_staging WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return {"status": "error", "error": f"no proposal {proposal_id}"}
            content, session_name, context_type, project, status, expires_at = row
            if status != "pending":
                conn.execute("ROLLBACK")
                return {
                    "status": "error",
                    "error": f"proposal {proposal_id} is already {status}",
                }
            if expires_at and now_iso > expires_at:
                conn.execute(
                    "UPDATE distill_staging SET status = 'stale', updated_at = ? "
                    "WHERE id = ?",
                    (now_iso, proposal_id),
                )
                conn.execute("COMMIT")
                return {"status": "error", "error": f"proposal {proposal_id} expired"}
            conn.execute(
                "UPDATE distill_staging SET status = 'applying', updated_at = ? "
                "WHERE id = ?",
                (now_iso, proposal_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    metadata: dict[str, Any] = {"source": "marm_distill", "proposal_id": proposal_id}
    if project:
        metadata["project"] = project
    try:
        memory_id = await memory.store_memory_queued(
            sanitize_content(content),
            session_name,
            context_type or "general",
            metadata,
        )
    except Exception as exc:
        with memory.get_connection() as conn:
            conn.execute(
                "UPDATE distill_staging SET status = 'pending', updated_at = ? "
                "WHERE id = ? AND status = 'applying'",
                (_now().isoformat(), proposal_id),
            )
        return {"status": "error", "error": f"write failed: {exc}"}

    done = _now().isoformat()
    with memory.get_connection() as conn:
        conn.execute(
            "UPDATE distill_staging SET status = 'applied', applied_memory_id = ?, "
            "reviewed_at = ?, updated_at = ? WHERE id = ?",
            (memory_id, done, done, proposal_id),
        )
    return {"status": "success", "memory_id": memory_id, "proposal_id": proposal_id}


def discard(memory: MARMMemory, proposal_id: str) -> dict[str, Any]:
    """Reject a proposal. It will not be proposed again -- see `propose`."""
    now_iso = _now().isoformat()
    with memory.get_connection() as conn:
        cursor = conn.execute(
            "UPDATE distill_staging SET status = 'discarded', reviewed_at = ?, "
            "updated_at = ? WHERE id = ? AND status = 'pending'",
            (now_iso, now_iso, proposal_id),
        )
    if cursor.rowcount == 0:
        return {"status": "error", "error": f"no pending proposal {proposal_id}"}
    return {"status": "success", "proposal_id": proposal_id}


__all__ = ["TTL_HOURS", "apply", "discard", "propose", "review"]
