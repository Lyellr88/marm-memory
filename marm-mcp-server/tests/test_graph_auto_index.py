"""Code graph auto-indexing: change detection, the indexing gate, and the switch.

Real git repositories and a real SQLite memory database throughout. The engine
itself is stubbed only where a test is about MARM's logic rather than the
engine's, and those stubs stand in for one call with a known response shape;
the end-to-end path is covered by the @requires_binary test at the bottom.
"""

import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def shared_db(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    load_isolated_server(monkeypatch, tmp_path)
    memory_module = sys.modules["marm_mcp_server.core.memory"]
    return memory_module.memory, tmp_path / "marm_memory.db"


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


# Deliberately not under tmp_path. The graph engine names each project's
# database after the repository's full path with the separators replaced, so a
# deep pytest temp directory produces a filename that overflows Windows MAX_PATH
# and the engine's indexing worker exits non-zero. Measured: a repo 140
# characters deep yields a 283-character database path against a 260 limit, and
# the test then fails for a reason unrelated to what it tests. pytest's temp
# depth is set by the invocation, so it cannot be relied on here.
SHORT_TMP = Path(r"C:\tmp\marm-pytest") if os.name == "nt" else Path("/tmp/marm-pytest")


@pytest.fixture
def git_repo():
    root = SHORT_TMP / f"gr-{uuid.uuid4().hex[:8]}"
    (root / "src").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "src" / "a.py").write_text("def g_one():\n    return 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "first")
    try:
        yield root
    finally:
        # .git holds read-only pack files on Windows, which rmtree refuses.
        shutil.rmtree(root, onerror=_force_remove)


def _force_remove(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _run_in_second_process(db_path: Path, body: str) -> dict:
    prelude = (
        "import json, os, sys\n"
        f"os.environ['MARM_DB_PATH'] = {str(db_path)!r}\n"
        f"os.environ['MARM_ANALYTICS_DB_PATH'] = "
        f"{str(db_path.parent / 'analytics.db')!r}\n"
        "os.environ['WRITE_QUEUE_ENABLED'] = '0'\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
    )
    script = (
        prelude
        + textwrap.dedent(body).strip()
        + "\nprint('RESULT ' + json.dumps(result))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env=dict(os.environ),
    )
    if completed.returncode != 0:
        pytest.fail(f"second process failed:\n{completed.stdout}\n{completed.stderr}")
    for line in completed.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT ") :])
    pytest.fail(f"second process printed no result:\n{completed.stdout}")


# ── change detection ────────────────────────────────────────────────


def test_signature_moves_on_commit_and_on_edit(git_repo):
    """The two changes a code graph must notice. detect_changes sees only the
    second one, which is why the poller does not use it."""
    from marm_mcp_server.core.graph_index_worker import git_signature

    base = git_signature(str(git_repo))
    assert base is not None
    assert base[1] is False

    (git_repo / "src" / "a.py").write_text("def g_one():\n    return 2\n")
    dirty = git_signature(str(git_repo))
    assert dirty[0] == base[0]
    assert dirty[1] is True

    _git(git_repo, "commit", "-aqm", "second")
    committed = git_signature(str(git_repo))
    assert committed[0] != base[0], "HEAD must move on commit"
    assert committed[1] is False


def test_a_dirty_repo_signature_is_identical_across_repeated_edits(git_repo):
    """The measurement the whole dirty-path design rests on. If this ever
    changes, re-indexing every dirty cycle stops being necessary."""
    from marm_mcp_server.core.graph_index_worker import git_signature

    signatures = []
    for index in range(3):
        # Never the committed body, or one iteration is legitimately clean.
        (git_repo / "src" / "a.py").write_text(f"def g_one():\n    return 10{index}\n")
        signatures.append(git_signature(str(git_repo)))

    assert signatures[0] == signatures[1] == signatures[2]
    assert all(signature[1] is True for signature in signatures)


def test_git_failure_reads_as_no_change(tmp_path):
    """A broken or non-repo path must not re-index on every single cycle."""
    from marm_mcp_server.core.graph_index_worker import git_signature, is_git_repo

    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_git_repo(str(plain)) is False
    assert git_signature(str(plain)) is None


def test_a_non_repo_never_reports_an_ancestor_repos_signature(git_repo):
    """Git's repository discovery walks upward from -C. A subdirectory that is
    not itself a repo must not report the enclosing repo's HEAD and dirty state,
    or it would re-index whenever anything anywhere in that parent changed.

    This is also why the assertion above cannot depend on pytest's temp
    directory happening to sit outside every git repository.
    """
    from marm_mcp_server.core.graph_index_worker import git_signature, is_git_repo

    nested = git_repo / "src" / "not_a_repo"
    nested.mkdir()
    assert git_signature(str(git_repo)) is not None, "the real repo still answers"

    assert is_git_repo(str(nested)) is False
    assert git_signature(str(nested)) is None

    # And the same for a plain directory whose parent is a repo.
    (git_repo / "src" / "a.py").write_text("def g_one():\n    return 42\n")
    assert git_signature(str(nested)) is None


def test_core_fsmonitor_from_the_polled_repo_is_never_executed(git_repo, tmp_path):
    """core.fsmonitor names a program git will run, read from the watched repo's
    own config. Polling a user-chosen repository must not invoke it on a timer."""
    from marm_mcp_server.core.graph_index_worker import git_signature

    sentinel = tmp_path / "fsmonitor-ran"
    if sys.platform == "win32":
        hook = tmp_path / "hook.bat"
        hook.write_text(f"@echo ran > {sentinel}\n")
    else:
        hook = tmp_path / "hook.sh"
        hook.write_text(f"#!/bin/sh\necho ran > {sentinel}\n")
        hook.chmod(0o755)
    _git(git_repo, "config", "core.fsmonitor", str(hook).replace("\\", "/"))

    (git_repo / "src" / "a.py").write_text("def g_one():\n    return 9\n")
    assert git_signature(str(git_repo)) is not None
    assert not sentinel.exists(), "core.fsmonitor was executed"


def test_git_runs_with_a_scrubbed_environment(git_repo, monkeypatch, tmp_path):
    """An inherited GIT_DIR belongs to whatever launched the server, and would
    point our -C at a different repository entirely."""
    from marm_mcp_server.core.graph_index_worker import git_signature

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("GIT_DIR", str(other))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))

    assert git_signature(str(git_repo)) is not None


