import asyncio
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from marm_graph.core.cbm_client import CbmClient

import structlog

from marm_graph.core import tool_router as R
from marm_graph.core.models import GraphIndexRequest

from ..config.settings import (
    GRAPH_AUTO_INDEX,
    GRAPH_AUTO_INDEX_DEBOUNCE_SECONDS,
    GRAPH_AUTO_INDEX_MODE,
    GRAPH_AUTO_INDEX_PROJECT_TTL,
    GRAPH_AUTO_INDEX_RECONCILE_SECONDS,
)
from . import code_link_queue, code_project_bindings, runtime_flags
from .graph_index_lock import GraphIndexBusy, run_exclusive
from .graph_index_watcher import GraphIndexWatcher
from .graph_supervisor import graph_supervisor

logger = structlog.get_logger(__name__)

_GIT_TIMEOUT_SECONDS = 15

_UNBORN_HEAD = ""

_IDLE_POLL_SECONDS = 15.0


def _git_env() -> dict[str, str]:
    """A scrubbed environment for a git call on a user-chosen repository.

    Inherited GIT_* variables belong to whatever launched the server, not to the
    repo being polled, and GIT_DIR or GIT_WORK_TREE would point our -C somewhere
    else entirely. GIT_OPTIONAL_LOCKS=0 keeps a status check from taking
    .git/index.lock and rewriting the index -- which matters even more now than
    it used to: a watcher would see that rewrite as a change and re-trigger the
    very check that caused it.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _git(root: str, *args: str) -> Optional[str]:
    """Run one git command in `root`. None means "could not tell", never "no change".

    core.fsmonitor names a program git will execute, and it is read from the
    polled repository's own config: honoring it would let any repo MARM watches
    run a program of its choosing whenever this fires.
    """
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", root, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("graph_auto_index.git_failed", root=root, error=str(exc))
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def is_git_repo(root: str) -> bool:
    return (Path(root) / ".git").exists()


def git_source_state(root: str) -> Optional[tuple[str, str]]:
    """(HEAD, content_hash) for the repo AT `root`, or None if git could not answer.

    content_hash is sensitive to the bytes that changed, not just which paths
    are dirty. It combines the diff against HEAD -- covers staged and unstaged
    changes to tracked files in one command -- with a content hash of every
    non-ignored untracked path, so a second edit to an already-dirty file, or
    a same-length edit to an untracked one, produces a new signature. Nothing
    here is logged; only the digest is ever kept.

    A None result must be treated as "no change". Re-indexing on a git error
    would turn a broken repo into a re-index on every single evaluation.

    The `.git` check is not redundant with the caller's. Git's repository
    discovery walks upward from `-C`, so on a directory that is not itself a
    repo this would report an ancestor's state: an indexed subdirectory of some
    other repo would then re-index whenever anything anywhere in that parent
    changed.
    """
    if not is_git_repo(root):
        return None
    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
            return None
        head = _UNBORN_HEAD
        unborn = True
    else:
        unborn = False

    diff_output: str
    if unborn:
        diff_cached = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--cached")
        if diff_cached is None:
            return None
        diff_unstaged = _git(root, "diff", "--no-ext-diff", "--no-textconv")
        if diff_unstaged is None:
            return None
        diff_output = diff_cached + "\x1e" + diff_unstaged
    else:
        diff_head = _git(root, "diff", "--no-ext-diff", "--no-textconv", "HEAD")
        if diff_head is None:
            return None
        diff_output = diff_head

    untracked_raw = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked_raw is None:
        return None
    fingerprints = []
    for path in untracked_raw.split("\x00"):
        if not path:
            continue
        full_path = os.path.join(root, path)
        try:
            if os.path.islink(full_path):
                target_text = os.readlink(full_path)
                digest = hashlib.sha256(
                    target_text.encode("utf-8", "surrogateescape")
                ).hexdigest()
            else:
                hasher = hashlib.sha256()
                with open(full_path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        hasher.update(chunk)
                digest = hasher.hexdigest()
        except OSError:
            continue
        fingerprints.append(f"{path}:{digest}")

    digest_input = "\x1f".join([diff_output, *sorted(fingerprints)])
    content_hash = hashlib.sha256(
        digest_input.encode("utf-8", "surrogateescape")
    ).hexdigest()
    return (head, content_hash)


def index_repository(client: "CbmClient", req: GraphIndexRequest) -> dict:
    """The callable every index path hands to the gate: index, then settle the
    durable block state before the lease is released.

    Settling it afterwards left the two blocks racing each other, because both
    transports index concurrently by design. An automatic index that fails on the
    path limit and a manual one that succeeds could release their gates in either
    order, and the loser's write won: a recovered repository stayed marked
    unindexable, silently, in both processes.

    One function rather than a rule at four call sites, because the rule is
    invisible at the call site and there is nothing to notice when it is skipped.
    """
    result: dict = R.do_index(client, req)
    root = req.repo_path
    if not root:
        return result
    if result.get("status") == "error":
        if result.get("error_code") == "windows_path_too_long":
            runtime_flags.mark_unindexable(root, "windows_path_too_long")
        return result
    runtime_flags.clear_index_blocks(root)
    graph_project = result.get("project")
    if isinstance(graph_project, str) and graph_project:
        try:
            binding_state, binding = code_project_bindings.auto_bind(
                graph_project, root
            )
            result["memory_linking"] = {"state": binding_state}
            if binding is not None:
                code_link_queue.enqueue_refresh(
                    binding.graph_project,
                    binding.memory_project,
                    binding.root_path,
                )
                result["memory_linking"]["memory_project"] = binding.memory_project
                result["memory_linking"]["refresh_queued"] = True
        except Exception as exc:
            logger.warning("code_linking.enqueue_failed", error=str(exc))
    return result


class _Watched:
    """Per-project watch state. Disposable in memory: the durable baseline
    lives in graph_watch_state, so losing this costs at most one extra
    re-index rather than a wrong "unchanged" verdict."""

    __slots__ = (
        "content_hash",
        "debounce_deadline",
        "evaluated_generation",
        "failed",
        "generation",
        "git_head",
        "is_git",
        "last_index_reason",
        "last_indexed",
        "reconcile_deadline",
        "retry_after",
        "root",
        "watch_mode",
    )

    def __init__(self, root: str) -> None:
        self.root = root
        self.is_git = is_git_repo(root)
        self.git_head: Optional[str] = None
        self.content_hash: Optional[str] = None
        self.last_indexed: Optional[str] = None
        self.last_index_reason: Optional[str] = None
        self.retry_after: float = 0.0
        self.failed = False
        self.generation = 0
        self.evaluated_generation = 0
        self.debounce_deadline: Optional[float] = None
        self.reconcile_deadline: float = float("-inf")
        self.watch_mode = "disabled"


class GraphIndexWorker:
    """Lazy singleton, mirroring ConceptIndexWorker's shape. start() and stop()
    are both idempotent."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._watcher = GraphIndexWatcher()
        self._watched: dict[str, _Watched] = {}
        self._projects_loaded_at: Optional[float] = None
        self._ticked_once = False
        self._cycles = 0
        self._indexed = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @staticmethod
    def enabled() -> bool:
        """Re-read on every wake, never cached. An off switch that needed a
        restart would not be an off switch."""
        return runtime_flags.get_bool(runtime_flags.AUTO_INDEX_GRAPH, GRAPH_AUTO_INDEX)

    @staticmethod
    def binary_present() -> bool:
        """Whether the engine binary is already downloaded.

        Auto-index is on by default, so an eager start that ignored this would
        make every fresh install pull ~269MB on first boot, including users who
        never touch a graph tool. Same check graph_supervisor uses before it
        logs the one-time download notice.
        """
        try:
            from codebase_memory_mcp import _cli

            return bool(_cli._bin_path(_cli._version()).exists())
        except Exception:
            return False

    def start(self) -> None:
        """Never raises. A worker that cannot run leaves graphs as stale as
        they are today, which is recoverable; breaking startup is not."""
        if self.running:
            return
        if not self.enabled():
            logger.info("graph_auto_index.idle", reason="auto_index_off")
        try:
            self._stop.clear()
            self._task = asyncio.get_running_loop().create_task(self._run())
            logger.info(
                "graph_auto_index.started",
                debounce_seconds=GRAPH_AUTO_INDEX_DEBOUNCE_SECONDS,
                reconcile_seconds=GRAPH_AUTO_INDEX_RECONCILE_SECONDS,
                mode=GRAPH_AUTO_INDEX_MODE,
            )
        except RuntimeError as exc:
            logger.warning("graph_auto_index.start_failed", error=str(exc))

    async def stop(self) -> None:
        """Stop scheduling, tear down any active filesystem watches, and return.

        Deliberately does not wait for an in-flight index and deliberately does
        not release its lease. The index call owns its own lease through
        run_exclusive and finishes on its own; there is no durable task to
        protect here, and the next start recomputes everything from scratch.
        """
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("graph_auto_index.stop_error", error=str(exc))
        self._watcher.stop()
        logger.info(
            "graph_auto_index.stopped", cycles=self._cycles, indexed=self._indexed
        )

    async def _run(self) -> None:
        primed = False
        while not self._stop.is_set():
            delay = self._next_wake_delay()
            if await self._wait(delay):
                return
            if not self.enabled():
                self._deactivate()
                continue
            if not primed:
                primed = True
                await self._prime_engine()
            self._cycles += 1
            try:
                await self._tick()
            except Exception as exc:
                logger.warning("graph_auto_index.cycle_failed", error=str(exc))

    def _next_wake_delay(self) -> float:
        """Seconds until the next thing needing attention: a debounce
        deadline, a reconcile deadline, or -- while disabled or with nothing
        watched yet -- a short idle poll, so a cross-process auto_on or a
        freshly-listed project is noticed promptly instead of after a full
        reconcile wait."""
        if not self.enabled():
            return min(_IDLE_POLL_SECONDS, GRAPH_AUTO_INDEX_PROJECT_TTL)
        if not self._ticked_once:
            return 0.0
        if not self._watched:
            return min(_IDLE_POLL_SECONDS, GRAPH_AUTO_INDEX_PROJECT_TTL)
        now = time.monotonic()
        live = [state for state in self._watched.values() if not state.failed]
        if not live:
            return min(_IDLE_POLL_SECONDS, GRAPH_AUTO_INDEX_PROJECT_TTL)
        idle_floor = now + min(_IDLE_POLL_SECONDS, GRAPH_AUTO_INDEX_PROJECT_TTL)
        never_evaluated = float("-inf")
        deadlines = [
            idle_floor
            if state.reconcile_deadline == never_evaluated
            else state.reconcile_deadline
            for state in live
        ]
        deadlines.extend(
            state.debounce_deadline
            for state in live
            if state.debounce_deadline is not None
        )
        return max(0.0, min(deadlines) - now)

    async def _wait(self, seconds: float) -> bool:
        """Sleep until `seconds` elapse, a wake is requested, or stopped.
        Returns whether a stop arrived."""
        stop_wait = asyncio.ensure_future(self._stop.wait())
        wake_wait = asyncio.ensure_future(self._wake.wait())
        try:
            await asyncio.wait(
                {stop_wait, wake_wait},
                timeout=max(0.0, seconds),
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (stop_wait, wake_wait):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stop_wait, wake_wait, return_exceptions=True)
        self._wake.clear()
        return self._stop.is_set()

    def wake(self) -> None:
        """Wake the coordinator promptly instead of waiting out its current
        sleep. Only reaches a coordinator in this process; a flag flipped
        from another process is still picked up on the next idle poll."""
        self._wake.set()

    async def _prime_engine(self) -> None:
        """Start the engine once, off the lifespan path, if it is already on disk.

        _ensure_started() is synchronous and can spend CBM_STARTUP_TIMEOUT (60s)
        spawning and handshaking, so it must never run inline in lifespan and
        never inside a scheduling tick.
        """
        if not self.binary_present():
            logger.info("graph_auto_index.dormant", reason="engine_binary_absent")
            return
        try:
            await asyncio.to_thread(graph_supervisor.is_available)
        except Exception as exc:
            logger.warning("graph_auto_index.prime_failed", error=str(exc))

    def _deactivate(self) -> None:
        """Stop all filesystem watching without forgetting per-project
        history, so `auto_status` still shows the last known state while
        off. Re-enrolled by _tick the moment auto-index is turned back on."""
        self._watcher.stop()
        for state in self._watched.values():
            if state.watch_mode != "disabled":
                state.watch_mode = "disabled"
                state.debounce_deadline = None

    def _recover_dead_watcher(self) -> None:
        """The one shared observer thread died after successfully starting --
        not a setup failure, which watch() already handles per root by
        falling back to reconcile_fallback. One Observer backs every root, so
        all of them lose event delivery at once here; reconciliation still
        protects correctness, but freshness silently degrades to it until
        something notices. Rebuild a fresh observer and re-enroll exactly the
        roots that were relying on the dead one, leaving alone any root
        already on reconcile_fallback for its own reason (a permission
        error, a watch-count limit) rather than retrying that every tick.
        """
        affected = [
            state
            for state in self._watched.values()
            if state.watch_mode in ("git_events", "filesystem_events")
        ]
        logger.warning(
            "graph_index_watcher.observer_died", affected_roots=len(affected)
        )
        self._watcher.stop()
        for state in affected:
            self._enroll_watch(state)

    async def _tick(self) -> None:
        self._ticked_once = True
        if not self.enabled():
            return
        if not graph_supervisor.snapshot()["available"]:
            return

        await self._refresh_projects()
        if self._watched and not self._watcher.healthy():
            self._recover_dead_watcher()
        for state in self._watched.values():
            if state.watch_mode == "disabled":
                self._enroll_watch(state)

        now = time.monotonic()
        for state in list(self._watched.values()):
            if self._stop.is_set():
                return
            if state.failed:
                continue
            due = now >= state.reconcile_deadline or (
                state.debounce_deadline is not None and now >= state.debounce_deadline
            )
            if not due:
                continue
            if await asyncio.to_thread(runtime_flags.index_block, state.root):
                if (
                    state.debounce_deadline is not None
                    and state.debounce_deadline <= now
                ):
                    state.debounce_deadline = None
                continue
            try:
                await self._evaluate(state)
            except GraphIndexBusy:
                continue
            except Exception as exc:
                logger.warning(
                    "graph_auto_index.project_failed", root=state.root, error=str(exc)
                )

    async def _refresh_projects(self) -> None:
        """Reload the watch set when its TTL expires.

        list_projects costs ~265ms and holds the engine lock, so this is cached
        rather than called every tick.

        Freshness is the load timestamp alone, never whether the watch set came
        back non-empty. An empty result is a real answer: a fresh install with no
        projects, or an install where every project is suppressed. Treating empty
        as "not loaded yet" would put list_projects back on every tick for
        exactly the users who have no indexing to do.
        """
        now = time.monotonic()
        if (
            self._projects_loaded_at is not None
            and now - self._projects_loaded_at < GRAPH_AUTO_INDEX_PROJECT_TTL
        ):
            return
        client = graph_supervisor.get_client()
        if client is None:
            return
        result = await asyncio.to_thread(
            R.do_index, client, GraphIndexRequest(action="list")
        )
        self._projects_loaded_at = now
        if result.get("status") == "error":
            return

        roots = {
            root
            for root in (
                (project or {}).get("root_path")
                for project in result.get("projects", [])
            )
            if root
        }
        for root in roots:
            if root in self._watched:
                continue
            if runtime_flags.is_watch_suppressed(root):
                continue
            state = _Watched(root)
            durable = await asyncio.to_thread(runtime_flags.get_watch_state, root)
            if durable is not None:
                state.last_indexed = durable.get("last_indexed")
                state.last_index_reason = durable.get("last_index_reason")
                stored = durable.get("last_source_state") or ""
                if durable.get("source_kind") == "git" and ":" in stored:
                    state.git_head, state.content_hash = stored.split(":", 1)
            self._watched[root] = state
            self._enroll_watch(state)
        for root in list(self._watched):
            if root not in roots or runtime_flags.is_watch_suppressed(root):
                self._detach(root)

    def _enroll_watch(self, state: _Watched) -> None:
        ok = self._watcher.watch(state.root, self._on_watch_event)
        if ok:
            state.watch_mode = "git_events" if state.is_git else "filesystem_events"
        elif self._watcher.available:
            state.watch_mode = "reconcile_fallback"
        else:
            state.watch_mode = "unavailable"

    def _on_watch_event(self, root: str) -> None:
        """The watcher's callback, invoked on this process's event loop via
        call_soon_threadsafe. Bumps a counter, pushes the debounce deadline
        out, and wakes the coordinator. All judgment -- whether the change is
        real, whether to re-index -- happens in _evaluate, on a later tick.

        The wake is not optional: the coordinator may already be sleeping
        toward a reconcile deadline minutes away, computed before this event
        existed. Without waking it, the event sits recorded but unexamined
        until that old deadline arrives, which is worse than the fixed poll
        this design replaced.
        """
        state = self._watched.get(root)
        if state is None:
            return
        state.generation += 1
        state.debounce_deadline = time.monotonic() + GRAPH_AUTO_INDEX_DEBOUNCE_SECONDS
        self.wake()

    async def _evaluate(self, state: _Watched) -> None:
        root = state.root
        if not os.path.isdir(root):
            logger.info("graph_auto_index.root_missing", root=root)
            state.failed = True
            self._watcher.unwatch(root)
            return

        generation_at_start = state.generation
        state.debounce_deadline = None

        reason: Optional[str] = None
        candidate_git_state: Optional[tuple[str, str]] = None
        if state.is_git:
            result = await asyncio.to_thread(git_source_state, root)
            if result is not None:
                candidate_git_state = result
                head, content_hash = result
                previous_head = state.git_head
                previous_hash = state.content_hash
                first_observation = previous_head is None
                changed = first_observation or (previous_head, previous_hash) != (
                    head,
                    content_hash,
                )
                if changed:
                    reason = (
                        "head_moved"
                        if not first_observation and head != previous_head
                        else "worktree_changed"
                    )
                elif state.retry_after and time.monotonic() >= state.retry_after:
                    reason = "reconcile"
        else:
            reason = (
                "filesystem_changed"
                if state.watch_mode != "reconcile_fallback"
                else "reconcile"
            )

        state.evaluated_generation = generation_at_start
        state.reconcile_deadline = time.monotonic() + GRAPH_AUTO_INDEX_RECONCILE_SECONDS

        if reason is not None:
            await self._reindex(
                state, reason=reason, candidate_git_state=candidate_git_state
            )

    async def _reindex(
        self,
        state: _Watched,
        reason: str,
        candidate_git_state: Optional[tuple[str, str]] = None,
    ) -> None:
        client = graph_supervisor.get_client()
        if client is None:
            return
        started = time.monotonic()
        result = await run_exclusive(
            f"auto_index:{state.root}",
            index_repository,
            client,
            GraphIndexRequest(
                action="index", repo_path=state.root, mode=GRAPH_AUTO_INDEX_MODE
            ),
        )
        if candidate_git_state is not None:
            state.git_head, state.content_hash = candidate_git_state
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if result.get("status") == "error":
            if result.get("error_code") == "windows_path_too_long":
                logger.warning(
                    "graph_auto_index.unindexable",
                    root=state.root,
                    error_code=result.get("error_code"),
                    hint=result.get("hint"),
                )
                return
            state.retry_after = time.monotonic() + GRAPH_AUTO_INDEX_RECONCILE_SECONDS
            logger.warning(
                "graph_auto_index.index_failed",
                root=state.root,
                reason=reason,
                message=result.get("message"),
                retry_in_seconds=GRAPH_AUTO_INDEX_RECONCILE_SECONDS,
            )
            return
        state.retry_after = 0.0
        self._indexed += 1
        state.last_indexed = _iso_now()
        state.last_index_reason = reason
        logger.info(
            "graph_auto_index.reindexed",
            root=state.root,
            project=result.get("project"),
            reason=reason,
            duration_ms=elapsed_ms,
        )
        try:
            await asyncio.to_thread(
                runtime_flags.save_watch_state,
                state.root,
                source_kind="git" if state.is_git else "non_git",
                last_source_state=(
                    f"{state.git_head}:{state.content_hash}" if state.is_git else None
                ),
                last_indexed=state.last_indexed,
                last_index_reason=reason,
                watch_status=state.watch_mode,
            )
        except Exception as exc:
            logger.warning(
                "graph_auto_index.watch_state_save_failed",
                root=state.root,
                error=str(exc),
            )

    def _detach(self, root: str) -> None:
        self._watcher.unwatch(root)
        self._watched.pop(root, None)

    def drop_watch(self, root: str) -> None:
        """Forget a root immediately, ahead of the next cache refresh, and
        stop watching it at the OS level.

        Only covers this process. The durable suppression in runtime_flags is
        what stops the other transport's poller, and what survives a restart.

        Matched canonically, because the caller's path spelling need not be the
        engine's: the watch set is keyed by whatever list_projects reported.
        """
        target = runtime_flags.canonical_root(root)
        for key in [
            key for key in self._watched if runtime_flags.canonical_root(key) == target
        ]:
            self._detach(key)

    def status(self) -> dict:
        return {
            "enabled": self.enabled(),
            "flag_source": runtime_flags.source(runtime_flags.AUTO_INDEX_GRAPH),
            "running": self.running,
            "debounce_seconds": GRAPH_AUTO_INDEX_DEBOUNCE_SECONDS,
            "reconcile_seconds": GRAPH_AUTO_INDEX_RECONCILE_SECONDS,
            "cycles": self._cycles,
            "indexed": self._indexed,
            "engine_binary_present": self.binary_present(),
            "projects": [
                {
                    "root_path": state.root,
                    "last_indexed": state.last_indexed,
                    "last_index_reason": state.last_index_reason,
                    "dropped": state.failed,
                    "watch_mode": state.watch_mode,
                    "last_source_state": (
                        f"{state.git_head}:{state.content_hash}"
                        if state.git_head is not None
                        else None
                    ),
                    "pending": state.generation != state.evaluated_generation,
                }
                for state in self._watched.values()
            ],
            "suppressed": runtime_flags.suppressed_watches(),
            "unindexable": runtime_flags.unindexable_watches(),
        }


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


graph_index_worker = GraphIndexWorker()

AUTO_ACTIONS = ("auto_on", "auto_off", "auto_status")


def auto_action(action: str) -> dict:
    """Handle the auto_* actions of marm_graph_index.

    Must be reachable with the engine stopped and must not start it: an off
    switch that only works while the thing it disables is running is not an off
    switch. Callers therefore dispatch this ahead of their availability gate.
    """
    if action == "auto_status":
        return {"status": "success", "auto_index": graph_index_worker.status()}

    turning_on = action == "auto_on"
    runtime_flags.set_bool(runtime_flags.AUTO_INDEX_GRAPH, turning_on)
    if turning_on:
        graph_index_worker.start()
    graph_index_worker.wake()
    return {
        "status": "success",
        "auto_index": {
            "enabled": turning_on,
            "flag_source": runtime_flags.source(runtime_flags.AUTO_INDEX_GRAPH),
            "effective": "next cycle" if not turning_on else "now",
        },
    }
