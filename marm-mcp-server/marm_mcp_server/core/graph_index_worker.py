"""Background poller that keeps indexed code graphs current.

A graph is otherwise only as fresh as the last manual `marm_graph_index` call,
and a stale graph does not fail loudly: it answers confidently from deleted code.

Detection is a git signature computed outside the engine, so an idle cycle costs
no engine lock. It is deliberately NOT the engine's own `detect_changes`, which
reports the dirty working tree relative to HEAD rather than drift between the
repo and the index: commit your work and it reports clean while the graph still
lacks every symbol in that commit. See docs/current/graph-auto-index.md.

While a repo is dirty the signature is useless, because `git status --porcelain`
names which files changed and not what is in them, so the second and every later
edit to one file produce byte-identical output. A dirty repo is therefore
re-indexed every cycle instead. `index_repository` is incremental, so an
unchanged dirty repo costs a few hundred milliseconds and a changed one does
exactly the work that was needed.
"""

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import structlog
from marm_graph.core import tool_router as R
from marm_graph.core.models import GraphIndexRequest

from ..config.settings import (
    GRAPH_AUTO_INDEX,
    GRAPH_AUTO_INDEX_FULL_INTERVAL,
    GRAPH_AUTO_INDEX_INTERVAL,
    GRAPH_AUTO_INDEX_MODE,
    GRAPH_AUTO_INDEX_PROJECT_TTL,
)
from . import runtime_flags
from .graph_index_lock import GraphIndexBusy, run_exclusive
from .graph_supervisor import graph_supervisor

logger = structlog.get_logger(__name__)

_GIT_TIMEOUT_SECONDS = 15

# Stands in for HEAD in a repository with no commits yet.
_UNBORN_HEAD = ""