def test_git_poll_hides_its_windows_child_window(monkeypatch):
    """The poller runs git every cycle, so it must not flash a console window."""
    from marm_mcp_server.core import graph_index_worker as module

    captured = {}

    class Completed:
        returncode = 0
        stdout = "ok\n"

    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.subprocess, "CREATE_NO_WINDOW", 123, raising=False)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kwargs: captured.update(command=command, **kwargs) or Completed(),
    )

    assert module._git("C:/repo", "rev-parse", "HEAD") == "ok"
    assert captured["creationflags"] == 123


# ── the indexing gate ───────────────────────────────────────────────


def test_a_second_process_cannot_take_the_index_gate(shared_db):
    """_project_job_lock is a threading.Lock and covers one interpreter. Two
    transports are two processes over one engine store."""
    from marm_mcp_server.core import graph_index_lock

    _, db_path = shared_db
    assert graph_index_lock.try_acquire("a", "auto_index", 300) is True

    theirs = _run_in_second_process(
        db_path,
        """
        from marm_mcp_server.core import graph_index_lock
        result = {
            "acquired": graph_index_lock.try_acquire("b", "manual_index:http", 60),
            "holder": graph_index_lock.current_holder(),
        }
        """,
    )
    assert theirs["acquired"] is False
    assert theirs["holder"][0] == "auto_index"


def test_a_second_process_takes_over_an_expired_gate(shared_db):
    """A process killed mid-index must not wedge indexing forever."""
    from marm_mcp_server.core import graph_index_lock

    mem, db_path = shared_db
    graph_index_lock.try_acquire("crashed", "auto_index", 3600)
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE graph_index_lock SET expires_at = '2000-01-01T00:00:00+00:00'"
        )

    theirs = _run_in_second_process(
        db_path,
        """
        from marm_mcp_server.core import graph_index_lock
        result = {"acquired": graph_index_lock.try_acquire("next", "auto_index", 60)}
        """,
    )
    assert theirs["acquired"] is True


def test_the_concept_lock_and_the_index_gate_are_independent(shared_db):
    """Separate rows on purpose: concept extraction and code indexing touch
    different stores and must not be mutually exclusive."""
    from marm_mcp_server.core import concept_build_lock, graph_index_lock

    assert concept_build_lock.try_acquire("c", "manual_build", 300) is True
    assert graph_index_lock.try_acquire("g", "auto_index", 300) is True


@pytest.mark.asyncio
async def test_run_exclusive_refuses_a_second_caller_while_one_runs(shared_db):
    from marm_mcp_server.core import graph_index_lock

    entered = threading.Event()
    may_finish = threading.Event()

    def blocking_index():
        entered.set()
        may_finish.wait(10)
        return {"status": "success"}

    first = asyncio.create_task(
        graph_index_lock.run_exclusive("auto_index", blocking_index)
    )
    await asyncio.to_thread(entered.wait, 5)

    with pytest.raises(graph_index_lock.GraphIndexBusy):
        await graph_index_lock.run_exclusive("manual_index:http", lambda: {})

    may_finish.set()
    assert (await first)["status"] == "success"
    assert graph_index_lock.current_holder() is None


@pytest.mark.asyncio
async def test_cancelling_the_caller_does_not_release_the_gate(shared_db):
    """asyncio.to_thread cancellation cancels the await, never the thread. A
    lease released on caller cancellation hands the store to another process
    while the engine is still writing to it."""
    from marm_mcp_server.core import graph_index_lock

    entered = threading.Event()
    may_finish = threading.Event()
    exited = threading.Event()

    def blocking_index():
        entered.set()
        may_finish.wait(10)
        exited.set()
        return {"status": "success"}

    caller = asyncio.create_task(
        graph_index_lock.run_exclusive("auto_index", blocking_index)
    )
    await asyncio.to_thread(entered.wait, 5)

    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller

    # The engine call is still running, so the gate must still be held.
    assert not exited.is_set()
    assert graph_index_lock.current_holder() is not None
    with pytest.raises(graph_index_lock.GraphIndexBusy):
        await graph_index_lock.run_exclusive("manual_index:http", lambda: {})

    may_finish.set()
    await asyncio.to_thread(exited.wait, 5)
    for _ in range(100):
        if graph_index_lock.current_holder() is None:
            break
        await asyncio.sleep(0.05)
    assert graph_index_lock.current_holder() is None, (
        "the gate must be released once the engine call returns"
    )
    # And it is genuinely reusable afterwards.
    assert (
        await graph_index_lock.run_exclusive("manual_index:http", lambda: {"ok": 1})
    )["ok"] == 1


@pytest.mark.asyncio
async def test_the_gate_outlives_its_own_ttl_while_work_continues(shared_db):
    """The heartbeat guarantee: the TTL bounds a crashed holder, not a long index."""
    from marm_mcp_server.core import graph_index_lock

    entered = threading.Event()
    may_finish = threading.Event()

    def slow_index():
        entered.set()
        may_finish.wait(10)
        return {"status": "success"}

    task = asyncio.create_task(
        graph_index_lock.run_exclusive("auto_index", slow_index, ttl_seconds=1)
    )
    await asyncio.to_thread(entered.wait, 5)
    await asyncio.sleep(2.5)  # well past the 1s TTL, heartbeat should have renewed

    assert graph_index_lock.try_acquire("other", "manual_index:http", 60) is False

    may_finish.set()
    await task


