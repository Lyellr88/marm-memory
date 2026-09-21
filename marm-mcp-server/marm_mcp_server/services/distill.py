"""Stage distilled memory proposals, and apply the ones a reviewer keeps.

The review loop is deliberately the same shape as `marm_compaction`: propose
into a staging table, show the proposals, apply or discard by id. Nothing here
writes a memory without being asked to, for the reason given in
`core/distill.py` -- a similarity score is not good enough evidence to write
memory unattended, and this store has the false-positive numbers to prove it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import sqlite3
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


def _hash(session_name: str, content: str, project: "str | None") -> str:
    """Identity of a proposal: its text, within its session AND its project.

    Session-scoped so that the same sentence distilled in two sessions is two
    proposals -- the reviewer deciding in one should not have the decision made
    for them by the other.

    Project is in the identity for the same reason. Without it the unique
    `candidate_hash` index suppresses the same content proposed for a different
    project in one session, including after the first was discarded, so a
    project could never be offered a fact another project had rejected.
    """
    # Only the CONTENT is normalised. `compute_content_hash` lowercases and
    # strips its whole input, so folding the scope through it would make
    # `Alpha` and `alpha` the same proposal and the unique index would drop one
    # of two legitimately distinct ones. A session name and a project are
    # identifiers, not prose.
    identity = json.dumps(
        {
            "session": session_name,
            "project": project or "",
            "content": compute_content_hash(content),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


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
                    _hash(session_name, candidate.content, project),
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


#: How long an `applying` claim is trusted before it is treated as abandoned.
#: Long enough that a slow write is never stolen, short enough that a crashed
#: apply is recoverable without operator action.
_APPLY_CLAIM_SECONDS = 300

#: How often a still-running apply() renews its claim's timestamp. Comfortably
#: under _APPLY_CLAIM_SECONDS so a live write refreshes it well before it
#: could look abandoned. HTTP and STDIO are separate processes with their own
#: write queues, sharing only the SQLite database -- so the renewal has to be
#: a persisted timestamp, not process-local state, for a second process to
#: read the same, correct answer.
_APPLY_HEARTBEAT_SECONDS = 60


async def _heartbeat_claim(memory: MARMMemory, proposal_id: str) -> None:
    """Keep an `applying` claim's timestamp fresh while its write is in flight."""
    try:
        while True:
            await asyncio.sleep(_APPLY_HEARTBEAT_SECONDS)
            with memory.get_connection() as conn:
                conn.execute(
                    "UPDATE distill_staging SET updated_at = ? "
                    "WHERE id = ? AND status = 'applying'",
                    (_now().isoformat(), proposal_id),
                )
    except asyncio.CancelledError:
        pass


def _claim_is_stale(claimed_at: "str | None", now_iso: str) -> bool:
    """Has an `applying` claim been held longer than any real write would take?

    An unparseable or missing timestamp counts as stale: the row predates the
    claim bookkeeping, so there is nothing in flight to protect.
    """
    if not claimed_at:
        return True
    try:
        held = datetime.fromisoformat(now_iso) - datetime.fromisoformat(claimed_at)
    except ValueError:
        return True
    return held.total_seconds() >= _APPLY_CLAIM_SECONDS


def _applied_memory_id(conn: "sqlite3.Connection", proposal_id: str) -> "str | None":
    """The memory this proposal already wrote, if it did.

    `apply()` stamps `proposal_id` into the memory's metadata before the write,
    which makes the write recoverable: the staging row and the memory live in
    separate transactions, so a crash between them leaves the memory stored and
    the proposal `applying` forever.
    """
    row = conn.execute(
        "SELECT id FROM memories WHERE json_extract(metadata, '$.proposal_id') = ? "
        "ORDER BY rowid LIMIT 1",
        (proposal_id,),
    ).fetchone()
    return row[0] if row else None


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
                "expires_at, updated_at FROM distill_staging WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return {"status": "error", "error": f"no proposal {proposal_id}"}
            (
                content,
                session_name,
                context_type,
                project,
                status,
                expires_at,
                claimed_at,
            ) = row
            # `nudge_exhausted` means the queue stopped asking, not that the
            # proposal was resolved. review() and discard() both accept it, so
            # apply() must too -- otherwise an un-answered proposal can be
            # listed and thrown away but never accepted, which is a worse
            # half-state than not surfacing it at all.
            if status == "applying":
                # Left behind by a crash between the memory write and the
                # staging update. Decide from the store, not from the status:
                # if the memory is there the apply SUCCEEDED and only the
                # bookkeeping is missing, and rejecting it strands the proposal
                # permanently -- nothing else recovers this state.
                existing = _applied_memory_id(conn, proposal_id)
                if existing is None and not _claim_is_stale(claimed_at, now_iso):
                    # No memory yet, and the claim is still fresh -- an apply
                    # is genuinely in flight, not crashed. Taking it over
                    # would enqueue a second write, the duplicate this whole
                    # service exists to avoid.
                    conn.execute("ROLLBACK")
                    return {
                        "status": "error",
                        "error": f"proposal {proposal_id} is already applying",
                    }
                if existing is not None:
                    conn.execute(
                        "UPDATE distill_staging SET status = 'applied', "
                        "applied_memory_id = ?, reviewed_at = ?, updated_at = ? "
                        "WHERE id = ?",
                        (existing, now_iso, now_iso, proposal_id),
                    )
                    conn.execute("COMMIT")
                    return {
                        "status": "success",
                        "memory_id": existing,
                        "proposal_id": proposal_id,
                        "recovered": True,
                    }
                # No memory, so the write never landed and this is retryable.
                # Fall through and re-claim it.
                status = "pending"
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
    heartbeat = asyncio.create_task(_heartbeat_claim(memory, proposal_id))
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
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat

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
# A staged proposal nobody is told about is a proposal nobody reviews, so the
# connected agent is asked through the same response-injection channel
# `marm_compaction` uses, rather than a second mechanism.
#
# The expiry sweep lives here because the claim already takes the write lock and
# already walks the table; a separate scheduler would duplicate that work.


#: Longest neighbour rendered in a review prompt. The proposal itself is capped
#: at 240 characters when it is extracted; an unbounded neighbour beside it is
#: what let one variable field crowd out the other.
_NEIGHBOUR_CHARS = 400


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
    # The proposal comes FIRST of the variable-length parts, and the neighbour
    # is bounded. `_truncate` keeps the prefix, and `neighbour_content` has no
    # length constraint in the database while the write path accepts 10,000
    # characters -- so with the neighbour above it, a long enough neighbour kept
    # the apply/discard instructions and cut away the very text under review.
    lines += [
        f"expires: {expires_at}",
        f"nudge: {nudges + 1}",
        "",
        "Proposal:",
        f"  {content}",
    ]
    if verdict != "new":
        lines += [
            "",
            f"closest stored memory (cosine {cosine:.3f}):",
            f"  {_truncate(neighbour, _NEIGHBOUR_CHARS) if neighbour else '(unavailable)'}",
            "A `near` verdict is why this needs you: an encoder cannot tell "
            "whether this refines the proposal above or contradicts it.",
        ]
    lines += [
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
                # `nudge_exhausted` expires too: the queue stopped ASKING
                # about it, which is not the same as it being resolved. Left
                # out, an expired one is hidden by review() and never swept,
                # so the staging table grows without bound.
                "UPDATE distill_staging SET status = 'stale', updated_at = ? "
                "WHERE status IN ('pending', 'nudge_exhausted') AND expires_at <= ?",
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
