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


def _is_unindexable(root: str) -> bool:
    from marm_mcp_server.core import runtime_flags

    return runtime_flags.index_block(root) is not None


@pytest.fixture
def shared_db(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    load_isolated_server(monkeypatch, tmp_path)
    memory_module = sys.modules["marm_mcp_server.core.memory"]
    return memory_module.memory, tmp_path / "marm_memory.db"


@pytest.fixture(autouse=True)
def _stop_leaked_watchers(monkeypatch):
    """Every GraphIndexWorker built below may start a real watchdog Observer
    thread: _tick enrolls any watch_mode == "disabled" state on its own, and
    that is the default for a state constructed directly rather than through
    _refresh_projects. Track every instance built during the test and stop
    its watcher afterward, rather than relying on each test to remember to."""
    from marm_mcp_server.core import graph_index_worker as module

    built: list = []
    original_init = module.GraphIndexWorker.__init__

    def tracking_init(self, *args, **kwargs):
        built.append(self)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(module.GraphIndexWorker, "__init__", tracking_init)
    yield
    for worker in built:
        worker._watcher.stop()


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


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


def test_signature_moves_on_commit_and_on_edit(git_repo):
    """The two changes a code graph must notice. detect_changes sees only the
    second one, which is why the worker does not use it."""
    from marm_mcp_server.core.graph_index_worker import git_source_state

    base_head, base_hash = git_source_state(str(git_repo))

    (git_repo / "src" / "a.py").write_text("def g_one():\n    return 2\n")
    dirty_head, dirty_hash = git_source_state(str(git_repo))
    assert dirty_head == base_head
    assert dirty_hash != base_hash

    _git(git_repo, "commit", "-aqm", "second")
    committed_head, committed_hash = git_source_state(str(git_repo))
    assert committed_head != base_head, "HEAD must move on commit"
    assert committed_hash != dirty_hash


def test_two_different_edits_to_the_same_dirty_file_produce_different_signatures(
    git_repo,
):
    """The measurement the whole event-driven design rests on. The old (HEAD,
    dirty) signature could not tell these apart, because `git status
    --porcelain` reports which files changed and not what changed in them --
    exactly the gap that forced a dirty repo to re-index on every cycle
    instead of only when something really changed."""
    from marm_mcp_server.core.graph_index_worker import git_source_state

    hashes = []
    for index in range(3):
        (git_repo / "src" / "a.py").write_text(f"def g_one():\n    return 10{index}\n")
        hashes.append(git_source_state(str(git_repo))[1])

    assert len(set(hashes)) == 3, "three different edits must be three different hashes"


def test_staged_unstaged_and_untracked_changes_all_move_the_signature(git_repo):
    """`git diff HEAD` alone covers staged and unstaged changes to tracked
    files; it never shows untracked files at all, which is why the untracked
    fingerprint is a separate half of the signature."""
    from marm_mcp_server.core.graph_index_worker import git_source_state

    base = git_source_state(str(git_repo))[1]

    (git_repo / "src" / "a.py").write_text("def g_one():\n    return 2\n")
    _git(git_repo, "add", "-A")
    staged = git_source_state(str(git_repo))[1]
    assert staged != base

    (git_repo / "src" / "a.py").write_text("def g_one():\n    return 3\n")
    mixed = git_source_state(str(git_repo))[1]
    assert mixed != staged, "an unstaged edit on top of a staged one must also move it"

    _git(git_repo, "commit", "-aqm", "clean up")
    clean = git_source_state(str(git_repo))[1]

    (git_repo / "src" / "new_file.py").write_text("x = 1\n")
    untracked = git_source_state(str(git_repo))[1]
    assert untracked != clean, "a new untracked file must move the signature too"


def test_a_same_length_edit_to_an_untracked_file_moves_the_signature_even_with_a_restored_mtime(
    git_repo,
):
    """The untracked-file fingerprint used to be path:size:mtime, not content.
    A same-length edit landing on an mtime restored to its original value --
    a coarse filesystem clock, a tool that preserves timestamps -- would
    fingerprint identically to the version before it: exactly the staleness
    class the content-hash diff above already fixed for tracked files."""
    from marm_mcp_server.core.graph_index_worker import git_source_state

    target = git_repo / "src" / "untracked.py"
    target.write_text("value = 1\n")
    original_stat = target.stat()
    before = git_source_state(str(git_repo))[1]

    target.write_text("value = 2\n")
    os.utime(target, (original_stat.st_atime, original_stat.st_mtime))
    after = git_source_state(str(git_repo))[1]

    assert after != before, (
        "a content change must move the signature even when size and mtime "
        "are unchanged"
    )


def test_a_same_length_untracked_edit_with_a_restored_mtime_is_not_skipped_by_the_worker(
    shared_db, git_repo, monkeypatch
):
    """The signature moving is necessary but not sufficient: prove the worker
    itself acts on it. A state seeded with the pre-edit baseline, exactly what
    an already-running worker would have recorded from its last evaluation,
    must still trigger a reindex through _evaluate after this exact edit."""
    from marm_mcp_server.core import graph_index_worker as module

    target = git_repo / "src" / "untracked.py"
    target.write_text("value = 1\n")
    original_stat = target.stat()
    baseline = module.git_source_state(str(git_repo))
    assert baseline is not None

    target.write_text("value = 2\n")
    os.utime(target, (original_stat.st_atime, original_stat.st_mtime))

    attempts = []

    async def counting_gate(purpose, fn, *args, **kwargs):
        attempts.append(purpose)
        return {"status": "success", "project": "p"}

    monkeypatch.setattr(module, "run_exclusive", counting_gate)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )

    state = module._Watched(str(git_repo))
    state.git_head, state.content_hash = baseline

    asyncio.run(module.GraphIndexWorker()._evaluate(state))
    assert len(attempts) == 1, (
        "a same-length untracked edit with a restored mtime must still "
        "trigger a reindex, not be skipped as unchanged"
    )