@pytest.mark.asyncio
async def test_worker_stop_neither_releases_the_gate_nor_waits_for_the_index(shared_db):
    from marm_mcp_server.core import graph_index_lock
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker

    entered = threading.Event()
    may_finish = threading.Event()

    def blocking_index():
        entered.set()
        may_finish.wait(10)
        return {"status": "success"}

    worker = GraphIndexWorker()
    indexing = asyncio.create_task(
        graph_index_lock.run_exclusive("auto_index", blocking_index)
    )
    await asyncio.to_thread(entered.wait, 5)

    started = time.monotonic()
    await worker.stop()
    assert time.monotonic() - started < 2, "stop() must not wait for the index"
    assert graph_index_lock.current_holder() is not None

    may_finish.set()
    await indexing


# ── the switch ──────────────────────────────────────────────────────


def test_a_saved_override_beats_the_environment(shared_db, monkeypatch):
    """Otherwise a GRAPH_AUTO_INDEX=true in a Dockerfile silently re-enables
    something the user turned off, on every restart."""
    from marm_mcp_server.core import runtime_flags
    from marm_mcp_server.core.graph_index_worker import graph_index_worker

    assert graph_index_worker.enabled() is True
    assert runtime_flags.source(runtime_flags.AUTO_INDEX_GRAPH) == "environment"

    runtime_flags.set_bool(runtime_flags.AUTO_INDEX_GRAPH, False)
    assert graph_index_worker.enabled() is False
    assert runtime_flags.source(runtime_flags.AUTO_INDEX_GRAPH) == "override"

    runtime_flags.clear(runtime_flags.AUTO_INDEX_GRAPH)
    assert graph_index_worker.enabled() is True


def test_the_switch_is_visible_to_another_process(shared_db):
    from marm_mcp_server.core import runtime_flags

    _, db_path = shared_db
    runtime_flags.set_bool(runtime_flags.AUTO_INDEX_GRAPH, False)

    theirs = _run_in_second_process(
        db_path,
        """
        from marm_mcp_server.core.graph_index_worker import graph_index_worker
        from marm_mcp_server.core import runtime_flags
        result = {
            "enabled": graph_index_worker.enabled(),
            "source": runtime_flags.source(runtime_flags.AUTO_INDEX_GRAPH),
        }
        """,
    )
    assert theirs == {"enabled": False, "source": "override"}


def test_auto_off_and_auto_status_do_not_start_the_engine(shared_db):
    """The availability gate starts the engine as a side effect, so the auto
    actions are dispatched ahead of it. An off switch that needs the thing it
    disables to be running is not an off switch."""
    from marm_mcp_server.core.graph_index_worker import auto_action
    from marm_mcp_server.core.graph_supervisor import graph_supervisor

    assert graph_supervisor.snapshot()["started"] is False

    off = auto_action("auto_off")
    assert off["status"] == "success"
    assert off["auto_index"]["enabled"] is False

    status = auto_action("auto_status")
    assert status["auto_index"]["enabled"] is False
    assert status["auto_index"]["flag_source"] == "override"

    assert graph_supervisor.snapshot()["started"] is False, (
        "the auto actions must not spawn the engine"
    )


def test_a_disabled_cycle_never_touches_the_engine(shared_db, monkeypatch):
    """Off must mean off before anything reads engine state, since the poller's
    own gate is the only thing standing between a disabled feature and a spawned
    269MB child."""
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core import runtime_flags

    touched = []
    monkeypatch.setattr(
        module.graph_supervisor,
        "snapshot",
        lambda: touched.append("snapshot") or {"available": True},
    )
    monkeypatch.setattr(
        module.graph_supervisor,
        "is_available",
        lambda: pytest.fail("is_available() spawns the engine; the poller must not"),
    )

    runtime_flags.set_bool(runtime_flags.AUTO_INDEX_GRAPH, False)
    worker = module.GraphIndexWorker()
    asyncio.run(worker._cycle())

    assert touched == []
    assert worker.status()["enabled"] is False


def test_concept_auto_index_honors_the_same_override(shared_db):
    from marm_mcp_server.core import runtime_flags
    from marm_mcp_server.core.concept_worker import concept_worker

    assert concept_worker.enabled() is True
    runtime_flags.set_bool(runtime_flags.AUTO_INDEX_CONCEPT, False)
    assert concept_worker.enabled() is False


# ── unwatching ──────────────────────────────────────────────────────


def test_a_suppressed_root_is_dropped_from_the_watch_set(shared_db, monkeypatch):
    """A delete must survive the project cache. Re-indexing a root inside the
    TTL window recreates the project the user just deleted."""
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core import runtime_flags

    worker = module.GraphIndexWorker()
    listed = {
        "status": "success",
        "projects": [
            {"name": "keep", "root_path": "/repo/keep"},
            {"name": "gone", "root_path": "/repo/gone"},
        ],
    }
    monkeypatch.setattr(module.R, "do_index", lambda client, req: listed)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )

    asyncio.run(worker._refresh_projects())
    assert set(worker._watched) == {"/repo/keep", "/repo/gone"}

    runtime_flags.suppress_watch("/repo/gone")
    worker._projects_loaded_at = None
    asyncio.run(worker._refresh_projects())
    assert set(worker._watched) == {"/repo/keep"}

    # An explicit manual index re-enrolls it.
    runtime_flags.unsuppress_watch("/repo/gone")
    worker._projects_loaded_at = None
    asyncio.run(worker._refresh_projects())
    assert set(worker._watched) == {"/repo/keep", "/repo/gone"}


