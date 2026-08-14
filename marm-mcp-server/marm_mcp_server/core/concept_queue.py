"""Durable outbox for concept indexing.

The queue lives in the memory database so `enqueue` can run inside the same
transaction as the memories INSERT: a memory cannot be stored without its
indexing task, and a rolled-back write leaves no orphan task. Concepts still
live in their own database; only the task list is here.

Claiming is lease-based rather than lock-based. `_concept_build_lock` in
endpoints/concepts.py is an asyncio.Lock and therefore in-process only, while
an HTTP server and a STDIO session are two processes sharing one memory DB.
The lease in this table is the only thing that stops both from claiming the
same task, and it is also what makes a killed worker recoverable: an expired
lease is reclaimed rather than failed, so a crash costs no attempts.
"""

import sqlite3
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple, Optional

from ..config.settings import (
    CONCEPT_INDEX_DEBOUNCE_SECONDS,
    CONCEPT_INDEX_LEASE_SECONDS,
    CONCEPT_INDEX_MAX_ATTEMPTS,
)

# SQLite's default parameter ceiling is 999. A full-corpus build settles far
# more ids than that in one call.
_DELETE_CHUNK = 500


class ClaimedTask(NamedTuple):
    memory_id: str
    content_hash: str
    lease_token: str


def _connection() -> Any:
    """Resolved on use, not at import: core.memory imports memory_ops, which
    imports this module, so binding the singleton at module level would be a
    cycle."""
    from .memory import memory

    return memory.get_connection()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(conn: sqlite3.Connection, memory_id: str, content_hash: str) -> None:
    """Queue a memory for indexing on the caller's own connection, inside the
    caller's own transaction.

    An upsert, not an insert-or-ignore. A merge reuses an existing memory_id
    with new content and a new hash, so an already-queued row must take the
    new hash and return to pending. Dedup on memory_id alone would treat
    merged content as already indexed and it would never be extracted.
    """
    conn.execute(
        """
        INSERT INTO concept_index_queue
            (memory_id, content_hash, enqueued_at, state, attempts)
        VALUES (?, ?, ?, 'pending', 0)
        ON CONFLICT(memory_id) DO UPDATE SET
            content_hash = excluded.content_hash,
            enqueued_at  = excluded.enqueued_at,
            state        = 'pending',
            lease_token  = NULL,
            leased_until = NULL,
            attempts     = 0,
            last_error   = NULL
        """,
        (memory_id, content_hash, _now().isoformat()),
    )


def dequeue(conn: sqlite3.Connection, memory_ids: Iterable[str]) -> None:
    """Drop tasks for memories that no longer exist, on the caller's
    connection. The FK cascade would usually cover this, but it only fires
    when foreign keys are enforced on that specific connection, so the delete
    is explicit."""
    ids = list(memory_ids)
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"DELETE FROM concept_index_queue WHERE memory_id IN ({placeholders})", ids
    )


def claim(limit: int) -> list[ClaimedTask]:
    """Take ownership of up to `limit` ready tasks.

    Select and update run in one BEGIN IMMEDIATE so two workers cannot read
    the same rows before either writes. Parked rows are never returned.

    leased_until means "not claimable before this" in both live states, which
    is what lets one predicate cover both cases: a leased row is owned until
    it expires, and a row that just failed is backing off until its retry is
    due. A fresh enqueue clears it, so new content is never delayed.
    """
    if limit < 1:
        return []
    now = _now()
    token = uuid.uuid4().hex
    leased_until = now + timedelta(seconds=CONCEPT_INDEX_LEASE_SECONDS)

    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(
                """
                SELECT memory_id, content_hash FROM concept_index_queue
                WHERE state IN ('pending', 'leased')
                  AND (leased_until IS NULL OR leased_until <= ?)
                ORDER BY enqueued_at
                LIMIT ?
                """,
                (now.isoformat(), limit),
            ).fetchall()
            if not rows:
                conn.execute("COMMIT")
                return []
            claimed_ids = [row[0] for row in rows]
            placeholders = ",".join("?" * len(claimed_ids))
            conn.execute(
                f"""
                UPDATE concept_index_queue
                SET state = 'leased', lease_token = ?, leased_until = ?
                WHERE memory_id IN ({placeholders})
                """,
                [token, leased_until.isoformat(), *claimed_ids],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    return [ClaimedTask(row[0], row[1], token) for row in rows]


def renew(memory_ids: Iterable[str], lease_token: str, ttl_seconds: int) -> int:
    """Push back the expiry on tasks we still hold.

    The build lock alone is not enough. These leases run on the same clock, so
    an extraction that outlives the TTL would let another process reclaim the
    very memories being worked on and extract them a second time.
    """
    ids = list(memory_ids)
    if not ids:
        return 0
    now = _now()
    leased_until = (now + timedelta(seconds=ttl_seconds)).isoformat()
    placeholders = ",".join("?" * len(ids))
    with _connection() as conn:
        cursor = conn.execute(
            f"UPDATE concept_index_queue SET leased_until = ? "
            f"WHERE memory_id IN ({placeholders}) AND lease_token = ?",
            [leased_until, *ids, lease_token],
        )
    return max(int(cursor.rowcount), 0)


@asynccontextmanager
async def keep_claimed(
    tasks: "list[ClaimedTask]", ttl_seconds: int
) -> AsyncIterator[None]:
    """Hold a batch's leases for as long as the body runs."""
    import asyncio

    from .concept_build_lock import heartbeat_interval

    if not tasks:
        yield
        return
    memory_ids = [task.memory_id for task in tasks]
    token = tasks[0].lease_token

    async def _keep_alive() -> None:
        interval = heartbeat_interval(ttl_seconds)
        while True:
            await asyncio.sleep(interval)
            try:
                await asyncio.to_thread(renew, memory_ids, token, ttl_seconds)
            except Exception:
                # A missed renewal is recoverable: the task returns to the
                # queue and is picked up again. Failing the batch is not.
                pass

    beat = asyncio.create_task(_keep_alive())
    try:
        yield
    finally:
        beat.cancel()
        try:
            await beat
        except (asyncio.CancelledError, Exception):
            pass


def complete(memory_id: str, lease_token: str, content_hash: str) -> bool:
    """Retire a finished task. Returns whether it was actually retired.

    Matched on the hash as well as the token: a memory merged while its
    extraction was running was re-enqueued with new content, and deleting that
    row would drop the merged text from the graph permanently.
    """
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM concept_index_queue "
            "WHERE memory_id = ? AND lease_token = ? AND content_hash = ?",
            (memory_id, lease_token, content_hash),
        )
    return bool(cursor.rowcount > 0)