def test_an_ignored_file_does_not_move_the_signature(git_repo):
    """The engine remains the ignore-policy owner; this signature must not
    react to churn in build output or dependency directories."""
    from marm_mcp_server.core.graph_index_worker import git_source_state

    (git_repo / ".gitignore").write_text("ignored/\n")
    _git(git_repo, "add", ".gitignore")
    _git(git_repo, "commit", "-qm", "add gitignore")
    (git_repo / "ignored").mkdir()

    base = git_source_state(str(git_repo))[1]
    (git_repo / "ignored" / "build.log").write_text("noise\n")
    after = git_source_state(str(git_repo))[1]
    assert after == base


def test_a_branch_switch_moves_the_signature(git_repo):
    """A checkout is exactly the kind of change detect_changes cannot see
    either, since the working tree can end up identical to how it started."""
    from marm_mcp_server.core.graph_index_worker import git_source_state

    base_head = git_source_state(str(git_repo))[0]
    _git(git_repo, "checkout", "-qb", "other")
    (git_repo / "src" / "a.py").write_text("def g_one():\n    return 99\n")
    _git(git_repo, "commit", "-aqm", "on other branch")
    _git(git_repo, "checkout", "-q", "-")

    back = git_source_state(str(git_repo))[0]
    assert back == base_head, "back on the original branch, HEAD is unchanged"

    _git(git_repo, "checkout", "-q", "other")
    switched = git_source_state(str(git_repo))[0]
    assert switched != base_head


def test_git_failure_reads_as_no_change(tmp_path):
    """A broken or non-repo path must not re-index on every single evaluation."""
    from marm_mcp_server.core.graph_index_worker import git_source_state, is_git_repo

    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_git_repo(str(plain)) is False
    assert git_source_state(str(plain)) is None


def test_a_non_repo_never_reports_an_ancestor_repos_signature(git_repo):
    """Git's repository discovery walks upward from -C. A subdirectory that is
    not itself a repo must not report the enclosing repo's HEAD and content
    state, or it would re-index whenever anything anywhere in that parent
    changed.

    This is also why the assertion above cannot depend on pytest's temp
    directory happening to sit outside every git repository.
    """
    from marm_mcp_server.core.graph_index_worker import git_source_state, is_git_repo

    nested = git_repo / "src" / "not_a_repo"
    nested.mkdir()
    assert git_source_state(str(git_repo)) is not None, "the real repo still answers"

    assert is_git_repo(str(nested)) is False
    assert git_source_state(str(nested)) is None

    (git_repo / "src" / "a.py").write_text("def g_one():\n    return 42\n")
    assert git_source_state(str(nested)) is None


def test_core_fsmonitor_from_the_polled_repo_is_never_executed(git_repo, tmp_path):
    """core.fsmonitor names a program git will run, read from the watched repo's
    own config. Evaluating a user-chosen repository must not invoke it, even
    though a watcher now triggers evaluation far more often than a 30s poll did."""
    from marm_mcp_server.core.graph_index_worker import git_source_state

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
    assert git_source_state(str(git_repo)) is not None
    assert not sentinel.exists(), "core.fsmonitor was executed"


def test_git_runs_with_a_scrubbed_environment(git_repo, monkeypatch, tmp_path):
    """An inherited GIT_DIR belongs to whatever launched the server, and would
    point our -C at a different repository entirely."""
    from marm_mcp_server.core.graph_index_worker import git_source_state

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("GIT_DIR", str(other))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))

    assert git_source_state(str(git_repo)) is not None


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
        lambda command, **kwargs: (
            captured.update(command=command, **kwargs) or Completed()
        ),
    )

    assert module._git("C:/repo", "rev-parse", "HEAD") == "ok"
    assert captured["creationflags"] == 123


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
    await asyncio.sleep(2.5)

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
    asyncio.run(worker._tick())

    assert touched == []
    assert worker.status()["enabled"] is False


