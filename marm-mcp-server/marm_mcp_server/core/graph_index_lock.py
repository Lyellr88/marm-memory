import asyncio
import os
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Optional, TypeVar

import structlog

from ..config import settings
from . import lease_lock

logger = structlog.get_logger(__name__)

T = TypeVar("T")

_TABLE = "graph_index_lock"

_inflight: set[asyncio.Task] = set()


class GraphIndexBusy(RuntimeError):
    """Another index is running. Carries the holder for the error message.

    The message reaches API responses, so it names only what kind of work holds
    the gate. A purpose carries the repository root ("auto_index:C:\\...") and
    that path has no business leaving the machine over an HTTP tool call.
    """

    def __init__(self, purpose: Optional[str] = None) -> None:
        self.holder_purpose = purpose
        kind = purpose.split(":", 1)[0] if purpose else ""
        detail = f" (held by: {kind})" if kind else ""
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


def _gated_call(
    purpose: str,
    ttl_seconds: int,
    fn: Callable[..., T],
    args: tuple,
    kwargs: dict,
) -> T:
    with gate_sync(purpose, ttl_seconds):
        return fn(*args, **kwargs)


async def _owned_call(
    purpose: str,
    ttl_seconds: int,
    fn: Callable[..., T],
    args: tuple,
    kwargs: dict,
) -> T:
    """Acquire, call, and release, all inside one thread.

    The acquire and the release have to sit on the same side of the thread
    boundary as the call. Holding the lease from the event loop meant a
    cancellation delivered directly to this coroutine, which is what loop
    teardown does to every pending task, unwound the release while the engine
    thread was still writing, handing the gate to the other transport mid-index.
    """
    return await asyncio.to_thread(_gated_call, purpose, ttl_seconds, fn, args, kwargs)


def _forget(task: asyncio.Task) -> None:
    _inflight.discard(task)
    if not task.cancelled():
        task.exception()


async def run_exclusive(
    purpose: str,
    fn: Callable[..., T],
    *args: Any,
    ttl_seconds: Optional[int] = None,
    **kwargs: Any,
) -> T:
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
