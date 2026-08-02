"""Cross-process mutual exclusion for concept graph writes.

endpoints/concepts.py holds an asyncio.Lock, which serializes builds inside one
interpreter and nothing beyond it. HTTP and STDIO are two processes over one
memory database, and every process now runs an indexing worker, so the manual
build and somebody else's worker can reach the concept database at the same
time. The manual build is the dangerous half: a rebuild backs up and drops the
graph tables, which is exactly what the v2.36.0 upgrade asks every user to run.

The lock is one row in the memory database, held for the duration of a build
and released after. It expires so a killed process cannot wedge indexing
forever, and both holders take it before the in-process lock so the two can
never be acquired in opposite orders.
"""

import os
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, NamedTuple, Optional

import structlog

logger = structlog.get_logger(__name__)

# A full-corpus rebuild is a long operation and must not have the lock pulled
# out from under it mid-run. This only decides how long a *crashed* holder
# blocks the next build, so it is generous on purpose.
MANUAL_BUILD_LOCK_SECONDS = 3600


class ConceptBuildBusy(RuntimeError):
    """Another process is writing the concept graph."""


class BuildLease(NamedTuple):
    """A held lock, plus the flag that says we stopped holding it.

    `lost` is a threading.Event rather than an asyncio one because the work it
    interrupts runs in a worker thread, where an asyncio primitive cannot be
    read safely.
    """

    holder: str
    lost: threading.Event


def _connection() -> Any:
    """Resolved on use: this module is reached from endpoints and from the
    worker, and core.memory is heavy to bind at import time."""
    from .memory import memory

    return memory.get_connection()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def try_acquire(holder: str, purpose: str, ttl_seconds: int) -> bool:
    """Take the lock if it is free or the current holder's lease has expired."""
    now = _now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT holder, purpose, expires_at FROM concept_build_lock WHERE id = 1"
            ).fetchone()
            if row is not None and row[2] > now.isoformat():
                conn.execute("COMMIT")
                return False
            if row is not None:
                logger.info("concept_lock.reclaimed_expired", previous=row[1])
            conn.execute(
                """
                INSERT INTO concept_build_lock
                    (id, holder, purpose, acquired_at, expires_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    holder = excluded.holder,
                    purpose = excluded.purpose,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                """,
                (holder, purpose, now.isoformat(), expires_at),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return True


def renew(holder: str, ttl_seconds: int) -> bool:
    """Push our own expiry back. False means we no longer hold it.

    Without this the lock is a deadline rather than a lock: a batch or a
    rebuild that outlives its TTL gets overtaken by the next process, which is
    the collision the lock exists to prevent.
    """
    now = _now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    with _connection() as conn:
        cursor = conn.execute(
            "UPDATE concept_build_lock SET expires_at = ? "
            "WHERE id = 1 AND holder = ? AND expires_at > ?",
            (expires_at, holder, now.isoformat()),
        )
    return bool(cursor.rowcount > 0)


def release(holder: str) -> bool:
    """Release only our own hold. A lease that already expired and was taken by
    someone else must not be deleted out from under them."""
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM concept_build_lock WHERE id = 1 AND holder = ?", (holder,)
        )
    return bool(cursor.rowcount > 0)


def current_holder() -> Optional[tuple[str, str]]:
    """(purpose, expires_at) of a live hold, or None."""
    with _connection() as conn:
        row = conn.execute(
            "SELECT purpose, expires_at FROM concept_build_lock WHERE id = 1"
        ).fetchone()
    if row is None or row[1] <= _now().isoformat():
        return None
    return (row[0], row[1])


def heartbeat_interval(ttl_seconds: float) -> float:
    """Renew well inside the TTL so one slow renewal cannot lose the lock.

    Floored so a deliberately tiny lease setting cannot turn the heartbeat
    into a busy loop against SQLite.
    """
    return max(0.5, ttl_seconds / 3)


@asynccontextmanager
async def concept_build_lock(
    purpose: str, ttl_seconds: int
) -> AsyncIterator[BuildLease]:
    """Hold the graph for one operation, or raise ConceptBuildBusy.

    Renewed by a heartbeat for as long as the body runs, so the TTL bounds how
    long a *crashed* holder blocks others rather than how long a legitimate
    build is allowed to take. A full rebuild has no bounded runtime and a
    batch's runtime depends on the corpus, so a fixed expiry would eventually
    be crossed by real work.

    Never waits to acquire. Both callers have something better to do than
    block: the worker skips the cycle and keeps its tasks queued, and the
    manual build tells the user who has it.
    """
    import asyncio

    holder = f"{os.getpid()}:{uuid.uuid4().hex}"
    if not await asyncio.to_thread(try_acquire, holder, purpose, ttl_seconds):
        raise ConceptBuildBusy("another process is writing the concept graph")

    lease = BuildLease(holder=holder, lost=threading.Event())

    async def _keep_alive() -> None:
        interval = heartbeat_interval(ttl_seconds)
        while True:
            await asyncio.sleep(interval)
            try:
                if not await asyncio.to_thread(renew, holder, ttl_seconds):
                    # Only reachable if this process was stalled for longer
                    # than the whole TTL. Another process owns the graph now,
                    # so raise the flag: the work cannot be killed from here,
                    # but it can be asked to stop at its next safe point
                    # instead of writing alongside the new owner.
                    logger.error("concept_lock.lost", purpose=purpose)
                    lease.lost.set()
                    return
            except Exception as exc:
                logger.warning("concept_lock.renew_failed", error=str(exc))

    beat = asyncio.create_task(_keep_alive())
    try:
        yield lease
    finally:
        beat.cancel()
        try:
            await beat
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await asyncio.to_thread(release, holder)
        except Exception as exc:
            # An unreleased lock expires on its own; failing teardown here
            # would be worse than waiting it out.
            logger.warning("concept_lock.release_failed", error=str(exc))