def test_concept_auto_index_honors_the_same_override(shared_db):
    from marm_mcp_server.core import runtime_flags
    from marm_mcp_server.core.concept_worker import concept_worker

    assert concept_worker.enabled() is True
    runtime_flags.set_bool(runtime_flags.AUTO_INDEX_CONCEPT, False)
    assert concept_worker.enabled() is False


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

    runtime_flags.unsuppress_watch("/repo/gone")
    worker._projects_loaded_at = None
    asyncio.run(worker._refresh_projects())
    assert set(worker._watched) == {"/repo/keep", "/repo/gone"}


def test_a_non_git_project_reindexes_only_when_due(shared_db, tmp_path, monkeypatch):
    """A non-git root has no cheap signature, so any trigger -- a debounced
    watcher event or the reconcile deadline -- means an unconditional
    reindex. Due-ness itself is _tick's gate, not _evaluate's: a directory
    that was never a repo must not reindex on every tick regardless."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()

    reindexed = []

    async def record(target, reason, candidate_git_state=None):
        reindexed.append(reason)

    monkeypatch.setattr(worker, "_reindex", record)
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    asyncio.run(worker._tick())
    assert reindexed == ["filesystem_changed"]

    asyncio.run(worker._tick())
    assert reindexed == ["filesystem_changed"]

    state.reconcile_deadline = time.monotonic() - 1
    asyncio.run(worker._tick())
    assert reindexed == ["filesystem_changed", "filesystem_changed"]


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


def test_a_failing_non_git_project_does_not_retry_before_its_deadline(
    shared_db, tmp_path, monkeypatch
):
    """A non-git project's only gate is its reconcile deadline. Leaving that at
    its old value on failure made a broken one re-index every tick, taking the
    engine gate each time."""
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
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()

    asyncio.run(worker._tick())
    assert len(attempts) == 1

    asyncio.run(worker._tick())
    asyncio.run(worker._tick())
    assert len(attempts) == 1, "a failure must still occupy the slow lane"

    state.reconcile_deadline = time.monotonic() - 1
    asyncio.run(worker._tick())
    assert len(attempts) == 2


def test_a_failed_index_on_a_clean_repo_retries_after_a_backoff(
    shared_db, git_repo, monkeypatch
):
    """retry_after governs whether an unchanged evaluation retries; it never
    blocks a real change, which is retried the moment something notices it --
    a debounced watcher event in production, forced here directly since
    nothing is really watching this call."""
    from marm_mcp_server.core import graph_index_worker as module

    attempts = []

    async def failing(purpose, fn, *args, **kwargs):
        attempts.append(purpose)
        return {"status": "error", "message": "boom"}

    monkeypatch.setattr(module, "run_exclusive", failing)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    worker = module.GraphIndexWorker()
    state = module._Watched(str(git_repo))
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()

    asyncio.run(worker._tick())
    assert len(attempts) == 1
    assert state.retry_after > 0

    asyncio.run(worker._tick())
    assert len(attempts) == 1

    state.reconcile_deadline = time.monotonic() - 1
    asyncio.run(worker._tick())
    assert len(attempts) == 1

    state.retry_after = time.monotonic() - 1
    state.reconcile_deadline = time.monotonic() - 1
    asyncio.run(worker._tick())
    assert len(attempts) == 2

    state.retry_after = time.monotonic() + 10_000
    state.debounce_deadline = time.monotonic() - 1
    (git_repo / "src" / "b.py").write_text("def g_two():\n    return 2\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "second")
    asyncio.run(worker._tick())
    assert len(attempts) == 3, "a changed repo must not wait out the backoff"


def test_an_unindexable_path_is_not_retried_at_all(shared_db, tmp_path, monkeypatch):
    """Deterministic failures must stop, or the poller holds the engine gate
    forever to re-learn the same thing."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    attempts = []

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

    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    asyncio.run(worker._evaluate(state))
    assert len(attempts) == 1
    assert _is_unindexable(str(plain)) is True

    state.reconcile_deadline = time.monotonic() - 1
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )
    asyncio.run(worker._tick())
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

    asyncio.run(worker._tick())
    assert attempts == [], "the marker must keep the worker off it"

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
    assert _is_unindexable(root) is False

    before = len(attempts)
    asyncio.run(worker._tick())
    assert len(attempts) == before + 1, (
        "polling must resume on the next tick, with no restart"
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
            "blocked": runtime_flags.index_block({str(plain)!r}) is not None,
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
    asyncio.run(worker._evaluate(missing))
    assert missing.failed is True


def test_a_failed_root_does_not_pin_the_coordinator_at_a_zero_second_wake(
    shared_db, tmp_path
):
    """A failed root never reaches _evaluate again, so its reconcile_deadline
    never advances past the -inf it starts at. Left in _next_wake_delay's
    aggregation, that -inf would win the min() forever and spin the
    coordinator at 0.0 with no sleep between ticks."""
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker, _Watched

    worker = GraphIndexWorker()
    missing = _Watched(str(tmp_path / "does-not-exist"))
    asyncio.run(worker._evaluate(missing))
    assert missing.failed is True

    worker._watched[missing.root] = missing
    worker._ticked_once = True
    assert worker._next_wake_delay() > 0.0, (
        "a failed root must not pin the coordinator's wake delay at 0.0"
    )


def test_a_blocked_root_does_not_pin_the_coordinator_either(shared_db, tmp_path):
    """The other never-evaluated path: runtime_flags.index_block keeps
    skipping _evaluate for a suppressed or unindexable root, so its
    reconcile_deadline also stays at -inf forever. _tick() must still
    re-check the block on every real tick -- that is how a manual index
    clearing it is noticed without a restart -- so the fix must live in
    _next_wake_delay's aggregation, not in the state itself."""
    from marm_mcp_server.core import runtime_flags
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker, _Watched

    plain = tmp_path / "plain"
    plain.mkdir()
    root = str(plain)
    runtime_flags.mark_unindexable(root, "windows_path_too_long")

    worker = GraphIndexWorker()
    state = _Watched(root)
    worker._watched[state.root] = state
    worker._ticked_once = True
    assert state.reconcile_deadline == float("-inf"), (
        "never evaluated: the block always skips it before _evaluate runs"
    )
    assert worker._next_wake_delay() > 0.0, (
        "a permanently blocked root must not pin the coordinator's wake delay at 0.0"
    )


def test_a_blocked_root_with_an_elapsed_debounce_deadline_still_does_not_pin_the_coordinator(
    shared_db, tmp_path, monkeypatch
):
    """_on_watch_event sets debounce_deadline independent of the block -- the
    watch stays live on a blocked root, since _enroll_watch does not consult
    index_block. Once that deadline elapses it is just as sharp an -inf as
    reconcile_deadline once elapsed, so leaving it in _tick's index_block skip
    path reopens the exact loop the reconcile_deadline fix closed, just
    through the other deadline."""
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core import runtime_flags

    plain = tmp_path / "plain"
    plain.mkdir()
    root = str(plain)
    runtime_flags.mark_unindexable(root, "windows_path_too_long")

    worker = module.GraphIndexWorker()
    state = module._Watched(root)
    state.debounce_deadline = time.monotonic() - 1
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    asyncio.run(worker._tick())
    assert state.debounce_deadline is None, (
        "a consumed debounce event on a blocked root must not linger in the past"
    )
    assert worker._next_wake_delay() > 0.0, (
        "an elapsed debounce deadline on a blocked root must not pin the "
        "coordinator's wake delay at 0.0 either"
    )


def test_a_fresh_debounce_event_during_the_block_check_survives(
    shared_db, tmp_path, monkeypatch
):
    """index_block runs behind a real await (asyncio.to_thread), and a
    watcher event can land on this exact root while it is in flight. This
    root was indexed once already, so reconcile_deadline is a genuine future
    timestamp rather than -inf: clobbering the fresh debounce_deadline
    unconditionally would leave nothing to make it due again until the far-off
    reconcile pass, minutes later, silently losing the change."""
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core import runtime_flags

    plain = tmp_path / "plain"
    plain.mkdir()
    root = str(plain)
    runtime_flags.mark_unindexable(root, "windows_path_too_long")

    worker = module.GraphIndexWorker()
    state = module._Watched(root)
    state.reconcile_deadline = time.monotonic() + 300
    state.debounce_deadline = time.monotonic() - 1
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    fresh_deadline = time.monotonic() + 999

    def blocked_with_a_concurrent_event(root_path):
        state.debounce_deadline = fresh_deadline
        return "unindexable"

    monkeypatch.setattr(runtime_flags, "index_block", blocked_with_a_concurrent_event)

    asyncio.run(worker._tick())
    assert state.debounce_deadline == fresh_deadline, (
        "a debounce deadline set while the block check was in flight must survive"
    )


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
    assert indexed.get("status") != "error", f"engine refused to index: {indexed}"
    project = indexed["project"]

    (git_repo / "src" / "b.py").write_text("def g_two():\n    return 2\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "add g_two")

    worker = module.GraphIndexWorker()
    state = module._Watched(str(git_repo))
    state.git_head = indexed.get("head") or "pre-commit"
    state.content_hash = "pre-commit"
    await worker._evaluate(state)
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
    assert indexed.get("status") != "error", f"engine refused to index: {indexed}"
    project = indexed["project"]

    from marm_mcp_server.core import runtime_flags

    watched_root = runtime_flags.canonical_root(str(git_repo))
    worker = module.GraphIndexWorker()
    try:
        worker.start()
        assert worker.running is True

        deadline = time.monotonic() + 30
        state = None
        while time.monotonic() < deadline:
            state = next(
                (
                    candidate
                    for root, candidate in worker._watched.items()
                    if runtime_flags.canonical_root(root) == watched_root
                ),
                None,
            )
            if state is not None and state.last_indexed is not None:
                break
            await asyncio.sleep(0.5)
        assert state is not None and state.last_indexed is not None, (
            "the worker never indexed the enrolled repo"
        )
        assert watched_root in {
            runtime_flags.canonical_root(root) for root in worker._watched
        }

        settled = state.last_indexed
        await asyncio.sleep(3)
        assert state.last_indexed == settled, (
            "a clean, unchanged repo must not be re-indexed every cycle"
        )
    finally:
        await worker.stop()
        assert worker.running is False
        await asyncio.to_thread(
            client.call_tool, "delete_project", {"project": project}
        )


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
    worker._projects_loaded_at = time.monotonic()

    await worker._tick()
    assert len(attempts) == 1

    runtime_flags.suppress_watch(root)
    worker._watched[root].reconcile_deadline = time.monotonic() - 1
    await worker._tick()
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
    made _evaluate return on every tick, so a repo indexed before its first
    commit was never refreshed again."""
    from marm_mcp_server.core import graph_index_worker as module

    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "a.py").write_text("def a():\n    return 1\n")

    state = module.git_source_state(str(root))
    assert state is not None
    assert state[0] == module._UNBORN_HEAD

    reasons = []

    async def fake_reindex(state, reason, candidate_git_state=None):
        reasons.append(reason)

    worker = module.GraphIndexWorker()
    monkeypatch.setattr(worker, "_reindex", fake_reindex)
    asyncio.run(worker._evaluate(module._Watched(str(root))))
    assert reasons == ["worktree_changed"]


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
    assert _is_unindexable("/repo/x") is True
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

    root = "/repo/contested"
    observed = {}

    def observe(label):
        observed[label] = {
            "held": lock.current_holder() is not None,
            "unindexable": _is_unindexable(root),
        }

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
        assert _is_unindexable(root) is True

        module.R.do_index = lambda client, req: {"status": "success", "project": "p"}
        await lock.run_exclusive(
            "manual_index:test",
            module.index_repository,
            object(),
            GraphIndexRequest(action="index", repo_path=root),
        )
        assert _is_unindexable(root) is False
    finally:
        module.R.do_index = original


def test_a_burst_of_watcher_events_coalesces_into_one_debounce_deadline(
    shared_db, tmp_path
):
    """The deadline is only ever pushed forward by each event, never queued
    separately, so a burst of saves collapses into the single evaluation that
    runs once the deadline finally holds still."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    worker._watched[state.root] = state

    for _ in range(5):
        worker._on_watch_event(state.root)
    assert state.generation == 5
    first_deadline = state.debounce_deadline
    assert first_deadline is not None

    worker._on_watch_event(state.root)
    assert state.generation == 6
    assert state.debounce_deadline >= first_deadline, (
        "a later event must not schedule an earlier evaluation"
    )


def test_a_burst_of_events_produces_one_reindex_not_several(
    shared_db, tmp_path, monkeypatch
):
    """Integration-level companion to the coalescing test above: a burst that
    never lets the debounce deadline settle must not evaluate at all, and
    settling it must evaluate exactly once."""
    from marm_mcp_server.core import graph_index_worker as module

    monkeypatch.setattr(module, "GRAPH_AUTO_INDEX_DEBOUNCE_SECONDS", 0.3)
    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    state.reconcile_deadline = time.monotonic() + 1000
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()

    reindexed = []

    async def record(target, reason, candidate_git_state=None):
        reindexed.append(reason)

    monkeypatch.setattr(worker, "_reindex", record)
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    for _ in range(5):
        worker._on_watch_event(state.root)
        asyncio.run(worker._tick())
    assert reindexed == [], "the burst must not evaluate before the debounce settles"

    time.sleep(0.35)
    asyncio.run(worker._tick())
    assert reindexed == ["filesystem_changed"], (
        "settling the burst evaluates exactly once"
    )


@pytest.mark.asyncio
async def test_an_event_during_an_in_flight_index_leaves_exactly_one_pending_pass(
    shared_db, tmp_path, monkeypatch
):
    """An event that lands while the engine call is still running must not
    start a competing index; it must be visible as exactly one pending
    catch-up once the in-flight call returns."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    worker._watched[state.root] = state

    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_reindex(target, reason, candidate_git_state=None):
        entered.set()
        await release.wait()

    monkeypatch.setattr(worker, "_reindex", slow_reindex)

    evaluation = asyncio.create_task(worker._evaluate(state))
    await asyncio.wait_for(entered.wait(), timeout=5)

    worker._on_watch_event(state.root)
    assert state.generation != state.evaluated_generation

    release.set()
    await evaluation

    assert state.generation != state.evaluated_generation, (
        "the late event must still be visible as a pending pass"
    )
    assert state.debounce_deadline is not None, (
        "exactly one catch-up must be scheduled, not zero and not a busy loop"
    )


def test_read_only_watchdog_events_are_not_forwarded(shared_db):
    """Linux's inotify backend also emits "opened" and "closed_no_write" for a
    plain read, with no content change. Forwarding those would make a non-git
    root -- which has no signature check and reindexes unconditionally on any
    trigger -- re-index itself every debounce window from nothing but reads
    under the watched root, including the graph engine's own reads while
    indexing it."""
    from watchdog.events import (
        FileClosedNoWriteEvent,
        FileCreatedEvent,
        FileModifiedEvent,
        FileOpenedEvent,
    )

    from marm_mcp_server.core.graph_index_watcher import _RootHandler

    class _ImmediateLoop:
        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

    seen = []
    handler = _RootHandler(
        "/some/root", _ImmediateLoop(), lambda root: seen.append(root)
    )

    handler.on_any_event(FileOpenedEvent("/some/root/a.py"))
    handler.on_any_event(FileClosedNoWriteEvent("/some/root/a.py"))
    assert seen == [], "read-only events must not wake the coordinator"

    handler.on_any_event(FileModifiedEvent("/some/root/a.py"))
    handler.on_any_event(FileCreatedEvent("/some/root/b.py"))
    assert seen == ["/some/root", "/some/root"], "real changes must still be forwarded"


def test_a_watch_failure_for_one_root_falls_back_to_reconcile(
    shared_db, tmp_path, monkeypatch
):
    """A permissions error or a watch-count limit on a single root must not
    take the whole worker down with it; that root simply relies on the
    reconcile deadline instead of events."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    monkeypatch.setattr(worker._watcher, "watch", lambda root, callback: False)

    state = module._Watched(str(plain))
    worker._enroll_watch(state)
    assert state.watch_mode == "reconcile_fallback"


def test_a_globally_unavailable_watcher_marks_roots_unavailable(shared_db, tmp_path):
    """When the observer subsystem itself cannot start at all, every root must
    say so distinctly from a single root's own watch failure."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    worker._watcher._globally_unavailable = True

    state = module._Watched(str(plain))
    worker._enroll_watch(state)
    assert state.watch_mode == "unavailable"


def test_a_reconcile_fallback_root_still_reindexes_unconditionally(
    shared_db, tmp_path, monkeypatch
):
    """A non-git root that could not be watched has no cheap signature and no
    events either, so the reconcile deadline is its only trigger -- and it
    must still fire."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    state.watch_mode = "reconcile_fallback"
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()

    reindexed = []

    async def record(target, reason, candidate_git_state=None):
        reindexed.append(reason)

    monkeypatch.setattr(worker, "_reindex", record)
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    asyncio.run(worker._tick())
    assert reindexed == ["reconcile"]


@pytest.mark.asyncio
async def test_disabling_detaches_watches_and_the_next_tick_reactivates_them(
    shared_db, tmp_path, monkeypatch
):
    """auto_off must not leave filesystem observers running; the next tick
    after auto_on brings them back without a restart."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    worker._watched[state.root] = state
    worker._enroll_watch(state)
    assert state.watch_mode != "disabled"

    worker._deactivate()
    assert state.watch_mode == "disabled"
    assert state.debounce_deadline is None

    worker._projects_loaded_at = time.monotonic()
    state.reconcile_deadline = time.monotonic() + 1000
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )
    await worker._tick()
    assert state.watch_mode != "disabled", (
        "the next tick must re-enroll a reactivated root"
    )


@pytest.mark.asyncio
async def test_wake_cuts_a_long_wait_short(shared_db):
    """The idle poll and reconcile deadline can be minutes away; wake() must
    let a caller who just wants prompt action skip the rest of that wait."""
    from marm_mcp_server.core.graph_index_worker import GraphIndexWorker

    worker = GraphIndexWorker()
    started = time.monotonic()
    waiting = asyncio.create_task(worker._wait(60))
    await asyncio.sleep(0.05)

    worker.wake()
    stopped = await asyncio.wait_for(waiting, timeout=2)
    assert stopped is False, "a wake is not a stop"
    assert time.monotonic() - started < 2


def test_auto_on_wakes_the_worker(shared_db, monkeypatch):
    """auto_on must not leave a caller waiting out the idle poll to see
    auto-indexing come back to life."""
    from marm_mcp_server.core.graph_index_worker import auto_action, graph_index_worker

    woken = []
    monkeypatch.setattr(graph_index_worker, "wake", lambda: woken.append(True))
    monkeypatch.setattr(graph_index_worker, "start", lambda: None)

    auto_action("auto_on")
    assert woken == [True]


def test_watch_state_round_trips_through_the_database(shared_db):
    """The durable baseline: source kind, opaque digest, last index time and
    reason, and watch mode, keyed canonically like the other durable state."""
    from marm_mcp_server.core import runtime_flags

    root = "C:/repo/round-trip" if os.name == "nt" else "/repo/round-trip"
    assert runtime_flags.get_watch_state(root) is None

    runtime_flags.save_watch_state(
        root,
        source_kind="git",
        last_source_state="abc123:def456",
        last_indexed="2026-01-01T00:00:00+00:00",
        last_index_reason="worktree_changed",
        watch_status="git_events",
    )
    assert runtime_flags.get_watch_state(root) == {
        "source_kind": "git",
        "last_source_state": "abc123:def456",
        "last_indexed": "2026-01-01T00:00:00+00:00",
        "last_index_reason": "worktree_changed",
        "watch_status": "git_events",
    }

    runtime_flags.save_watch_state(
        root,
        source_kind="git",
        last_source_state="new111:new222",
        last_indexed="2026-01-02T00:00:00+00:00",
        last_index_reason="head_moved",
        watch_status="git_events",
    )
    assert runtime_flags.get_watch_state(root)["last_source_state"] == "new111:new222"

    other_spelling = "C:\\repo\\round-trip" if os.name == "nt" else "/repo/round-trip/"
    assert (
        runtime_flags.get_watch_state(other_spelling)["last_index_reason"]
        == "head_moved"
    )


@pytest.mark.asyncio
async def test_a_restart_does_not_reindex_an_unchanged_project(
    shared_db, git_repo, monkeypatch
):
    """A durable baseline that already matches the repo's current state must
    stop a freshly created worker -- standing in for a restart, or the other
    transport enrolling this root first -- from re-indexing solely because
    its in-memory state was recreated."""
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core import runtime_flags

    root = str(git_repo)
    head, content_hash = module.git_source_state(root)
    runtime_flags.save_watch_state(
        root,
        source_kind="git",
        last_source_state=f"{head}:{content_hash}",
        last_indexed="2026-01-01T00:00:00+00:00",
        last_index_reason="worktree_changed",
        watch_status="git_events",
    )

    listed = {"status": "success", "projects": [{"name": "p", "root_path": root}]}
    monkeypatch.setattr(module.R, "do_index", lambda client, req: listed)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    reindexed = []

    async def record(target, reason, candidate_git_state=None):
        reindexed.append(reason)

    worker = module.GraphIndexWorker()
    monkeypatch.setattr(worker, "_reindex", record)

    await worker._tick()
    assert reindexed == [], (
        "an unchanged project must not be re-indexed after a restart"
    )

    seeded = worker._watched[root]
    assert seeded.git_head == head
    assert seeded.content_hash == content_hash


def test_auto_status_reports_the_event_driven_fields_without_starting_the_engine(
    shared_db, tmp_path
):
    """The status an operator actually reads: what mode each project is
    watched under, its opaque baseline, why it last indexed, and whether a
    debounced event or catch-up pass is still waiting."""
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core.graph_supervisor import graph_supervisor

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    state.watch_mode = "filesystem_events"
    state.last_indexed = "2026-01-01T00:00:00+00:00"
    state.last_index_reason = "filesystem_changed"
    state.generation = 2
    state.evaluated_generation = 1
    worker._watched[state.root] = state

    assert graph_supervisor.snapshot()["started"] is False
    status = worker.status()
    assert graph_supervisor.snapshot()["started"] is False, (
        "reading status must not start the engine"
    )

    assert status["debounce_seconds"] == module.GRAPH_AUTO_INDEX_DEBOUNCE_SECONDS
    assert status["reconcile_seconds"] == module.GRAPH_AUTO_INDEX_RECONCILE_SECONDS
    project = status["projects"][0]
    assert project["watch_mode"] == "filesystem_events"
    assert project["last_indexed"] == "2026-01-01T00:00:00+00:00"
    assert project["last_index_reason"] == "filesystem_changed"
    assert project["pending"] is True, "generation ahead of evaluated_generation"


@pytest.mark.asyncio
async def test_stop_leaves_no_live_observer_thread(shared_db, tmp_path):
    """A watcher thread that outlives worker.stop() would keep watching a
    project the worker itself no longer knows about."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    worker._watched[state.root] = state
    worker._enroll_watch(state)
    observer = worker._watcher._observer
    assert observer is not None and observer.is_alive()

    await worker.stop()
    assert not observer.is_alive(), "stop() must tear down the observer thread"


def test_the_worker_does_not_busy_loop_when_the_engine_stays_unavailable(
    shared_db, monkeypatch
):
    """_tick must record that it ran even when it bails out immediately, or
    _next_wake_delay keeps handing back 0.0 forever -- which is what a fresh
    install with the engine binary not yet downloaded looks like, since
    _refresh_projects (the only setter of _projects_loaded_at) is never
    reached while the engine is unavailable."""
    from marm_mcp_server.core import graph_index_worker as module

    worker = module.GraphIndexWorker()
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": False}
    )

    assert worker._next_wake_delay() == 0.0, (
        "the very first tick is still owed immediately"
    )
    asyncio.run(worker._tick())
    assert worker._projects_loaded_at is None, (
        "the engine never became available to list from"
    )
    assert worker._next_wake_delay() > 0.0, (
        "a second tick must not also get a 0.0 delay with the engine still down"
    )


@pytest.mark.asyncio
async def test_a_watcher_event_wakes_a_sleeping_coordinator(shared_db, tmp_path):
    """A worker asleep toward a five-minute reconcile deadline must not stay
    asleep through a debounce window that starts well before it -- that is
    strictly worse than the fixed poll this design replaced."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    state.reconcile_deadline = time.monotonic() + 1000
    worker._watched[state.root] = state

    started = time.monotonic()
    waiting = asyncio.create_task(worker._wait(60))
    await asyncio.sleep(0.05)

    worker._on_watch_event(state.root)
    stopped = await asyncio.wait_for(waiting, timeout=2)
    assert stopped is False
    assert time.monotonic() - started < 2, "the event must cut the sleep short"


def test_auto_off_also_wakes_the_worker(shared_db, monkeypatch):
    """A worker sleeping toward its reconcile deadline must not keep
    filesystem observers running for however long that sleep still has left;
    _deactivate is only reached on the coordinator's next wake."""
    from marm_mcp_server.core.graph_index_worker import auto_action, graph_index_worker

    woken = []
    monkeypatch.setattr(graph_index_worker, "wake", lambda: woken.append(True))

    auto_action("auto_off")
    assert woken == [True]


def test_an_unborn_repo_sees_an_unstaged_edit_to_an_already_staged_file(tmp_path):
    """`git diff --cached` alone reflects the index, not the working tree, and
    the file is no longer "untracked" once staged either -- both halves of the
    unborn signature miss this without the extra working-tree diff."""
    from marm_mcp_server.core.graph_index_worker import git_source_state

    root = tmp_path / "unborn"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "a.py").write_text("x = 1\n")
    _git(root, "add", "a.py")

    staged_only = git_source_state(str(root))[1]

    (root / "a.py").write_text("x = 2\n")
    with_unstaged_edit = git_source_state(str(root))[1]

    assert with_unstaged_edit != staged_only


