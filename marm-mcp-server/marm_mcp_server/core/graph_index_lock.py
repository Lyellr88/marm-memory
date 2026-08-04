"""The single gate every mutation of the engine's project store passes through.

There are four callers of the engine's `index_repository`: the HTTP tool, the
Console's async job, the STDIO tool, and the auto-index worker, plus the Console's
`delete_project`. `_project_job_lock` in endpoints/graph.py is a threading.Lock, so
it serializes the Console's jobs inside one interpreter and nothing across
processes. HTTP and STDIO are two processes with two engine children over one
shared engine store, so without this a worker in one can index the same
repository a request in the other is indexing, or delete one it is building.

The lease is the same primitive the concept graph uses (lease_lock.py), bound to
its own table: making concept extraction and code indexing mutually exclusive
would serialize two unrelated stores for no reason.

## Why this is not an `async with`

The engine call runs through `asyncio.to_thread`, and cancelling that await
cancels only the await. The thread keeps running and keeps writing. A lease
released by a `finally` tied to the awaiting task would therefore be handed to
another process while the engine is still mid-write, which is precisely the
collision the lease exists to prevent.

The concept build can be asked to stop cooperatively, because it loops over
memories and can check a flag between them. One `index_repository` call is a
single opaque round trip into the engine child: there is no safe point to
interrupt it. So the release is driven by the thread's completion instead. The
work is owned by a task that acquires, calls, and releases; callers await that
task through `asyncio.shield` and can walk away from it without collapsing the
lease. If the event loop itself dies mid-index nothing releases, and the lease
expires on its TTL. That is the one case the TTL is for.
"""

import asyncio
import os
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Optional

import structlog

from ..config import settings
from . import lease_lock
from .lease_lock import Lease

logger = structlog.get_logger(__name__)

_TABLE = "graph_index_lock"

# Tasks that own a lease right now. Held only so an orphaned index (its caller
# cancelled, or the worker stopped) is not garbage collected mid-flight.
_inflight: set[asyncio.Task] = set()


class GraphIndexBusy(RuntimeError):
    """Another index is running. Carries the holder for the error message."""

    def __init__(self, purpose: Optional[str] = None) -> None:
        self.holder_purpose = purpose
        detail = f" (held by: {purpose})" if purpose else ""
        super().__init__(f"another code index is already running{detail}")


def try_acquire(holder: str, purpose: str, ttl_seconds: int) -> bool:
    return lease_lock.try_acquire(_TABLE, holder, purpose, ttl_seconds)


def renew(holder: str, ttl_seconds: int) -> bool:
    return lease_lock.renew(_TABLE, holder, ttl_seconds)


def release(holder: str) -> bool:
    return lease_lock.release(_TABLE, holder)


def current_holder() -> Optional[tuple[str, str]]:
    return lease_lock.current_holder(_TABLE)


@contextmanager
def gate_sync(purpose: str, ttl_seconds: Optional[int] = None) -> Any:
    """The gate for a caller that already owns a plain thread of its own.

    The Console's index job is a `threading.Thread` started outside the event
    loop, so it cannot use `run_exclusive`. Here a `finally` release IS correct:
    nothing can cancel a bare thread, so the block cannot unwind while the
    engine call is still running. The heartbeat is a daemon thread for the same
    reason there is no loop to host it.
    """
    ttl = ttl_seconds or settings.GRAPH_AUTO_INDEX_LEASE_SECONDS
    holder = f"{os.getpid()}:{uuid.uuid4().hex}"
    if not try_acquire(holder, purpose, ttl):
        held = current_holder()
        raise GraphIndexBusy(held[0] if held else None)

    done = threading.Event()

    def _beat() -> None:
        interval = lease_lock.heartbeat_interval(ttl)
        while not done.wait(interval):
            try:
                if not renew(holder, ttl):
                    logger.error("graph_index_lock.lost", purpose=purpose)
                    return
            except Exception as exc:
                logger.warning("graph_index_lock.renew_failed", error=str(exc))

    beat = threading.Thread(target=_beat, daemon=True)
    beat.start()
    try:
        yield holder
    finally:
        done.set()
        try:
            release(holder)
        except Exception as exc:
            logger.warning("graph_index_lock.release_failed", error=str(exc))


async def _owned_call(
    purpose: str,
    ttl_seconds: int,
    fn: Callable[..., Any],
    args: tuple,
    kwargs: dict,
) -> Any:
    """Acquire, run the engine call in a thread, release when it returns."""
    holder = f"{os.getpid()}:{uuid.uuid4().hex}"
    if not await asyncio.to_thread(try_acquire, holder, purpose, ttl_seconds):
        held = await asyncio.to_thread(current_holder)
        raise GraphIndexBusy(held[0] if held else None)

    lease = Lease(holder=holder, lost=threading.Event())
    beat = asyncio.create_task(
        lease_lock.keep_alive(
            lease=lease,
            purpose=purpose,
            ttl_seconds=ttl_seconds,
            log_name=lease_lock.log_name(_TABLE),
            renew_fn=lambda h, t: renew(h, t),
        )
    )
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    finally:
        beat.cancel()
        try:
            await beat
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await asyncio.to_thread(release, holder)
        except Exception as exc:
            # An unreleased lease expires on its own; failing teardown here
            # would be worse than waiting it out.
            logger.warning("graph_index_lock.release_failed", error=str(exc))


def _forget(task: asyncio.Task) -> None:
    _inflight.discard(task)
    # Mark any exception retrieved. A caller that was cancelled while shielded
    # never awaits the result, and an unretrieved exception would surface as a
    # spurious "exception was never retrieved" at loop teardown.
    if not task.cancelled():
        task.exception()


async def run_exclusive(
    purpose: str,
    fn: Callable[..., Any],
    *args: Any,
    ttl_seconds: Optional[int] = None,
    **kwargs: Any,
) -> Any:
    """Run one engine store mutation under the gate. Raises GraphIndexBusy if refused.

    Indexing is the common case, but a project delete mutates the same per-project
    store and has to take the same gate: a delete that lands while a poller is
    inside index_repository is undone when that index completes and writes the
    project back.

    Never waits to acquire. Every caller has something better to do than block:
    the worker skips its cycle and recomputes the signature next time, and a
    manual call tells the user who holds it.

    Cancelling this await detaches from the result. It does not stop the index
    and it does not release the lease.
    """
    ttl = ttl_seconds or settings.GRAPH_AUTO_INDEX_LEASE_SECONDS
    task = asyncio.create_task(_owned_call(purpose, ttl, fn, args, kwargs))
    _inflight.add(task)
    task.add_done_callback(_forget)
    return await asyncio.shield(task)