def drop(memory_id: str, lease_token: str) -> bool:
    """Retire a task whose memory is gone, regardless of hash. Used for
    vanished memories, where there is no current content to match against."""
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM concept_index_queue WHERE memory_id = ? AND lease_token = ?",
            (memory_id, lease_token),
        )
    return bool(cursor.rowcount > 0)


def fail(memory_id: str, lease_token: str, error: str) -> bool:
    """Record a failed attempt, release the lease, and hold the task back.

    The backoff is not optional. The worker drains continuously until the
    queue is empty, so a task returned straight to pending would be re-claimed
    by the very next iteration and burn every attempt in milliseconds. One
    debounce interval per attempt spreads the retries over real time instead.

    A task that reaches CONCEPT_INDEX_MAX_ATTEMPTS is parked rather than
    deleted: the queue keeps moving, and the row stays as evidence of what
    could not be indexed and why.
    """
    now = _now()
    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT attempts FROM concept_index_queue "
                "WHERE memory_id = ? AND lease_token = ?",
                (memory_id, lease_token),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return False
            attempts = row[0] + 1
            parked = attempts >= CONCEPT_INDEX_MAX_ATTEMPTS
            retry_at = now + timedelta(
                seconds=CONCEPT_INDEX_DEBOUNCE_SECONDS * attempts
            )
            conn.execute(
                """
                UPDATE concept_index_queue
                SET attempts = ?, last_error = ?, lease_token = NULL,
                    leased_until = ?, state = ?
                WHERE memory_id = ? AND lease_token = ?
                """,
                (
                    attempts,
                    error[:500],
                    None if parked else retry_at.isoformat(),
                    "parked" if parked else "pending",
                    memory_id,
                    lease_token,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return True


def retire_indexed(memory_ids: Iterable[str], queued_before: str) -> int:
    """Drop tasks a completed build has already covered.

    Called after a build with the ids it actually indexed, and the timestamp
    the build started. `queued_before` is what makes this safe without
    comparing content: a merge, replace, or fresh write during the build
    re-stamps enqueued_at to now, so those rows sort after the cutoff and
    survive. A memory whose extraction failed is not in memory_ids at all, so
    its retry is never dropped. Leased rows belong to another worker.

    Without this, the forced rebuild in v2.36.0 would leave the whole corpus
    queued behind a build that just indexed it, and the worker would extract
    every memory a second time.
    """
    ids = list(memory_ids)
    if not ids:
        return 0
    total = 0
    with _connection() as conn:
        for start in range(0, len(ids), _DELETE_CHUNK):
            chunk = ids[start : start + _DELETE_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            cursor = conn.execute(
                f"DELETE FROM concept_index_queue WHERE memory_id IN ({placeholders}) "
                "AND state != 'leased' AND enqueued_at <= ?",
                [*chunk, queued_before],
            )
            total += max(cursor.rowcount, 0)
    return total


def current_hashes(memory_ids: Iterable[str]) -> dict[str, Optional[str]]:
    """Read each memory's live content_hash, for the worker's post-write
    ownership check. A missing key means the memory no longer exists."""
    ids = list(memory_ids)
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    with _connection() as conn:
        rows = conn.execute(
            f"SELECT id, content_hash FROM memories WHERE id IN ({placeholders})", ids
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def counts() -> dict[str, int]:
    """Queue depth for status reporting.

    Two numbers rather than one: a growing pending count means indexing is
    behind or switched off, while a non-zero parked count means specific
    memories gave up and will not be retried without help. They call for
    different responses, so they are not summed.
    """
    with _connection() as conn:
        rows = conn.execute(
            "SELECT state, COUNT(*) FROM concept_index_queue GROUP BY state"
        ).fetchall()
    by_state = {row[0]: int(row[1]) for row in rows}
    return {
        "pending": by_state.get("pending", 0) + by_state.get("leased", 0),
        "parked": by_state.get("parked", 0),
    }