def _git_env() -> dict[str, str]:
    """A scrubbed environment for a git call on a user-chosen repository.

    Inherited GIT_* variables belong to whatever launched the server, not to the
    repo being polled, and GIT_DIR or GIT_WORK_TREE would point our -C somewhere
    else entirely. GIT_OPTIONAL_LOCKS=0 keeps a status check from taking
    .git/index.lock and rewriting the index on a timer.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _git(root: str, *args: str) -> Optional[str]:
    """Run one git command in `root`. None means "could not tell", never "no change".

    core.fsmonitor names a program git will execute, and it is read from the
    polled repository's own config: honoring it would let any repo MARM watches
    run a program of its choosing on a 30 second timer.
    """
    try:
        proc = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("graph_auto_index.git_failed", root=root, error=str(exc))
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def is_git_repo(root: str) -> bool:
    return (Path(root) / ".git").exists()


def git_signature(root: str) -> Optional[tuple[str, bool]]:
    """(HEAD, dirty) for the repo AT `root`, or None if git could not answer.

    A None result must be treated as "no change". Re-indexing on a git error
    would turn a broken repo into a re-index on every single cycle.

    The `.git` check is not redundant with the caller's. Git's repository
    discovery walks upward from `-C`, so on a directory that is not itself a
    repo this would report an ancestor's HEAD and dirty state: an indexed
    subdirectory of some other repo would then re-index whenever anything
    anywhere in that parent changed.
    """
    if not is_git_repo(root):
        return None
    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        # A repository with no commits yet. `rev-parse HEAD` fails on an unborn
        # HEAD, and _poll_one has already classified this as git, so returning
        # None here meant such a repo returned early on every cycle and was
        # never refreshed at all. A stable sentinel puts it on the dirty lane
        # instead, which is the only signal it has until its first commit.
        if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
            return None
        head = _UNBORN_HEAD
    status = _git(root, "status", "--porcelain")
    if status is None:
        return None
    return (head, bool(status))


def index_repository(client, req: GraphIndexRequest) -> dict:
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
    result = R.do_index(client, req)
    root = req.repo_path
    if not root:
        return result
    if result.get("status") == "error":
        if result.get("error_code") == "windows_path_too_long":
            # Terminal until something outside the poller changes: the remedy the
            # error suggests (enabling Win32 long paths) leaves the path identical
            # and fixes both transports at once, so recovery cannot be keyed on
            # the path, and a restart must not be required to notice it.
            runtime_flags.mark_unindexable(root, "windows_path_too_long")
        return result
    # A success is the proof that both blocks are stale: the root is reachable,
    # and the user asked for it by indexing.
    runtime_flags.clear_index_blocks(root)
    return result


class _Watched:
    """Per-project poll state. Disposable: losing it costs one extra re-index."""

    __slots__ = (
        "failed",
        "last_full",
        "last_indexed",
        "retry_after",
        "root",
        "signature",
    )

    def __init__(self, root: str) -> None:
        self.root = root
        self.signature: Optional[tuple[str, bool]] = None
        self.last_full: float = 0.0
        self.last_indexed: Optional[str] = None
        # Set after a failure so the next attempt waits out a backoff instead of
        # retrying on the next cycle. Cleared by a success.
        self.retry_after: float = 0.0
        # Terminal for this session: a failure that cannot resolve itself, so
        # retrying only costs the engine gate.
        self.failed = False


class GraphIndexWorker:
    """Lazy singleton, mirroring ConceptIndexWorker's shape. start() and stop()
    are both idempotent."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._watched: dict[str, _Watched] = {}
        self._projects_loaded_at: Optional[float] = None
        self._cycles = 0
        self._indexed = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @staticmethod
    def enabled() -> bool:
        """Re-read on every cycle, never cached. An off switch that needed a
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
        """Never raises. A poller that cannot run leaves graphs as stale as they
        are today, which is recoverable; breaking startup is not."""
        if self.running:
            return
        if not self.enabled():
            # The loop still starts and each cycle re-checks the flag. That is
            # what lets `projects auto on` work without a restart: the CLI writes
            # the switch to the database from another process and cannot create a
            # task in this one. An idle cycle is one indexed SELECT.
            logger.info("graph_auto_index.idle", reason="auto_index_off")
        try:
            self._stop.clear()
            self._task = asyncio.get_running_loop().create_task(self._run())
            logger.info(
                "graph_auto_index.started",
                interval_seconds=GRAPH_AUTO_INDEX_INTERVAL,
                mode=GRAPH_AUTO_INDEX_MODE,
            )
        except RuntimeError as exc:
            logger.warning("graph_auto_index.start_failed", error=str(exc))

    async def stop(self) -> None:
        """Stop scheduling and return.

        Deliberately does not wait for an in-flight index and deliberately does
        not release its lease. The index call owns its own lease through
        run_exclusive and finishes on its own; there is no durable task to protect
        here, and the next cycle recomputes the signature from scratch anyway.
        """
        self._stop.set()
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("graph_auto_index.stop_error", error=str(exc))
        logger.info(
            "graph_auto_index.stopped", cycles=self._cycles, indexed=self._indexed
        )

    async def _run(self) -> None:
        primed = False
        while not self._stop.is_set():
            await self._wait(GRAPH_AUTO_INDEX_INTERVAL)
            if self._stop.is_set():
                return
            if not self.enabled():
                continue
            if not primed:
                # Once, and only after the flag says yes: priming spawns the
                # engine child, which auto-index off must never do.
                primed = True
                await self._prime_engine()
            self._cycles += 1
            try:
                await self._cycle()
            except Exception as exc:
                # One bad cycle must never end the loop. Nothing here is
                # durable, so the next signature check recovers whatever
                # this one missed.
                logger.warning("graph_auto_index.cycle_failed", error=str(exc))

    async def _prime_engine(self) -> None:
        """Start the engine once, off the lifespan path, if it is already on disk.

        _ensure_started() is synchronous and can spend CBM_STARTUP_TIMEOUT (60s)
        spawning and handshaking, so it must never run inline in lifespan and
        never inside a poll cycle.
        """
        if not self.binary_present():
            logger.info("graph_auto_index.dormant", reason="engine_binary_absent")
            return
        try:
            await asyncio.to_thread(graph_supervisor.is_available)
        except Exception as exc:
            logger.warning("graph_auto_index.prime_failed", error=str(exc))

    async def _wait(self, seconds: float) -> bool:
        """Sleep unless stopped first. Returns whether a stop arrived."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            return True
        except (asyncio.TimeoutError, TimeoutError):
            return False

    async def _cycle(self) -> None:
        if not self.enabled():
            return
        # snapshot(), never is_available(): the latter calls _ensure_started()
        # and would spawn the engine from inside a poll cycle.
        if not graph_supervisor.snapshot()["available"]:
            return

        await self._refresh_projects()
        for state in list(self._watched.values()):
            if self._stop.is_set():
                return
            if state.failed:
                # In-process and genuinely terminal: the root is gone.
                continue
            # Read per cycle rather than cached in the state. A delete or a
            # successful manual index in the OTHER transport is invisible here
            # until this read, and the watch set is only reloaded once per TTL,
            # so anything keyed to that reload lags by up to five minutes.
            if await asyncio.to_thread(runtime_flags.index_block, state.root):
                continue
            try:
                await self._poll_one(state)
            except GraphIndexBusy:
                # Someone else is indexing. Skip; the next cycle recomputes.
                continue
            except Exception as exc:
                logger.warning(
                    "graph_auto_index.project_failed", root=state.root, error=str(exc)
                )

    async def _refresh_projects(self) -> None:
        """Reload the watch set when its TTL expires.

        list_projects costs ~265ms and holds the engine lock, so this is cached
        rather than called every cycle.

        Freshness is the load timestamp alone, never whether the watch set came
        back non-empty. An empty result is a real answer: a fresh install with no
        projects, or an install where every project is suppressed. Treating empty
        as "not loaded yet" put list_projects back on every 30s cycle for exactly
        the users who have no indexing to do.
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
            self._watched[root] = _Watched(root)
        for root in list(self._watched):
            if root not in roots or runtime_flags.is_watch_suppressed(root):
                self._watched.pop(root, None)

    async def _poll_one(self, state: _Watched) -> None:
        root = state.root
        if not os.path.isdir(root):
            # Moved or deleted. index_repository would error on every cycle.
            logger.info("graph_auto_index.root_missing", root=root)
            state.failed = True
            return

        if not is_git_repo(root):
            # No cheap signature exists, so the only option is an unconditional
            # re-index. That holds the engine lock, so it gets the slow lane.
            if time.monotonic() - state.last_full < GRAPH_AUTO_INDEX_FULL_INTERVAL:
                return
            await self._reindex(state, reason="non_git_interval")
            return

        signature = await asyncio.to_thread(git_signature, root)
        if signature is None:
            return

        previous = state.signature
        state.signature = signature
        _, dirty = signature
        changed = previous is None or previous != signature

        # A repo that changed carries new information, so it is retried at once.
        # Otherwise a failure waits out its backoff: the signature is recorded
        # before the index runs, so without this a failed index would either never
        # be retried (clean repo) or be retried every single cycle (dirty repo).
        if state.retry_after and not changed and time.monotonic() < state.retry_after:
            return

        if dirty:
            await self._reindex(state, reason="dirty")
        elif changed and previous is not None and previous[1]:
            # Was dirty last cycle, clean now with the same HEAD: the edits were
            # reverted or stashed, and the graph still holds what they contained.
            await self._reindex(state, reason="went_clean")
        elif changed:
            await self._reindex(state, reason="head_moved")
        elif state.retry_after:
            await self._reindex(state, reason="retry_after_failure")

    async def _reindex(self, state: _Watched, reason: str) -> None:
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
        elapsed_ms = int((time.monotonic() - started) * 1000)
        # Recorded on failure too. A non-git project's only gate is this timer, so
        # leaving it at its old value on error made a failing one retry on the fast
        # interval and take the engine gate every cycle.
        state.last_full = time.monotonic()
        if result.get("status") == "error":
            if result.get("error_code") == "windows_path_too_long":
                # Marked by index_repository, inside the gate.
                logger.warning(
                    "graph_auto_index.unindexable",
                    root=state.root,
                    error_code=result.get("error_code"),
                    hint=result.get("hint"),
                )
                return
            state.retry_after = time.monotonic() + GRAPH_AUTO_INDEX_FULL_INTERVAL
            logger.warning(
                "graph_auto_index.index_failed",
                root=state.root,
                reason=reason,
                message=result.get("message"),
                retry_in_seconds=GRAPH_AUTO_INDEX_FULL_INTERVAL,
            )
            return
        state.retry_after = 0.0
        self._indexed += 1
        state.last_indexed = _iso_now()
        logger.info(
            "graph_auto_index.reindexed",
            root=state.root,
            project=result.get("project"),
            reason=reason,
            duration_ms=elapsed_ms,
        )

    def drop_watch(self, root: str) -> None:
        """Forget a root immediately, ahead of the next cache refresh.

        Only covers this process. The durable suppression in runtime_flags is
        what stops the other transport's poller, and what survives a restart.

        Matched canonically, because the caller's path spelling need not be the
        engine's: the watch set is keyed by whatever list_projects reported.
        """
        target = runtime_flags.canonical_root(root)
        for key in [
            key for key in self._watched if runtime_flags.canonical_root(key) == target
        ]:
            self._watched.pop(key, None)

    def status(self) -> dict:
        return {
            "enabled": self.enabled(),
            "flag_source": runtime_flags.source(runtime_flags.AUTO_INDEX_GRAPH),
            "running": self.running,
            "interval_seconds": GRAPH_AUTO_INDEX_INTERVAL,
            "cycles": self._cycles,
            "indexed": self._indexed,
            "engine_binary_present": self.binary_present(),
            "projects": [
                {
                    "root_path": state.root,
                    "last_indexed": state.last_indexed,
                    "dropped": state.failed,
                }
                for state in self._watched.values()
            ],
            "suppressed": runtime_flags.suppressed_watches(),
            # Named so a project that is enrolled but never refreshing is visible
            # rather than looking merely idle.
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
    return {
        "status": "success",
        "auto_index": {
            "enabled": turning_on,
            "flag_source": runtime_flags.source(runtime_flags.AUTO_INDEX_GRAPH),
            # The loop reads the flag per cycle, so turning it off takes effect
            # on the next one without a restart.
            "effective": "next cycle" if not turning_on else "now",
        },
    }
