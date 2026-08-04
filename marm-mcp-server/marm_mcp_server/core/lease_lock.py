"""Cross-process mutual exclusion on a leased row in the memory database.

Extracted verbatim from concept_build_lock.py, which is shipped and reviewed
concurrency code, and parameterized by table so the code index can reuse it
without a second copy. Two callers, two tables, one implementation:
concept_build_lock guards the concept database, graph_index_lock guards the code
index.

A lease rather than a plain lock: it expires so a killed process cannot wedge
the subsystem forever, and it is heartbeat-renewed so the TTL bounds how long a
*crashed* holder blocks others rather than how long real work is allowed to take.
"""

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, NamedTuple, Optional

import structlog

logger = structlog.get_logger(__name__)

# Table names are interpolated into SQL, so they may only come from this map.
# The values are structlog event prefixes, pinned per table rather than derived:
# the concept lock's events shipped as "concept_lock.*" and renaming them would
# break anything already watching for them.
_LOG_NAMES = {
    "concept_build_lock": "concept_lock",
    "graph_index_lock": "graph_index_lock",
}


class Lease(NamedTuple):
    """A held lock, plus the flag that says we stopped holding it.

    `lost` is a threading.Event rather than an asyncio one because the work it
    interrupts runs in a worker thread, where an asyncio primitive cannot be
    read safely.
    """

    holder: str
    lost: threading.Event


def _table(name: str) -> str:
    if name not in _LOG_NAMES:
        raise ValueError(f"unknown lease table: {name!r}")
    return name


def log_name(table: str) -> str:
    return _LOG_NAMES[_table(table)]


def _connection() -> Any:
    """Resolved on use: this module is reached from endpoints and from the
    workers, and core.memory is heavy to bind at import time."""
    from .memory import memory

    return memory.get_connection()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def try_acquire(table: str, holder: str, purpose: str, ttl_seconds: int) -> bool:
    """Take the lock if it is free or the current holder's lease has expired."""
    table = _table(table)
    now = _now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                f"SELECT holder, purpose, expires_at FROM {table} WHERE id = 1"
            ).fetchone()
            if row is not None and row[2] > now.isoformat():
                conn.execute("COMMIT")
                return False
            if row is not None:
                logger.info(f"{_LOG_NAMES[table]}.reclaimed_expired", previous=row[1])
            conn.execute(
                f"""
                INSERT INTO {table}
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


def renew(table: str, holder: str, ttl_seconds: int) -> bool:
    """Push our own expiry back. False means we no longer hold it.

    Without this the lock is a deadline rather than a lock: work that outlives
    its TTL gets overtaken by the next process, which is the collision the lock
    exists to prevent.
    """
    table = _table(table)
    now = _now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    with _connection() as conn:
        cursor = conn.execute(
            f"UPDATE {table} SET expires_at = ? "
            "WHERE id = 1 AND holder = ? AND expires_at > ?",
            (expires_at, holder, now.isoformat()),
        )
    return bool(cursor.rowcount > 0)


def release(table: str, holder: str) -> bool:
    """Release only our own hold. A lease that already expired and was taken by
    someone else must not be deleted out from under them."""
    table = _table(table)
    with _connection() as conn:
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE id = 1 AND holder = ?", (holder,)
        )
    return bool(cursor.rowcount > 0)


def current_holder(table: str) -> Optional[tuple[str, str]]:
    """(purpose, expires_at) of a live hold, or None."""
    table = _table(table)
    with _connection() as conn:
        row = conn.execute(
            f"SELECT purpose, expires_at FROM {table} WHERE id = 1"
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


def keep_alive(
    *,
    lease: Lease,
    purpose: str,
    ttl_seconds: int,
    log_name: str,
    renew_fn: Callable[[str, int], bool],
) -> Any:
    """The heartbeat coroutine. Returns it uncalled; the caller owns the task.

    `renew_fn` is passed in rather than called directly here so each facade
    module's own `renew` is the one that runs, which keeps it patchable in
    tests and keeps the table binding in one place.
    """
    import asyncio

    async def _keep_alive() -> None:
        interval = heartbeat_interval(ttl_seconds)
        loop = asyncio.get_running_loop()
        last_renewed = loop.time()
        while True:
            await asyncio.sleep(interval)
            try:
                # A renewal that keeps failing is indistinguishable from one
                # that was refused: either way the lease runs out on its own
                # clock and someone else can take the resource. Give up at the
                # TTL rather than logging warnings while still writing.
                if loop.time() - last_renewed >= ttl_seconds:
                    logger.error(f"{log_name}.lost", purpose=purpose, reason="stale")
                    lease.lost.set()
                    return
                if not await asyncio.to_thread(renew_fn, lease.holder, ttl_seconds):
                    # Only reachable if this process was stalled for longer
                    # than the whole TTL. Another process owns the resource
                    # now, so raise the flag: the work cannot be killed from
                    # here, but it can be asked to stop at its next safe point
                    # instead of writing alongside the new owner.
                    logger.error(f"{log_name}.lost", purpose=purpose)
                    lease.lost.set()
                    return
                last_renewed = loop.time()
            except Exception as exc:
                logger.warning(f"{log_name}.renew_failed", error=str(exc))

    return _keep_alive()