@pytest.mark.asyncio
async def test_a_refused_lease_does_not_advance_the_in_memory_baseline(
    shared_db, git_repo, monkeypatch
):
    """A GraphIndexBusy refusal means this process never actually indexed
    anything. It must not be recorded as though it had, or the next
    evaluation of an unchanged repo reads as "nothing to do" even though this
    process's own graph may still be stale."""
    from marm_mcp_server.core import graph_index_worker as module
    from marm_mcp_server.core.graph_index_lock import GraphIndexBusy

    async def refused(*args, **kwargs):
        raise GraphIndexBusy("auto_index")

    monkeypatch.setattr(module, "run_exclusive", refused)

    worker = module.GraphIndexWorker()
    state = module._Watched(str(git_repo))
    worker._watched[state.root] = state
    worker._projects_loaded_at = time.monotonic()
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    await worker._tick()
    assert state.git_head is None, "a refused lease must not advance the baseline"
    assert state.content_hash is None

    state.reconcile_deadline = time.monotonic() - 1
    attempts = []

    async def succeeding(purpose, fn, *args, **kwargs):
        attempts.append(purpose)
        return {"status": "success", "project": "p"}

    monkeypatch.setattr(module, "run_exclusive", succeeding)
    await worker._tick()
    assert len(attempts) == 1, "the repo must still be retried after the refusal"
    assert state.git_head is not None, "a real success is what advances the baseline"


