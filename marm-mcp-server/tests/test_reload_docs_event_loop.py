"""Reload-docs must run on the loop that owns the write queue.

`documentation.py` stores each document with `await memory.store_memory_queued()`,
which creates its completion Future on the calling loop while the write-queue
worker resolves that Future from the server loop. Running the reload on any other
loop therefore hangs. These tests use the real queue, not a stub, because a stub
never reaches it.
"""

import asyncio
import inspect
import sqlite3

import pytest

from marm_mcp_server.core.memory import memory
from marm_mcp_server.core.memory_db import SQLiteConnectionPool, init_database
from marm_mcp_server.endpoints import system


@pytest.fixture(autouse=True)
def schema(tmp_path, monkeypatch):
    """Point the pool at a temporary database, then create its tables.

    Redirecting HOME is not enough and the difference is not theoretical: this
    module imports the `memory` singleton at module scope, so its pool resolved
    `~/.marm/marm_memory.db` before any session fixture ran. These tests then
    perform REAL queued writes, and `store_memory_queued` returns when the
    future resolves rather than when the row is visible -- so the cleanup below
    deleted nothing and every run left a probe memory in the developer's own
    store. Measured: 8 such rows had accumulated, and one more appeared per run.

    Repointing the pool is what actually isolates it, because it does not
    depend on when the module was imported.
    """
    db = tmp_path / "marm_memory.db"
    init_database(str(db))
    # The POOL, not its `db_path`: SQLiteConnectionPool opens its first
    # connections in __init__, so repointing the attribute afterwards leaves
    # every existing connection bound to the original file.
    monkeypatch.setattr(memory, "connection_pool", SQLiteConnectionPool(str(db)))


def test_reload_docs_job_is_a_coroutine_not_a_thread_target():
    """A plain thread target would have to build its own loop, which is the bug."""
    assert inspect.iscoroutinefunction(system._run_reload_docs_job)


@pytest.mark.asyncio
async def test_reload_docs_runs_on_the_loop_that_owns_the_write_queue():
    """The whole job, including its queued writes, has to finish on the server loop."""
    await memory.start_write_queue()
    server_loop = asyncio.get_running_loop()
    observed: dict = {}

    async def fake_reload():
        observed["loop"] = asyncio.get_running_loop()
        # A real queued write is the operation that would deadlock across loops.
        observed["memory_id"] = await memory.store_memory_queued(
            content="reload docs loop probe",
            session="marm_loop_probe",
            context_type="general",
            metadata={"probe": True},
        )

    system.reload_marm_documentation = fake_reload
    try:
        started = await system.runtime_reload_docs()
        assert started["status"] in {"queued", "running"}

        job = started
        for _ in range(200):
            await asyncio.sleep(0.05)
            job = await system.runtime_reload_docs_status(started["job_id"])
            if job["status"] in {"success", "error"}:
                break
    finally:
        system.reload_marm_documentation = _ORIGINAL_RELOAD
        await _delete_probe_memories()

    assert job["status"] == "success", job.get("error")
    assert observed["loop"] is server_loop
    assert observed["memory_id"]


@pytest.mark.asyncio
async def test_a_queued_write_binds_its_completion_to_the_calling_loop():
    """Pins the hazard itself, so nobody reintroduces asyncio.run in a worker thread.

    `WriteQueue.put` creates its completion Future on the CALLING loop, while the
    worker resolves it from the server loop. That binding is the hazard, and it
    is deterministic.

    An earlier version asserted the SYMPTOM instead -- that such a write must not
    complete within a timeout -- and failed intermittently in CI, because
    resolving a Future across loops sometimes succeeds by scheduling luck. A test
    of a race condition must assert the structure that makes the race possible,
    not the outcome it usually produces.

    The queue here is deliberately never started, so nothing can drain it and
    nothing races: the await times out, and the request it left behind is
    inspected directly.
    """
    from marm_mcp_server.core.write_queue import WriteQueue

    server_loop = asyncio.get_running_loop()
    idle = WriteQueue(memory)
    captured: dict = {}

    def foreign_loop_write():
        async def do_write():
            captured["loop"] = asyncio.get_running_loop()
            await idle.put(
                content="foreign loop probe",
                session="marm_loop_probe",
                context_type="general",
                metadata={"probe": True},
            )

        try:
            asyncio.run(asyncio.wait_for(do_write(), timeout=2))
            return "completed"
        except asyncio.TimeoutError:
            return "hung"

    outcome = await asyncio.to_thread(foreign_loop_write)

    assert outcome == "hung", "nothing drains this queue, so the await cannot finish"
    request = idle.queue.get_nowait()
    assert request.future.get_loop() is captured["loop"], (
        "the completion Future must belong to the loop that called put()"
    )
    assert request.future.get_loop() is not server_loop, (
        "which is NOT the loop the worker resolves it from -- if this ever "
        "becomes the same loop, the write queue has become loop-agnostic and "
        "the reload job may no longer need to stay on the server loop"
    )


_ORIGINAL_RELOAD = system.reload_marm_documentation


async def _delete_probe_memories() -> None:
    # Cleanup must not mask the assertion that follows it.
    try:
        with memory.get_connection() as conn:
            conn.execute("DELETE FROM memories WHERE session_name = 'marm_loop_probe'")
            conn.commit()
    except sqlite3.Error:
        pass


@pytest.mark.asyncio
async def test_reload_docs_returns_before_the_reload_finishes():
    """A synchronous handler could not return while the reload is still gated."""
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def gated_reload():
        entered.set()
        await gate.wait()

    system.reload_marm_documentation = gated_reload
    try:
        started = await system.runtime_reload_docs()
        await asyncio.wait_for(entered.wait(), timeout=5)

        assert started["status"] in {"queued", "running"}
        assert started["finished_at"] is None
        mid_flight = await system.runtime_reload_docs_status(started["job_id"])
        assert mid_flight["status"] == "running"

        gate.set()
        job = await _await_job(started["job_id"])
    finally:
        system.reload_marm_documentation = _ORIGINAL_RELOAD

    assert job["status"] == "success"


@pytest.mark.asyncio
async def test_a_failing_reload_is_reported_on_the_job_not_the_request():
    async def broken_reload():
        raise RuntimeError("docs are unreadable")

    system.reload_marm_documentation = broken_reload
    try:
        started = await system.runtime_reload_docs()
        job = await _await_job(started["job_id"])
    finally:
        system.reload_marm_documentation = _ORIGINAL_RELOAD

    assert job["status"] == "error"
    assert "docs are unreadable" in job["error"]


async def _await_job(job_id: str, timeout: float = 10.0) -> dict:
    for _ in range(int(timeout / 0.05)):
        job = await system.runtime_reload_docs_status(job_id)
        if job["status"] in {"success", "error"}:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError("reload job never reached a terminal state")
