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
    # `nudge_exhausted` means "stop advertising this", not "discard it". Selecting
    # only `pending` made an un-answered proposal vanish from the queue and become
    # impossible to apply or discard -- a dead row nobody could reach.
    clauses = ["status IN ('pending', 'nudge_exhausted')", "expires_at > ?"]
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
            # `nudge_exhausted` means the queue stopped asking, not that the
            # proposal was resolved. review() and discard() both accept it, so
            # apply() must too -- otherwise an un-answered proposal can be
            # listed and thrown away but never accepted, which is a worse
            # half-state than not surfacing it at all.
            if status not in ("pending", "nudge_exhausted"):
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
            # The column, not just the metadata blob. Metadata is not what
            # project-filtered recall or code-context read, so a proposal applied
            # with project=... was landing unscoped.
            project=project,
            explicit_scope=bool(project),
        )
    except Exception as exc:
        with memory.get_connection() as conn:
            conn.execute(
                "UPDATE distill_staging SET status = 'pending', updated_at = ? "
                "WHERE id = ? AND status = 'applying'",
                (_now().isoformat(), proposal_id),
            )
        # The claim was released above, so this proposal really can be applied
        # again. Say so: the HTTP layer maps every error envelope to 400 by
        # default, and 400 tells a retry-aware caller the request itself was
        # wrong and must not be repeated.
        return {
            "status": "error",
            "error": f"write failed: {exc}",
            "retryable": True,
        }

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
            "updated_at = ? WHERE id = ? AND status IN ('pending', 'nudge_exhausted')",
            (now_iso, now_iso, proposal_id),
        )
    if cursor.rowcount == 0:
        return {"status": "error", "error": f"no pending proposal {proposal_id}"}
    return {"status": "success", "proposal_id": proposal_id}


__all__ = [
    "TTL_HOURS",
    "apply",
    "claim_pending_distill_prompt",
    "discard",
    "propose",
    "review",
]


# ---------------------------------------------------------------------------
# Review nudges.
#
# A staged proposal that nobody is told about is a proposal nobody reviews.
# Measured on this deployment: seven generated proposals sat pending for hours
# because the only way to learn the queue was non-empty was to open the Console
# page and look. `marm_compaction` has solved this since it shipped -- it asks
# the connected agent, through the same response-injection channel -- and this
# is deliberately the same mechanism rather than a second one.
#
# The expiry sweep lives here too, for the same reason compaction's does: the
# claim already takes the write lock and already walks the table, so a separate
# scheduler would be a second moving part doing a subset of this one's work.


def _prompt_block(row: tuple, byte_budget: int) -> dict:
    proposal_id, session, content, verdict, cosine, neighbour, expires_at, nudges = row
    lines = [
        "[MARM DISTILL REVIEW]",
        "",
        "A memory proposal is waiting for a decision. Read it, then call ONE of:",
        f'  marm_distill(action="apply",   proposal_id="{proposal_id}")',
        f'  marm_distill(action="discard", proposal_id="{proposal_id}")',
        "",
        f"session: {session}",
        f"verdict: {verdict}",
    ]
    if verdict != "new":
        lines.append(f"closest stored memory (cosine {cosine:.3f}):")
        lines.append(f"  {neighbour or '(unavailable)'}")
        lines.append(
            "A `near` verdict is why this needs you: an encoder cannot tell "
            "whether this refines the memory above or contradicts it."
        )
    lines += [
        f"expires: {expires_at}",
        f"nudge: {nudges + 1}",
        "",
        "Proposal:",
        f"  {content}",
        "",
        "Apply only what you would want recalled months from now. Discarding is "
        "permanent; it will not be proposed again.",
    ]
    return {"type": "text", "text": _truncate(("\n".join(lines)), byte_budget)}


def _truncate(text: str, byte_budget: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= byte_budget:
        return text
    if byte_budget <= 3:
        return "..."[:byte_budget]
    return encoded[: byte_budget - 3].decode("utf-8", errors="ignore") + "..."


def claim_pending_distill_prompt(
    memory: MARMMemory, session_name: Optional[str] = None
) -> Optional[dict]:
    """Claim one pending proposal for response injection, or None.

    Sweeps first: expired rows become `stale` and over-nudged rows become
    `nudge_exhausted`, so a queue nobody ever answers stops asking rather than
    nagging forever, and rows past their TTL stop accumulating invisibly --
    `review` already filtered them out, so without this they were a slow leak.

    Uses BEGIN IMMEDIATE and rowcount rather than SQLite RETURNING, matching
    compaction, so older bundled sqlite3 builds keep working.
    """
    from ..config import settings

    if not getattr(settings, "DISTILL_NUDGE_ENABLED", True):
        return None

    now_dt = _now()
    now = now_dt.isoformat()
    cooldown = getattr(settings, "DISTILL_NUDGE_COOLDOWN_SECONDS", 900)
    cutoff = (now_dt - timedelta(seconds=cooldown)).isoformat()
    max_nudges = getattr(settings, "DISTILL_MAX_NUDGES", 3)
    budget = getattr(settings, "DISTILL_INJECTION_BYTE_BUDGET", 1536)

    with memory.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "UPDATE distill_staging SET status = 'stale', updated_at = ? "
                "WHERE status = 'pending' AND expires_at <= ?",
                (now, now),
            )
            conn.execute(
                "UPDATE distill_staging SET status = 'nudge_exhausted', updated_at = ? "
                "WHERE status = 'pending' AND nudge_count >= ?",
                (now, max_nudges),
            )
            # GLOBAL cooldown, not per-row. Compaction's is per-candidate,
            # which is fine when candidates are rare -- but a distil run stages
            # a batch, and a per-row cooldown would then put a review request
            # on N consecutive tool responses. That is precisely the terminal
            # noise agents already get complained about. One request per
            # window, whichever proposal it is.
            last = conn.execute(
                "SELECT MAX(last_nudged_at) FROM distill_staging WHERE last_nudged_at IS NOT NULL"
            ).fetchone()
            if last and last[0] and last[0] > cutoff:
                conn.execute("COMMIT")
                return None

            clauses = [
                "status = 'pending'",
                "expires_at > ?",
                "nudge_count < ?",
                "(last_nudged_at IS NULL OR last_nudged_at <= ?)",
            ]
            params: list[Any] = [now, max_nudges, cutoff]
            if session_name:
                clauses.append("session_name = ?")
                params.append(session_name)
            row = conn.execute(
                "SELECT id, session_name, content, verdict, cosine, neighbour_content, "
                "expires_at, nudge_count FROM distill_staging "
                f"WHERE {' AND '.join(clauses)} "
                # Best first: a reviewer's attention is the scarce resource, and
                # the highest-scoring proposal is the one most worth spending it on.
                "ORDER BY score DESC, created_at ASC LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            claimed = conn.execute(
                "UPDATE distill_staging SET nudge_count = nudge_count + 1, "
                "last_nudged_at = ?, updated_at = ? WHERE id = ? AND status = 'pending'",
                (now, now, row[0]),
            )
            if claimed.rowcount != 1:
                # Another request claimed it between the select and the update.
                conn.execute("ROLLBACK")
                return None
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    return _prompt_block(row, budget)
