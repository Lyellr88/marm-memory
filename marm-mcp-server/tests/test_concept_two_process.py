"""Two real processes over one memory database.

Every other queue test runs sequential calls in one interpreter, which
exercises the SQL but not the thing the lease and the build lock exist for:
an HTTP server and a STDIO session are separate processes, and neither
asyncio.Lock nor a Python-level set reaches across that boundary. These tests
spawn a genuine second interpreter against the same database file.
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_in_second_process(db_path: Path, body: str, env_extra=None) -> dict:
    """Execute body in a fresh interpreter pointed at the same memory DB.

    Prints a single JSON line, so anything the server writes to stderr on
    import cannot corrupt the result.
    """
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
    env = {**dict(__import__("os").environ), **(env_extra or {})}
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if completed.returncode != 0:
        pytest.fail(f"second process failed:\n{completed.stdout}\n{completed.stderr}")
    for line in completed.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT ") :])
    pytest.fail(f"second process printed no result:\n{completed.stdout}")


@pytest.fixture
def shared_db(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    load_isolated_server(monkeypatch, tmp_path)
    import sys as _sys

    memory_module = _sys.modules["marm_mcp_server.core.memory"]
    return memory_module.memory, tmp_path / "marm_memory.db"


def _seed_task(mem, memory_id, content_hash="h1"):
    from marm_mcp_server.core import concept_queue

    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, content_hash) "
            "VALUES (?, 'sess-a', 'content', datetime('now'), ?)",
            (memory_id, content_hash),
        )
        concept_queue.enqueue(conn, memory_id, content_hash)


def test_a_second_process_cannot_claim_a_task_this_one_holds(shared_db):
    """The reason the queue carries a lease at all. An asyncio.Lock would let
    both processes extract the same memory at the same time."""
    from marm_mcp_server.core import concept_queue

    mem, db_path = shared_db
    _seed_task(mem, "m1")
    _seed_task(mem, "m2")

    mine = concept_queue.claim(10)
    assert sorted(task.memory_id for task in mine) == ["m1", "m2"]

    theirs = _run_in_second_process(
        db_path,
        """
        from marm_mcp_server.core import concept_queue
        result = [t.memory_id for t in concept_queue.claim(10)]
        """,
    )

    assert theirs == []


def test_a_second_process_reclaims_a_task_whose_lease_expired(shared_db):
    """A process killed mid-extraction must not strand its tasks."""
    from marm_mcp_server.core import concept_queue

    mem, db_path = shared_db
    _seed_task(mem, "m1")
    concept_queue.claim(1)
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE concept_index_queue SET leased_until = '2000-01-01T00:00:00+00:00'"
        )

    theirs = _run_in_second_process(
        db_path,
        """
        from marm_mcp_server.core import concept_queue
        result = [t.memory_id for t in concept_queue.claim(10)]
        """,
    )

    assert theirs == ["m1"]


def test_a_second_process_cannot_take_the_build_lock(shared_db):
    """A manual rebuild drops the graph tables. It must not run while the
    other transport's worker is writing to them."""
    from marm_mcp_server.core import concept_build_lock

    _mem, db_path = shared_db
    assert concept_build_lock.try_acquire("worker-a", "auto_index", 300) is True

    result = _run_in_second_process(
        db_path,
        """
        from marm_mcp_server.core import concept_build_lock
        result = {
            "acquired": concept_build_lock.try_acquire("build-b", "manual_build", 60),
            "holder": concept_build_lock.current_holder(),
        }
        """,
    )

    assert result["acquired"] is False
    assert result["holder"][0] == "auto_index"


def test_a_second_process_takes_the_lock_once_it_is_released(shared_db):
    from marm_mcp_server.core import concept_build_lock

    _mem, db_path = shared_db
    assert concept_build_lock.try_acquire("worker-a", "auto_index", 300) is True
    assert concept_build_lock.release("worker-a") is True

    result = _run_in_second_process(
        db_path,
        """
        from marm_mcp_server.core import concept_build_lock
        result = {"acquired": concept_build_lock.try_acquire("build-b", "manual_build", 60)}
        """,
    )

    assert result["acquired"] is True


def test_an_expired_build_lock_does_not_wedge_the_graph_forever(shared_db):
    """A crashed holder must not stop every future build."""
    from marm_mcp_server.core import concept_build_lock

    mem, db_path = shared_db
    concept_build_lock.try_acquire("crashed", "manual_build", 3600)
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE concept_build_lock SET expires_at = '2000-01-01T00:00:00+00:00'"
        )

    result = _run_in_second_process(
        db_path,
        """
        from marm_mcp_server.core import concept_build_lock
        result = {"acquired": concept_build_lock.try_acquire("next", "auto_index", 60)}
        """,
    )

    assert result["acquired"] is True


