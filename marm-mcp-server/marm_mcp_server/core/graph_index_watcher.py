"""Cross-platform filesystem watcher adapter for the graph auto-index worker.

Pure delivery: reports "something changed under this root" to the owning event
loop. It has no opinion about git, source state, durable baselines, or whether
a change matters -- that judgment belongs to GraphIndexWorker. This module must
never import graph_supervisor, tool_router, runtime_flags, or a database class;
doing so would make it a second indexing worker instead of a delivery mechanism.
"""

import asyncio
from typing import Callable, Optional

import structlog
from watchdog.events import (
    EVENT_TYPE_CLOSED,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_DELETED,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_MOVED,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver, ObservedWatch

logger = structlog.get_logger(__name__)

Callback = Callable[[str], None]

# Linux's inotify backend also emits "opened" and "closed_no_write" for a
# plain read, with no content change. Forwarding those would make the graph
# engine's own read of source files while indexing re-trigger itself: a
# non-git root has no signature check, so any watcher wake reindexes it
# unconditionally (see _evaluate in graph_index_worker.py).
_CHANGE_EVENT_TYPES = frozenset(
    {
        EVENT_TYPE_CREATED,
        EVENT_TYPE_MODIFIED,
        EVENT_TYPE_DELETED,
        EVENT_TYPE_MOVED,
        EVENT_TYPE_CLOSED,
    }
)


class _RootHandler(FileSystemEventHandler):
    """Forwards every event under one watched root back to the owning loop."""

    def __init__(
        self, root: str, loop: asyncio.AbstractEventLoop, callback: Callback
    ) -> None:
        self._root = root
        self._loop = loop
        self._callback = callback

    def on_any_event(self, event: FileSystemEvent) -> None:
        # Runs on watchdog's own thread. call_soon_threadsafe is the only safe
        # way to reach the owning loop from here; touching worker state
        # directly from this thread would race the coordinator's own reads.
        if event.event_type not in _CHANGE_EVENT_TYPES:
            return
        try:
            self._loop.call_soon_threadsafe(self._callback, self._root)
        except RuntimeError:
            # The loop is already closed (a shutdown race). Nothing to notify.
            pass


class GraphIndexWatcher:
    """One process-wide observer, multiplexed per watched root.

    watch() failing, for one root or for the whole process, is an expected
    outcome (network shares, containers, inotify limits) and not an error: the
    caller falls back to reconciliation. Nothing here decides that fallback
    cadence; it only reports what watching itself could or could not do.
    """

    def __init__(self) -> None:
        self._observer: Optional[BaseObserver] = None
        self._watches: dict[str, ObservedWatch] = {}
        self._globally_unavailable = False

    @property
    def available(self) -> bool:
        return not self._globally_unavailable

    def healthy(self) -> bool:
        """False only for an observer that started and then died -- not for
        one that was never created, or was deliberately stopped, since both
        of those already read as `_observer is None` and are not failures.
        The caller decides what a dead observer means for the roots relying
        on it; this only reports the thread's own state."""
        return self._observer is None or self._observer.is_alive()

    def _ensure_observer(self) -> Optional[BaseObserver]:
        if self._observer is not None:
            return self._observer
        try:
            observer = Observer()
            observer.start()
        except Exception as exc:
            self._globally_unavailable = True
            logger.warning("graph_index_watcher.unavailable", error=str(exc))
            return None
        self._observer = observer
        return observer

    def watch(self, root: str, callback: Callback) -> bool:
        """Start watching `root`. Returns whether watching is now active.

        False means the caller should rely on reconciliation alone for this
        root -- an unsupported filesystem, a permissions error, a watch-count
        limit, or (if `available` is also False) no working observer at all.
        """
        if root in self._watches:
            return True
        if self._globally_unavailable:
            return False
        loop = asyncio.get_running_loop()
        observer = self._ensure_observer()
        if observer is None:
            return False
        handler = _RootHandler(root, loop, callback)
        try:
            watch = observer.schedule(handler, root, recursive=True)
        except Exception as exc:
            logger.warning(
                "graph_index_watcher.watch_failed", root=root, error=str(exc)
            )
            return False
        self._watches[root] = watch
        return True

    def unwatch(self, root: str) -> None:
        watch = self._watches.pop(root, None)
        if watch is None or self._observer is None:
            return
        try:
            self._observer.unschedule(watch)
        except Exception as exc:
            logger.warning(
                "graph_index_watcher.unwatch_failed", root=root, error=str(exc)
            )

    def stop(self) -> None:
        """Tear down the observer thread entirely. Safe to call repeatedly;
        a later watch() call recreates it lazily."""
        observer = self._observer
        self._observer = None
        self._watches.clear()
        if observer is None:
            return
        try:
            observer.stop()
            observer.join(timeout=5)
        except Exception as exc:
            logger.warning("graph_index_watcher.stop_failed", error=str(exc))
