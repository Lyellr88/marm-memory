"""How often each memory is recalled, recorded off the recall path.

A count that is late or lost costs nothing; a recall that waits on one would,
so writes are queued to one background thread and failures are only logged.
The queue is bounded: while the store cannot keep up, counts are dropped
rather than held.
"""

import asyncio
import concurrent.futures
import threading
from datetime import datetime, timezone
from typing import Iterable

import structlog

logger = structlog.get_logger(__name__)

_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="marm-usage"
)
_pending: set[concurrent.futures.Future] = set()
_pending_lock = threading.Lock()
#: Count jobs allowed to wait for the store; beyond this a recall goes uncounted.
MAX_PENDING = 64
_dropped = 0


def _increment(memory_ids: list[str], at: str) -> None:
    from .memory import memory

    with memory.get_connection() as conn:
        conn.executemany(
            "INSERT INTO memory_usage (memory_id, recall_count, last_recalled_at) "
            "VALUES (?, 1, ?) ON CONFLICT(memory_id) DO UPDATE SET "
            "recall_count = recall_count + 1, "
            # Another process may write later with an earlier time.
            "last_recalled_at = MAX(COALESCE(last_recalled_at, ''), "
            "excluded.last_recalled_at)",
            [(memory_id, at) for memory_id in memory_ids],
        )


def _record(memory_ids: list[str], at: str) -> None:
    try:
        _increment(memory_ids, at)
    except Exception as exc:
        logger.warning("memory_usage.write_failed", error=str(exc))


def record_recalled(memory_ids: Iterable[object]) -> None:
    """Count one recall of each returned memory, without waiting for it."""
    global _dropped
    ids = list(dict.fromkeys(i for i in memory_ids if isinstance(i, str) and i))
    if not ids:
        return
    dropped = recovered = 0
    with _pending_lock:
        if len(_pending) >= MAX_PENDING:
            _dropped += 1
            dropped = _dropped
            future = None
        else:
            recovered, _dropped = _dropped, 0
            future = _executor.submit(
                _record, ids, datetime.now(timezone.utc).isoformat()
            )
            _pending.add(future)
    if recovered:
        logger.info("memory_usage.recovered", dropped=recovered)
    if future is None:
        # Once per overload and then sparingly: a stalled store must not also
        # flood the log.
        if dropped == 1 or dropped % 100 == 0:
            logger.warning("memory_usage.dropped", dropped=dropped, pending=MAX_PENDING)
        return
    future.add_done_callback(_forget)


def _forget(future: concurrent.futures.Future) -> None:
    with _pending_lock:
        _pending.discard(future)


async def drain() -> None:
    """Wait for queued counts; for tests and shutdown."""
    with _pending_lock:
        waiting = list(_pending)
    if waiting:
        await asyncio.to_thread(concurrent.futures.wait, waiting)
        # wait() returns before done callbacks run, so _forget may not have yet.
        with _pending_lock:
            _pending.difference_update(waiting)