@pytest.mark.asyncio
async def test_work_outliving_its_ttl_keeps_both_locks(shared_db):
    """The lock has to survive work that runs longer than the lease, or it is
    a deadline rather than a lock. A full rebuild has no bounded runtime, and
    the task leases expire on the same clock, so an unrenewed pair would let
    a second process both write the graph and re-extract the same memories.
    """
    import asyncio

    from marm_mcp_server.core import concept_build_lock, concept_queue

    mem, db_path = shared_db
    _seed_task(mem, "m1")
    ttl = 1

    async with concept_build_lock.concept_build_lock("manual_build", ttl):
        tasks = concept_queue.claim(10)
        assert len(tasks) == 1
        async with concept_queue.keep_claimed(tasks, ttl):
            # Three times the lease. Without renewal both are long expired.
            await asyncio.sleep(ttl * 3)

            # Through a thread, because subprocess.run is synchronous: called
            # directly it blocks the event loop for the child's whole startup,
            # which is exactly when the heartbeat needs to be renewing. That
            # would make the test fail for the opposite of the real reason.
            other = await asyncio.to_thread(
                _run_in_second_process,
                db_path,
                """
                from marm_mcp_server.core import concept_build_lock, concept_queue
                result = {
                    "took_lock": concept_build_lock.try_acquire("b", "manual_build", 60),
                    "claimed": [t.memory_id for t in concept_queue.claim(10)],
                }
                """,
            )

    assert other["took_lock"] is False, "a second process overtook a live build"
    assert other["claimed"] == [], "a second process re-claimed a live task"


@pytest.mark.asyncio
async def test_both_locks_are_free_again_once_the_work_finishes(shared_db):
    """Renewal must not outlive the body it was protecting."""
    from marm_mcp_server.core import concept_build_lock, concept_queue

    mem, db_path = shared_db
    _seed_task(mem, "m1")

    async with concept_build_lock.concept_build_lock("manual_build", 1):
        tasks = concept_queue.claim(10)
        async with concept_queue.keep_claimed(tasks, 1):
            pass
    concept_queue.complete("m1", tasks[0].lease_token, "h1")

    result = await asyncio.to_thread(
        _run_in_second_process,
        db_path,
        """
        from marm_mcp_server.core import concept_build_lock
        result = {"took_lock": concept_build_lock.try_acquire("b", "auto_index", 60)}
        """,
    )

    assert result["took_lock"] is True


@pytest.mark.asyncio
async def test_a_lease_that_cannot_be_renewed_gives_up_at_the_ttl(shared_db):
    """A renewal that keeps raising is indistinguishable from one refused: the
    lease runs out either way and another process can take the graph. Logging
    warnings while still writing is the one outcome that must not happen."""
    from marm_mcp_server.core import concept_build_lock

    _mem, _db_path = shared_db

    def always_fails(_holder, _ttl):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(concept_build_lock, "renew", always_fails)
    try:
        async with concept_build_lock.concept_build_lock("auto_index", 1) as lease:
            await asyncio.sleep(2.5)
            assert lease.lost.is_set(), (
                "the holder kept going with a lease it could not renew"
            )
    finally:
        monkeypatch.undo()


def test_renew_refuses_once_someone_else_owns_the_lock(shared_db):
    """A stalled holder must learn it lost the graph rather than quietly
    extending a lease it no longer has."""
    from marm_mcp_server.core import concept_build_lock

    mem, _db_path = shared_db
    concept_build_lock.try_acquire("stalled", "auto_index", 3600)
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE concept_build_lock SET expires_at = '2000-01-01T00:00:00+00:00'"
        )
    concept_build_lock.try_acquire("new-owner", "manual_build", 300)

    assert concept_build_lock.renew("stalled", 300) is False
    assert concept_build_lock.current_holder()[0] == "manual_build"


def test_queue_renew_only_extends_tasks_we_still_hold(shared_db):
    from marm_mcp_server.core import concept_queue

    mem, _db_path = shared_db
    _seed_task(mem, "m1")
    task = concept_queue.claim(1)[0]

    assert concept_queue.renew([task.memory_id], task.lease_token, 600) == 1
    assert concept_queue.renew([task.memory_id], "not-our-token", 600) == 0


def test_releasing_after_expiry_does_not_steal_the_new_holders_lock(shared_db):
    """The late finisher must not delete a lock somebody else now owns."""
    from marm_mcp_server.core import concept_build_lock

    mem, _db_path = shared_db
    concept_build_lock.try_acquire("slow-worker", "auto_index", 3600)
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE concept_build_lock SET expires_at = '2000-01-01T00:00:00+00:00'"
        )
    assert concept_build_lock.try_acquire("new-owner", "manual_build", 300) is True

    assert concept_build_lock.release("slow-worker") is False
    assert concept_build_lock.current_holder()[0] == "manual_build"