def test_a_non_git_project_polls_only_on_the_slow_interval(
    shared_db, tmp_path, monkeypatch
):
    """Its only detection option is an unconditional re-index, which holds the
    engine lock. A directory that was never a repo must not do that every 30s."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))

    reindexed = []

    async def record(target, reason):
        reindexed.append(reason)
        target.last_full = time.monotonic()

    monkeypatch.setattr(worker, "_reindex", record)

    asyncio.run(worker._poll_one(state))
    assert reindexed == ["non_git_interval"]

    # Immediately again: inside the slow interval, so nothing.
    asyncio.run(worker._poll_one(state))
    assert reindexed == ["non_git_interval"]

    # Past the slow interval it fires once more.
    state.last_full = time.monotonic() - module.GRAPH_AUTO_INDEX_FULL_INTERVAL - 1
    asyncio.run(worker._poll_one(state))
    assert reindexed == ["non_git_interval", "non_git_interval"]


def test_the_poller_stays_dormant_when_the_engine_binary_is_absent(
    shared_db, monkeypatch
):
    """Auto-index is on by default. Priming the engine when the binary is not
    downloaded would make every fresh install pull ~269MB at first boot,
    including users who never call a graph tool."""
    from marm_mcp_server.core import graph_index_worker as module

    worker = module.GraphIndexWorker()
    monkeypatch.setattr(worker, "binary_present", lambda: False)
    monkeypatch.setattr(
        module.graph_supervisor,
        "is_available",
        lambda: pytest.fail("the engine must not be started, let alone downloaded"),
    )

    asyncio.run(worker._prime_engine())


def test_a_tombstone_is_cleared_whichever_path_spelling_clears_it(shared_db):
    """The engine reports "C:/repo" while MARM validates to "C:\\repo". Keyed on
    the raw string, a manual index would never clear the delete's tombstone and
    the poller would keep skipping a project the user had just re-indexed."""
    from marm_mcp_server.core import runtime_flags

    engine_form = "C:/repo/thing" if os.name == "nt" else "/repo/thing/"
    marm_form = "C:\\repo\\thing" if os.name == "nt" else "/repo/thing"

    runtime_flags.suppress_watch(engine_form)
    assert runtime_flags.is_watch_suppressed(marm_form) is True
    assert runtime_flags.unsuppress_watch(marm_form) is True
    assert runtime_flags.is_watch_suppressed(engine_form) is False


@pytest.mark.asyncio
async def test_a_failed_manual_index_does_not_clear_the_tombstone(shared_db):
    """do_index reports engine failures as an error dict rather than raising, so
    a clear that runs before the status check re-enrolls a deleted project on the
    strength of an index that did not happen."""
    from marm_mcp_server.core import runtime_flags
    from marm_mcp_server.endpoints import graph as endpoint

    root = "/repo/deleted"
    runtime_flags.suppress_watch(root)

    failing = {"status": "error", "message": "index_repository failed"}
    original = endpoint.R.do_index
    endpoint.R.do_index = lambda client, req: failing
    try:
        result = await endpoint.marm_graph_index(
            endpoint.GraphIndexRequest(action="index", repo_path=root)
        )
    finally:
        endpoint.R.do_index = original

    assert result["status"] == "error"
    assert runtime_flags.is_watch_suppressed(root) is True, (
        "a failed index must not re-enroll a deleted project"
    )


@pytest.mark.asyncio
async def test_a_successful_manual_index_does_clear_the_tombstone(shared_db):
    from marm_mcp_server.core import runtime_flags
    from marm_mcp_server.endpoints import graph as endpoint

    root = "/repo/revived"
    runtime_flags.suppress_watch(root)

    original = endpoint.R.do_index
    endpoint.R.do_index = lambda client, req: {"status": "success", "project": "p"}
    try:
        result = await endpoint.marm_graph_index(
            endpoint.GraphIndexRequest(action="index", repo_path=root)
        )
    finally:
        endpoint.R.do_index = original

    assert result["status"] == "success"
    assert runtime_flags.is_watch_suppressed(root) is False


@pytest.mark.asyncio
async def test_a_delete_cannot_run_while_an_index_holds_the_gate(shared_db):
    """delete_project mutates the same per-project store as index_repository. A
    delete that lands mid-index is undone: the index finishes afterwards and
    writes the project back, so a deleted project reappears."""
    from marm_mcp_server.core import graph_index_lock
    from marm_mcp_server.endpoints import graph as endpoint

    entered = threading.Event()
    may_finish = threading.Event()

    def blocking_index():
        entered.set()
        may_finish.wait(10)
        return {"status": "success"}

    indexing = asyncio.create_task(
        graph_index_lock.run_exclusive("auto_index", blocking_index)
    )
    await asyncio.to_thread(entered.wait, 5)

    called = []
    original = endpoint.graph_supervisor.get_client

    class _Client:
        def call_tool(self, name, args=None):
            called.append(name)
            return {"status": "success"}

    endpoint.graph_supervisor.get_client = lambda: _Client()
    endpoint.graph_supervisor._available = True
    endpoint.graph_supervisor._ready.set()
    try:
        result = await endpoint.console_delete_project(
            endpoint.ConsoleDeleteProjectRequest(project="p", name="p", confirm=True)
        )
    finally:
        endpoint.graph_supervisor.get_client = original
        may_finish.set()
        await indexing

    assert result["error_code"] == "index_in_progress"
    assert "delete_project" not in called, (
        "delete_project must not reach the engine mid-index"
    )
    # Refused before the gate, so the root lookup is not spent either.
    assert called == []


def test_an_invalid_index_mode_falls_back_instead_of_failing_every_cycle(monkeypatch):
    """An unrecognized mode fails GraphIndexRequest's Literal deep inside the
    poll cycle, which logs a project failure forever and indexes nothing."""
    import importlib

    monkeypatch.setenv("GRAPH_AUTO_INDEX_MODE", "turbo")
    settings = importlib.reload(
        importlib.import_module("marm_mcp_server.config.settings")
    )
    try:
        assert settings.GRAPH_AUTO_INDEX_MODE == "moderate"
    finally:
        monkeypatch.delenv("GRAPH_AUTO_INDEX_MODE", raising=False)
        importlib.reload(settings)


def test_an_empty_project_list_is_still_a_cached_answer(shared_db, monkeypatch):
    """An empty watch set is a real result: a fresh install, or one where every
    project is suppressed. Treating it as "not loaded" puts list_projects, which
    costs ~265ms and holds the engine lock, back on every 30s cycle."""
    from marm_mcp_server.core import graph_index_worker as module

    calls = []

    def counting_list(client, req):
        calls.append(req.action)
        return {"status": "success", "projects": []}

    monkeypatch.setattr(module.R, "do_index", counting_list)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )

    worker = module.GraphIndexWorker()
    asyncio.run(worker._refresh_projects())
    asyncio.run(worker._refresh_projects())
    asyncio.run(worker._refresh_projects())

    assert worker._watched == {}
    assert calls == ["list"], "an empty result must be cached like any other"


# ── failure handling ────────────────────────────────────────────────


def _tool_error(payload):
    from marm_graph.core.cbm_client import CbmToolError

    return CbmToolError("index_repository: None", payload=payload)


@pytest.mark.skipif(os.name != "nt", reason="Win32 path limit")
def test_a_deep_repo_path_is_reported_as_a_path_limit_not_a_bad_file():
    """The engine reports this as a contained per-file worker crash and advises
    re-running, which can never succeed: nothing about the path changes between
    attempts. Users follow that hint hunting a corrupt file that does not exist."""
    from marm_graph.core import tool_router
    from marm_graph.core.models import GraphIndexRequest

    # Grown against the predictor rather than hardcoded: how deep a repo has to
    # be before it overflows depends on the length of this machine's home
    # directory, which is where the engine keeps its store.
    deep = "C:\\deep"
    while (
        tool_router._predicted_store_path_length(deep) < tool_router._WINDOWS_PATH_LIMIT
    ):
        deep += "\\" + "x" * 20
    assert tool_router._predicted_store_path_length(deep) >= 260

    class _Client:
        def call_tool(self, name, args):
            raise _tool_error(
                {
                    "status": "error",
                    "outcome": "exit_nonzero",
                    "hint": "Indexing worker crashed on a file. Re-run to retry;",
                    "repo_path": deep,
                }
            )

    result = tool_router.do_index(
        _Client(), GraphIndexRequest(action="index", repo_path=deep)
    )
    assert result["error_code"] == "windows_path_too_long"
    assert "Re-running will not help" in result["hint"]
    assert "crashed on a file" not in result["hint"]


def test_a_short_repo_path_keeps_the_engines_own_error():
    """The diagnosis is a reconstruction of the engine's naming scheme, so it must
    never replace an unrelated failure's message."""
    from marm_graph.core import tool_router
    from marm_graph.core.models import GraphIndexRequest

    class _Client:
        def call_tool(self, name, args):
            raise _tool_error(
                {
                    "status": "error",
                    "outcome": "exit_nonzero",
                    "hint": "Indexing worker crashed on a file.",
                }
            )

    short = "C:\\r" if os.name == "nt" else "/r"
    result = tool_router.do_index(
        _Client(), GraphIndexRequest(action="index", repo_path=short)
    )
    assert result["status"] == "error"
    assert result.get("error_code") != "windows_path_too_long"
    assert "crashed on a file" in result["hint"]