@pytest.mark.asyncio
async def test_a_dead_observer_thread_is_detected_and_recovered(
    shared_db, tmp_path, monkeypatch
):
    """The one shared observer backs every root. If its thread dies after a
    successful start -- not a setup failure, which watch() already handles
    per root -- reconciliation still protects correctness, but nothing
    previously noticed the silent degradation from event-driven back to
    poll-only. The next tick must detect it and rebuild a fresh observer."""
    from marm_mcp_server.core import graph_index_worker as module

    plain = tmp_path / "plain"
    plain.mkdir()
    worker = module.GraphIndexWorker()
    state = module._Watched(str(plain))
    worker._watched[state.root] = state
    worker._enroll_watch(state)
    assert state.watch_mode == "filesystem_events"
    dead_observer = worker._watcher._observer
    assert worker._watcher.healthy() is True

    dead_observer.stop()
    dead_observer.join(timeout=5)
    assert not dead_observer.is_alive()
    assert worker._watcher.healthy() is False

    state.reconcile_deadline = time.monotonic() + 1000
    worker._projects_loaded_at = time.monotonic()
    monkeypatch.setattr(
        module.graph_supervisor, "snapshot", lambda: {"available": True}
    )

    try:
        await worker._tick()
        assert worker._watcher.healthy() is True
        assert worker._watcher._observer is not dead_observer, (
            "a fresh observer must replace the dead one"
        )
        assert state.watch_mode == "filesystem_events", (
            "the affected root must be re-enrolled"
        )
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_an_ordinary_failure_still_advances_the_baseline_for_backoff(
    shared_db, git_repo, monkeypatch
):
    """Unlike a lease refusal, an ordinary engine failure means the attempt
    genuinely happened. The observed state must still become the comparison
    baseline, or retry_after's backoff is unreachable: an unchanged repo
    whose baseline never advances always looks like the first observation
    and retries immediately regardless of any backoff."""
    from marm_mcp_server.core import graph_index_worker as module

    async def failing(purpose, fn, *args, **kwargs):
        return {"status": "error", "message": "boom"}

    monkeypatch.setattr(module, "run_exclusive", failing)
    monkeypatch.setattr(
        module.graph_supervisor, "get_client", lambda: object(), raising=False
    )

    worker = module.GraphIndexWorker()
    state = module._Watched(str(git_repo))
    await worker._evaluate(state)
    assert state.git_head is not None, (
        "an attempted-but-failed index must still record what was observed"
    )
