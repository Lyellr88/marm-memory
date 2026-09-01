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
from marm_mcp_server.core.memory_db import init_database
from marm_mcp_server.endpoints import system


@pytest.fixture(autouse=True)
def schema():
    """conftest redirects HOME, so the isolated database starts without tables.

    Initialise the path the pool actually resolved, not the imported constant.
    """
    init_database(memory.connection_pool.db_path)


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
async def test_a_queued_write_from_a_foreign_loop_would_hang():
    """Pins the hazard itself, so nobody reintroduces asyncio.run in a worker thread."""
    await memory.start_write_queue()

    def foreign_loop_write():
        async def do_write():
            return await memory.store_memory_queued(
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
        except Exception as exc:
            return type(exc).__name__

    outcome = await asyncio.to_thread(foreign_loop_write)
    await _delete_probe_memories()

    assert outcome != "completed", (
        "a foreign-loop queued write unexpectedly succeeded; if the write queue "
        "became loop-agnostic, the reload job may no longer need to stay on the "
        "server loop and this constraint should be revisited"
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