def test_a_failing_non_git_project_does_not_retry_on_the_fast_interval(
    shared_db, tmp_path, monkeypatch
):
    """A non-git project's only gate is its last-attempt timer. Leaving that at its
    old value on failure made a broken one re-index every cycle, taking the engine
    gate each time."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    attempts = []

    async def failing(purpose, fn, *args, **kwargs):
        attempts.append(purpose)
        return {"status": "error", "message": "boom"}

    monkeypatch.setattr(module, "run_exclusive", failing)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )

    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    asyncio.run(worker._poll_one(state))
    assert len(attempts) == 1

    asyncio.run(worker._poll_one(state))
    asyncio.run(worker._poll_one(state))
    assert len(attempts) == 1, "a failure must still occupy the slow lane"

    state.last_full = time.monotonic() - module.GRAPH_AUTO_INDEX_FULL_INTERVAL - 1
    asyncio.run(worker._poll_one(state))
    assert len(attempts) == 2


def test_a_failed_index_on_a_clean_repo_retries_after_a_backoff(
    shared_db, git_repo, monkeypatch
):
    """The signature is recorded before the index runs, so without a backoff a
    failure on a clean repo would never be retried until the repo changed."""
    from marm_mcp_server.core import graph_index_worker as module

    attempts = []

    async def failing(purpose, fn, *args, **kwargs):
        attempts.append(purpose)
        return {"status": "error", "message": "boom"}

    monkeypatch.setattr(module, "run_exclusive", failing)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )

    worker = module.GraphIndexWorker()
    state = module._Watched(str(git_repo))
    asyncio.run(worker._poll_one(state))
    assert len(attempts) == 1
    assert state.retry_after > 0

    # Nothing changed and the backoff has not elapsed.
    asyncio.run(worker._poll_one(state))
    assert len(attempts) == 1

    state.retry_after = time.monotonic() - 1
    asyncio.run(worker._poll_one(state))
    assert len(attempts) == 2

    # A commit is new information and is retried at once, backoff or not.
    state.retry_after = time.monotonic() + 10_000
    (git_repo / "src" / "b.py").write_text("def g_two():\n    return 2\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "second")
    asyncio.run(worker._poll_one(state))
    assert len(attempts) == 3, "a changed repo must not wait out the backoff"


def test_an_unindexable_path_is_not_retried_at_all(shared_db, tmp_path, monkeypatch):
    """Deterministic failures must stop, or the poller holds the engine gate
    forever to re-learn the same thing."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    attempts = []

    # Stubbed at the engine boundary, so the real index_repository still runs:
    # it owns the marker write, and stubbing the gate instead would skip it.
    monkeypatch.setattr(
        module.R,
        "do_index",
        lambda client, req: {
            "status": "error",
            "error_code": "windows_path_too_long",
            "hint": "Index the repository from a shallower path.",
        },
    )

    async def counting_gate(purpose, fn, *args, **kwargs):
        attempts.append(purpose)
        return fn(*args, **kwargs)

    monkeypatch.setattr(module, "run_exclusive", counting_gate)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )

    from marm_mcp_server.core import runtime_flags

    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    asyncio.run(worker._poll_one(state))
    assert len(attempts) == 1
    assert runtime_flags.is_unindexable(str(plain)) is True

    # Even past the slow interval, and even through a whole cycle.
    state.last_full = time.monotonic() - module.GRAPH_AUTO_INDEX_FULL_INTERVAL - 1
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )
    asyncio.run(worker._cycle())
    assert len(attempts) == 1, "an unindexable project must be left alone"


