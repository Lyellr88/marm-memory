"""Tests for the graph engine's test-sandbox lifecycle in conftest.

The sandbox is the engine's HOME for a test session, so a sweep that removes the
wrong directory deletes a running session's graph store rather than leaking disk.
"""

import os
import time

from conftest import (
    _STALE_SANDBOX_AGE_SECONDS,
    _sandbox_last_active,
    _sweep_stale_sandboxes,
)


def _sandbox(root, name, idle_for):
    """A sandbox where nothing has been written for `idle_for` seconds.

    Every path in the tree is aged, not just the top directory, because that is
    what an abandoned sandbox looks like: writes stop when the session dies and
    every mtime freezes together.
    """
    path = root / name
    store = path / ".cache" / "codebase-memory-mcp"
    store.mkdir(parents=True)
    (store / "store.db").write_text("x", encoding="utf-8")
    stamp = time.time() - idle_for
    for entry in [*path.rglob("*"), path]:
        os.utime(entry, (stamp, stamp))
    return path


def _touch(path):
    """Mark recent engine activity deep inside a sandbox."""
    marker = path / ".cache" / "codebase-memory-mcp" / "store.db"
    now = time.time()
    os.utime(marker, (now, now))


def test_sweep_removes_a_sandbox_no_one_is_using(tmp_path):
    old = _sandbox(tmp_path, "cbm-home-abandoned", _STALE_SANDBOX_AGE_SECONDS + 60)

    _sweep_stale_sandboxes(tmp_path)

    assert not old.exists()


def test_sweep_keeps_a_long_running_session_that_is_still_writing(tmp_path):
    """The case the directory mtime alone gets wrong.

    A session that has run past the cutoff has a sandbox directory whose own
    mtime is still its creation time, because the engine writes several levels
    down and that does not touch the directory. Sweeping on the directory's mtime
    would delete the home of a session that is actively using it.
    """
    active = _sandbox(tmp_path, "cbm-home-long-run", _STALE_SANDBOX_AGE_SECONDS + 3600)
    _touch(active)

    _sweep_stale_sandboxes(tmp_path)

    assert active.exists()
    assert (active / ".cache" / "codebase-memory-mcp" / "store.db").exists()


def test_last_active_reads_deeper_than_the_sandbox_directory(tmp_path):
    path = _sandbox(tmp_path, "cbm-home-deep", _STALE_SANDBOX_AGE_SECONDS + 3600)
    _touch(path)

    assert path.stat().st_mtime < _sandbox_last_active(path)


def test_sweep_ignores_directories_it_did_not_create(tmp_path):
    """Only this fixture's own sandboxes, whatever else shares the root."""
    unrelated = tmp_path / "not-a-sandbox"
    unrelated.mkdir()
    stamp = time.time() - _STALE_SANDBOX_AGE_SECONDS - 60
    os.utime(unrelated, (stamp, stamp))

    _sweep_stale_sandboxes(tmp_path)

    assert unrelated.exists()


def test_sweep_tolerates_a_missing_root(tmp_path):
    _sweep_stale_sandboxes(tmp_path / "never-created")
