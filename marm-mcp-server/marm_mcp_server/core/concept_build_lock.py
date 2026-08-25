import asyncio
import os
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Callable, Optional, TypeVar

import structlog

from . import lease_lock
from .lease_lock import Lease as BuildLease
from .lease_lock import heartbeat_interval

logger = structlog.get_logger(__name__)

_TABLE = "concept_build_lock"

T = TypeVar("T")

_inflight: set[asyncio.Task] = set()

MANUAL_BUILD_LOCK_SECONDS = 60

__all__ = [
    "MANUAL_BUILD_LOCK_SECONDS",
    "BuildLease",
    "ConceptBuildBusy",
    "concept_build_lock",
    "current_holder",
    "gate_sync",
    "heartbeat_interval",
    "release",
    "renew",
    "run_exclusive",
    "try_acquire",
]


class ConceptBuildBusy(RuntimeError):
    """Another process is writing the concept graph."""


def try_acquire(holder: str, purpose: str, ttl_seconds: int) -> bool:
    return lease_lock.try_acquire(_TABLE, holder, purpose, ttl_seconds)


def renew(holder: str, ttl_seconds: int) -> bool:
    return lease_lock.renew(_TABLE, holder, ttl_seconds)


def release(holder: str) -> bool:
    return lease_lock.release(_TABLE, holder)


def current_holder() -> Optional[tuple[str, str]]:
    return lease_lock.current_holder(_TABLE)


@contextmanager
def gate_sync(
    purpose: str, ttl_seconds: int, lease_lost: threading.Event | None = None
) -> Any:
    """Hold the concept lease for work running in a plain worker thread."""
    holder = f"{os.getpid()}:{uuid.uuid4().hex}"
    if not try_acquire(holder, purpose, ttl_seconds):
        raise ConceptBuildBusy("another process is writing the concept graph")

    done = threading.Event()
    lost = lease_lost or threading.Event()

    def _beat() -> None:
        interval = heartbeat_interval(ttl_seconds)
        while not done.wait(interval):
            try:
                if not renew(holder, ttl_seconds):
                    logger.error("concept_lock.lost", purpose=purpose)
                    lost.set()
                    return
            except Exception as exc:
                logger.warning("concept_lock.renew_failed", error=str(exc))

    beat = threading.Thread(target=_beat, daemon=True)
    beat.start()
    try:
        yield holder
    finally:
        done.set()
        try:
            release(holder)
        except Exception as exc:
            logger.warning("concept_lock.release_failed", error=str(exc))


def _gated_call(
    purpose: str,
    ttl_seconds: int,
    fn: Callable[..., T],
    args: tuple,
    kwargs: dict,
    lease_lost: threading.Event | None,
) -> T:
    with gate_sync(purpose, ttl_seconds, lease_lost):
        return fn(*args, **kwargs)


async def _owned_call(
    purpose: str,
    ttl_seconds: int,
    fn: Callable[..., T],
    args: tuple,
    kwargs: dict,
    lease_lost: threading.Event | None,
) -> T:
    return await asyncio.to_thread(
        _gated_call, purpose, ttl_seconds, fn, args, kwargs, lease_lost
    )


def _forget(task: asyncio.Task) -> None:
    _inflight.discard(task)
    if not task.cancelled():
        task.exception()


async def run_exclusive(
    purpose: str,
    fn: Callable[..., T],
    *args: Any,
    ttl_seconds: int,
    lease_lost: threading.Event | None = None,
    **kwargs: Any,
) -> T:
    """Run one concept graph mutation without releasing its lease on cancellation."""
    task = asyncio.create_task(
        _owned_call(purpose, ttl_seconds, fn, args, kwargs, lease_lost)
    )
    _inflight.add(task)
    task.add_done_callback(_forget)
    return await asyncio.shield(task)


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
            logger.warning("concept_lock.release_failed", error=str(exc))