def test_a_successful_manual_index_re_enables_a_previously_unindexable_root(
    shared_db, tmp_path, monkeypatch
):
    """The remedy the error recommends, enabling Win32 long paths, fixes the cause
    without the path changing at all. So recovery cannot be keyed on the path, and
    must not require a server restart."""
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core import runtime_flags
    from marm_mcp_server.endpoints import graph as endpoint

    plain = tmp_path / "plain"
    plain.mkdir()
    root = str(plain)
    runtime_flags.mark_unindexable(root, "windows_path_too_long")

    attempts = []

    # Stubbed at the engine boundary: index_repository owns the clear, so a
    # stubbed gate would never exercise the recovery this test is about.
    monkeypatch.setattr(
        module.R, "do_index", lambda client, req: {"status": "success", "project": "p"}
    )

    async def counting_gate(purpose, fn, *args, **kwargs):
        attempts.append(purpose)
        return fn(*args, **kwargs)

    monkeypatch.setattr(module, "run_exclusive", counting_gate)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    worker = module.GraphIndexWorker()
    worker._watched[root] = module._Watched(root)
    worker._projects_loaded_at = time.monotonic()

    asyncio.run(worker._cycle())
    assert attempts == [], "the marker must keep the poller off it"

    # A manual index succeeds, which is the proof the root is indexable again.
    monkeypatch.setattr(endpoint, "run_exclusive", counting_gate)
    monkeypatch.setattr(
        endpoint.graph_supervisor, "get_client", lambda: object(), raising=False
    )
    monkeypatch.setattr(endpoint.graph_supervisor, "is_available", lambda: True)
    asyncio.run(
        endpoint.marm_graph_index(
            endpoint.GraphIndexRequest(action="index", repo_path=root)
        )
    )
    assert runtime_flags.is_unindexable(root) is False

    before = len(attempts)
    asyncio.run(worker._cycle())
    assert len(attempts) == before + 1, (
        "polling must resume on the next cycle, with no restart"
    )


def test_the_unindexable_marker_is_visible_to_the_other_transport(shared_db, tmp_path):
    """Both transports poll, so a marker only one of them can see would leave the
    other retrying forever."""
    from marm_mcp_server.core import runtime_flags

    _, db_path = shared_db
    plain = tmp_path / "plain"
    plain.mkdir()
    runtime_flags.mark_unindexable(str(plain), "windows_path_too_long")

    theirs = _run_in_second_process(
        db_path,
        f"""
        from marm_mcp_server.core import runtime_flags
        result = {{
            "blocked": runtime_flags.is_unindexable({str(plain)!r}),
            "listed": runtime_flags.unindexable_watches(),
        }}
        """,
    )
    assert theirs["blocked"] is True
    assert len(theirs["listed"]) == 1


def test_a_vanished_root_is_dropped_and_the_loop_survives(shared_db, tmp_path):
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker, _Watched

    worker = GraphIndexWorker()
    missing = _Watched(str(tmp_path / "does-not-exist"))
    asyncio.run(worker._poll_one(missing))
    assert missing.failed is True


# ── the standalone package ──────────────────────────────────────────


def test_standalone_marm_graph_rejects_the_marm_only_actions():
    """The shared request model carries these actions because FastAPI validates
    into it before the host's endpoint body runs. Without an explicit guard they
    fall through to "repo_path is required", which is actively misleading."""
    from marm_graph.core import tool_router
    from marm_graph.core.models import GraphIndexRequest

    for action in ("auto_on", "auto_off", "auto_status"):
        result = tool_router.do_index(None, GraphIndexRequest(action=action))
        assert result["status"] == "error"
        assert result["error_code"] == "unsupported_action"
        assert "repo_path" not in result["message"]


def test_standalone_stdio_schema_does_not_advertise_the_marm_only_actions():
    """marm-graph cannot perform them, so its own tool schema must not offer them."""
    source = (REPO_ROOT / "marm_graph" / "server_stdio.py").read_text(encoding="utf-8")
    assert "auto_on" not in source


# ── end to end ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_commit_is_picked_up_by_one_poll_cycle(shared_db, git_repo):
    """The exact case detect_changes fails: after a commit it reports clean
    while the graph still lacks every symbol in that commit."""
    from conftest import _CBM_BINARY

    if _CBM_BINARY is None:
        pytest.skip("codebase-memory-mcp binary not available")

    from marm_graph.core import tool_router as R
    from marm_graph.core.models import CodeLookupRequest, GraphIndexRequest
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core.graph_supervisor import graph_supervisor

    if not await asyncio.to_thread(graph_supervisor.is_available):
        pytest.skip("graph engine could not start")
    client = graph_supervisor.get_client()

    indexed = await asyncio.to_thread(
        R.do_index,
        client,
        GraphIndexRequest(action="index", repo_path=str(git_repo), mode="fast"),
    )
    # Surface the engine's own message. A bare status comparison fails as
    # "assert 'error' != 'error'", which says nothing about why.
    assert indexed.get("status") != "error", f"engine refused to index: {indexed}"
    project = indexed["project"]

    (git_repo / "src" / "b.py").write_text("def g_two():\n    return 2\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "add g_two")

    worker = module.GraphIndexWorker()
    state = module._Watched(str(git_repo))
    # The signature as it was at index time, before the commit moved HEAD.
    state.signature = (indexed.get("head") or "pre-commit", False)
    await worker._poll_one(state)
    assert worker._indexed == 1, "a commit must trigger exactly one re-index"

    found = await asyncio.to_thread(
        R.do_lookup,
        client,
        CodeLookupRequest(query="g_two", project=project, kind="symbol"),
    )
    assert "g_two" in json.dumps(found), "the committed symbol must be in the graph"

    await asyncio.to_thread(client.call_tool, "delete_project", {"project": project})


@pytest.mark.asyncio
async def test_the_running_worker_refreshes_a_repo_on_its_own(
    shared_db, git_repo, monkeypatch
):
    """The whole loop, not just one poll: start(), a real list_projects to build
    the watch set, a real re-index through the gate, then stop()."""
    from conftest import _CBM_BINARY

    if _CBM_BINARY is None:
        pytest.skip("codebase-memory-mcp binary not available")

    from marm_graph.core import tool_router as R
    from marm_graph.core.models import GraphIndexRequest
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core.graph_supervisor import graph_supervisor

    if not await asyncio.to_thread(graph_supervisor.is_available):
        pytest.skip("graph engine could not start")
    client = graph_supervisor.get_client()

    indexed = await asyncio.to_thread(
        R.do_index,
        client,
        GraphIndexRequest(action="index", repo_path=str(git_repo), mode="fast"),
    )
    # Surface the engine's own message. A bare status comparison fails as
    # "assert 'error' != 'error'", which says nothing about why.
    assert indexed.get("status") != "error", f"engine refused to index: {indexed}"
    project = indexed["project"]

    monkeypatch.setattr(module, "GRAPH_AUTO_INDEX_INTERVAL", 1)
    worker = module.GraphIndexWorker()
    try:
        worker.start()
        assert worker.running is True

        # First cycle enrolls the repo and re-indexes it once, because this
        # process has no remembered signature for it yet.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and worker._indexed < 1:
            await asyncio.sleep(0.5)
        assert worker._indexed >= 1, "the worker never indexed the enrolled repo"
        # Keyed by whatever list_projects reported, which is not necessarily
        # this platform's spelling of the same directory.
        from marm_mcp_server.core import runtime_flags

        assert runtime_flags.canonical_root(str(git_repo)) in {
            runtime_flags.canonical_root(root) for root in worker._watched
        }

        # A clean repo with an unchanged HEAD must then go quiet.
        settled = worker._indexed
        await asyncio.sleep(3)
        assert worker._indexed == settled, (
            "a clean, unchanged repo must not be re-indexed every cycle"
        )
    finally:
        await worker.stop()
        assert worker.running is False
        await asyncio.to_thread(
            client.call_tool, "delete_project", {"project": project}
        )


# ── review follow-up: cross-process blocks and lease lifetime ────────


@pytest.mark.asyncio
async def test_a_deleted_project_is_skipped_before_the_watch_cache_expires(
    shared_db, tmp_path, monkeypatch
):
    """A delete in the other transport writes only the tombstone. This poller
    holds the root in a watch set it reloads once per TTL, so a check tied to
    that reload left five minutes in which it re-indexed the deleted project."""
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core import runtime_flags

    root_dir = tmp_path / "cached"
    root_dir.mkdir()
    root = str(root_dir)
    attempts = []

    async def indexing(purpose, fn, *args, **kwargs):
        attempts.append(purpose)
        return {"status": "success", "project": "p"}

    monkeypatch.setattr(module, "run_exclusive", indexing)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    worker = module.GraphIndexWorker()
    worker._watched[root] = module._Watched(root)
    # Loaded and not due to reload: exactly the window the bug lived in.
    worker._projects_loaded_at = time.monotonic()

    await worker._cycle()
    assert len(attempts) == 1

    runtime_flags.suppress_watch(root)
    worker._watched[root].last_full = 0.0
    await worker._cycle()
    assert len(attempts) == 1, "the tombstone must stop it with no cache reload"


@pytest.mark.asyncio
async def test_the_gate_outlives_cancellation_of_the_task_that_owns_it(shared_db):
    """Loop teardown cancels every pending task, the lease owner among them.
    Releasing on that cancellation handed the gate to the other transport while
    this process's engine thread was still writing."""
    from marm_mcp_server.core import graph_index_lock as lock

    entered = threading.Event()
    finish = threading.Event()

    def slow_index():
        entered.set()
        finish.wait(10)
        return {"status": "success"}

    before = set(lock._inflight)
    caller = asyncio.create_task(lock.run_exclusive("manual_index:test", slow_index))
    await asyncio.to_thread(entered.wait, 10)
    assert lock.current_holder() is not None

    owner = next(iter(set(lock._inflight) - before))
    owner.cancel()
    for task in (owner, caller):
        with pytest.raises(asyncio.CancelledError):
            await task
    assert lock.current_holder() is not None, (
        "the engine call is still running, so the gate must still be held"
    )

    finish.set()
    for _ in range(200):
        if lock.current_holder() is None:
            break
        await asyncio.sleep(0.05)
    assert lock.current_holder() is None, "and released once the call returns"


def test_a_repository_with_no_commits_is_still_polled(shared_db, tmp_path, monkeypatch):
    """`rev-parse HEAD` fails on an unborn HEAD. Treating that as a git error
    made _poll_one return on every cycle, so a repo indexed before its first
    commit was never refreshed again."""
    from marm_mcp_server.core import graph_index_worker as module

    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "a.py").write_text("def a():\n    return 1\n")

    assert module.git_signature(str(root)) == (module._UNBORN_HEAD, True)

    reasons = []

    async def fake_reindex(state, reason):
        reasons.append(reason)

    worker = module.GraphIndexWorker()
    monkeypatch.setattr(worker, "_reindex", fake_reindex)
    asyncio.run(worker._poll_one(module._Watched(str(root))))
    assert reasons == ["dirty"]


def test_an_unreadable_flag_database_never_authorizes_background_work(
    shared_db, monkeypatch
):
    """A locked database is ordinary and transient. Resolving it to the
    environment default meant a saved "off" authorized indexing and a tombstone
    stopped protecting the project it was written for."""
    from marm_mcp_server.core import runtime_flags

    def broken():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(runtime_flags, "_connection", broken)

    assert runtime_flags.get_bool(runtime_flags.AUTO_INDEX_GRAPH, True) is False
    assert runtime_flags.is_watch_suppressed("/repo/x") is True
    assert runtime_flags.is_unindexable("/repo/x") is True
    assert runtime_flags.index_block("/repo/x") == "unreadable"
    assert runtime_flags.source(runtime_flags.AUTO_INDEX_GRAPH) == "unknown"


@pytest.mark.asyncio
async def test_the_deletion_tombstone_is_written_before_the_gate_is_released(
    shared_db, monkeypatch
):
    """A tombstone written after the gate was released cannot stop an index the
    other transport started in the gap, and the deleted project comes back."""
    from marm_mcp_server.core import graph_index_lock as lock
    from marm_mcp_server.core import runtime_flags
    from marm_mcp_server.endpoints import graph as endpoint

    root = "/repo/doomed"
    seen = {}

    class _Client:
        def call_tool(self, name, args):
            return {"status": "success", "deleted": args["project"]}

    monkeypatch.setattr(endpoint.graph_supervisor, "get_client", lambda: _Client())
    monkeypatch.setattr(endpoint.graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(endpoint, "_project_root_path", lambda project: root)
    monkeypatch.setattr(endpoint, "_cleanup_project_code_links", lambda project: None)

    real = endpoint.run_exclusive

    async def watching(purpose, fn, *args, **kwargs):
        def wrapped(*inner_args, **inner_kwargs):
            outcome = fn(*inner_args, **inner_kwargs)
            seen["held"] = lock.current_holder() is not None
            seen["suppressed"] = runtime_flags.is_watch_suppressed(root)
            return outcome

        return await real(purpose, wrapped, *args, **kwargs)

    monkeypatch.setattr(endpoint, "run_exclusive", watching)
    result = await endpoint.console_delete_project(
        endpoint.ConsoleDeleteProjectRequest(
            project="doomed", name="doomed", confirm=True
        )
    )
    assert result.get("status") != "error"
    assert seen["held"] is True, "observed inside the gate, or the test proves nothing"
    assert seen["suppressed"] is True


@pytest.mark.asyncio
async def test_block_state_is_settled_inside_the_gate_by_every_index_path(
    shared_db, monkeypatch
):
    """Both transports index concurrently by design, so an automatic failure and a
    manual success can release their gates in either order. Settling the blocks
    after release let the loser's write win, and a recovered repository stayed
    marked unindexable in both processes.

    Asserted from inside the gated call rather than by racing two real indexes:
    the ordering is what makes the race unwinnable, and observing the state while
    the lease is provably still held tests exactly that.
    """
    from marm_graph.core.models import GraphIndexRequest
    from marm_mcp_server.core import graph_index_lock as lock
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core import runtime_flags

    root = "/repo/contested"
    observed = {}

    def observe(label):
        observed[label] = {
            "held": lock.current_holder() is not None,
            "unindexable": runtime_flags.is_unindexable(root),
        }

    # The automatic side: a path-limit failure must be durable before release.
    monkeypatch.setattr(
        module.R,
        "do_index",
        lambda client, req: {
            "status": "error",
            "error_code": "windows_path_too_long",
            "hint": "shallower path",
        },
    )

    def failing_then_observe(client, req):
        result = module.index_repository(client, req)
        observe("after_failure")
        return result

    await lock.run_exclusive(
        f"auto_index:{root}",
        failing_then_observe,
        object(),
        GraphIndexRequest(action="index", repo_path=root),
    )
    assert observed["after_failure"] == {"held": True, "unindexable": True}

    # The manual side: the clear must land before its own release, or the write
    # above could arrive afterwards and undo a recovery that already happened.
    monkeypatch.setattr(
        module.R, "do_index", lambda client, req: {"status": "success", "project": "p"}
    )

    def succeeding_then_observe(client, req):
        result = module.index_repository(client, req)
        observe("after_success")
        return result

    await lock.run_exclusive(
        "manual_index:test",
        succeeding_then_observe,
        object(),
        GraphIndexRequest(action="index", repo_path=root),
    )
    assert observed["after_success"] == {"held": True, "unindexable": False}


@pytest.mark.asyncio
async def test_an_automatic_failure_cannot_overwrite_a_manual_recovery(shared_db):
    """The order Codex named: automatic index fails, manual index succeeds and
    clears, then the automatic task writes its marker. With the write inside the
    gate that interleaving cannot occur, because the manual index cannot start
    until the automatic one has released."""
    from marm_graph.core.models import GraphIndexRequest
    from marm_mcp_server.core import graph_index_lock as lock
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core import runtime_flags

    root = "/repo/recovered"
    entered = threading.Event()
    release = threading.Event()
    refused = []

    def slow_failure(client, req):
        entered.set()
        release.wait(10)
        return module.index_repository(client, req)

    original = module.R.do_index
    module.R.do_index = lambda client, req: {
        "status": "error",
        "error_code": "windows_path_too_long",
    }
    try:
        automatic = asyncio.create_task(
            lock.run_exclusive(
                f"auto_index:{root}",
                slow_failure,
                object(),
                GraphIndexRequest(action="index", repo_path=root),
            )
        )
        await asyncio.to_thread(entered.wait, 10)

        # The manual index arrives while the automatic one still holds the gate.
        try:
            await lock.run_exclusive(
                "manual_index:test",
                module.index_repository,
                object(),
                GraphIndexRequest(action="index", repo_path=root),
            )
        except lock.GraphIndexBusy:
            refused.append(True)

        release.set()
        await automatic
        assert refused == [True], "the gate must refuse the overlapping manual index"
        assert runtime_flags.is_unindexable(root) is True

        # Once the gate frees, the manual index succeeds and its clear is final.
        module.R.do_index = lambda client, req: {"status": "success", "project": "p"}
        await lock.run_exclusive(
            "manual_index:test",
            module.index_repository,
            object(),
            GraphIndexRequest(action="index", repo_path=root),
        )
        assert runtime_flags.is_unindexable(root) is False
    finally:
        module.R.do_index = original
