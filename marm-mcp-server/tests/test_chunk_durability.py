import asyncio
import sqlite3
import uuid

import anyio
import numpy as np
import pytest

from marm_mcp_server.config.settings import DEFAULT_SEMANTIC_DIM
from marm_mcp_server.core import memory as memory_module
from marm_mcp_server.core.memory import MEMORY_CHUNK_THRESHOLD_WORDS, MARMMemory
from marm_mcp_server.core.memory_utils import _write_chunks, drain_chunk_writes


def _long_content() -> str:
    return " ".join(f"w{i}" for i in range(MEMORY_CHUNK_THRESHOLD_WORDS + 300))


def _stub_encoder(mem, monkeypatch, delay: float = 0.0):
    """Stand in for fastembed with a real-shaped vector and controllable latency."""
    vector = np.ones(DEFAULT_SEMANTIC_DIM, dtype=np.float32)

    def _encode_sync(_text):
        if delay:
            import time

            time.sleep(delay)
        return vector

    monkeypatch.setattr(mem, "_load_encoder_lazily", lambda: True)
    monkeypatch.setattr(mem, "_encode_sync", _encode_sync)


def _chunk_rows(db_path: str, memory_id: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT chunk_text FROM memory_chunks WHERE memory_id = ?"
                " ORDER BY chunk_index",
                (memory_id,),
            )
        ]


@pytest.mark.asyncio
async def test_chunk_write_is_tracked_then_released(monkeypatch, tmp_path):
    """The task registers while in flight and the done-callback clears it after."""
    db_path = str(tmp_path / "tracked.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch, delay=0.05)

    memory_id = await mem.store_memory(_long_content(), "test")

    assert len(mem._pending_chunk_writes) == 1, (
        "chunk write was not registered in the tracking set"
    )
    await asyncio.gather(*mem._pending_chunk_writes)
    assert mem._pending_chunk_writes == set(), (
        "done-callback did not discard the finished task; the set would grow forever"
    )
    assert _chunk_rows(db_path, memory_id), "tracked write produced no chunk rows"


@pytest.mark.asyncio
async def test_drain_waits_for_a_slow_chunk_write(monkeypatch, tmp_path):
    """A drain with headroom lets the rows land, which is the whole point."""
    db_path = str(tmp_path / "drained.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch, delay=0.05)

    memory_id = await mem.store_memory(_long_content(), "test")
    assert _chunk_rows(db_path, memory_id) == [], (
        "chunks landed before the drain, so this test proves nothing"
    )

    messages = []
    still_pending = await drain_chunk_writes(mem, 10.0, messages.append)

    assert still_pending == 0
    assert _chunk_rows(db_path, memory_id), (
        "drain returned before the rows were written"
    )


@pytest.mark.asyncio
async def test_drain_gives_up_without_hanging(monkeypatch, tmp_path):
    """An encoder slower than the timeout must not hold the process open."""
    mem = MARMMemory(str(tmp_path / "timeout.db"))
    _stub_encoder(mem, monkeypatch, delay=5.0)

    await mem.store_memory(_long_content(), "test")

    messages = []
    started = asyncio.get_running_loop().time()
    still_pending = await drain_chunk_writes(mem, 0.2, messages.append)
    elapsed = asyncio.get_running_loop().time() - started

    assert still_pending >= 1
    assert elapsed < 2.0, f"bounded drain blocked for {elapsed:.2f}s"
    assert any("--rechunk" in message for message in messages), (
        "expired drain must point the user at the repair path"
    )


@pytest.mark.asyncio
async def test_drain_is_a_no_op_with_nothing_pending(tmp_path):
    mem = MARMMemory(str(tmp_path / "idle.db"))
    messages = []

    assert await drain_chunk_writes(mem, 5.0, messages.append) == 0
    assert messages == [], "an idle shutdown must stay silent"


@pytest.mark.asyncio
async def test_graceful_shutdown_drains_chunk_writes(monkeypatch, tmp_path):
    """The HTTP transport's real teardown path, not the helper in isolation."""
    from marm_mcp_server.core import shutdown_manager as shutdown_module

    db_path = str(tmp_path / "shutdown.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch, delay=0.05)
    monkeypatch.setattr(shutdown_module, "memory", mem)
    monkeypatch.setattr(
        shutdown_module.graph_supervisor, "stop", lambda: None, raising=False
    )

    memory_id = await mem.store_memory(_long_content(), "test")
    assert _chunk_rows(db_path, memory_id) == []

    manager = shutdown_module.ShutdownManager()
    await manager.graceful_shutdown()

    assert _chunk_rows(db_path, memory_id), (
        "graceful_shutdown closed the pool without waiting for chunk writes"
    )


@pytest.mark.asyncio
async def test_shutdown_drains_between_the_queue_stop_and_the_pool_close(
    monkeypatch, tmp_path
):
    """Both ordering constraints at once, and they pull in opposite directions.

    Draining the write queue runs the writes still in it, and a long one spawns a
    chunk task, so a drain taken before that point can miss tasks that do not exist
    yet. The pool close has to come after, because a chunk task holding
    BEGIN IMMEDIATE would race teardown.
    """
    from marm_mcp_server.core import shutdown_manager as shutdown_module

    mem = MARMMemory(str(tmp_path / "order.db"))
    _stub_encoder(mem, monkeypatch)
    monkeypatch.setattr(shutdown_module, "memory", mem)
    monkeypatch.setattr(
        shutdown_module.graph_supervisor, "stop", lambda: None, raising=False
    )

    events = []

    async def _spy_drain(_mem, _timeout, _log):
        events.append("drain")
        return 0

    async def _spy_stop_queue():
        events.append("stop_queue")

    monkeypatch.setattr(shutdown_module, "drain_chunk_writes", _spy_drain)
    monkeypatch.setattr(mem, "stop_write_queue", _spy_stop_queue)
    monkeypatch.setattr(
        mem.connection_pool, "close_all", lambda: events.append("close_pool")
    )

    await shutdown_module.ShutdownManager().graceful_shutdown()

    assert events == ["stop_queue", "drain", "close_pool"]


@pytest.mark.asyncio
async def test_shutdown_catches_a_chunk_write_spawned_by_the_queue_drain(
    monkeypatch, tmp_path
):
    """A long memory still queued when shutdown begins must not lose its chunks.

    stop_write_queue() awaits queue.join(), which runs the remaining writes through
    store_memory and spawns their chunk tasks. Those tasks are created during
    shutdown, so the chunk drain has to observe the set after that point.
    """
    from marm_mcp_server.core import shutdown_manager as shutdown_module
    from marm_mcp_server.core.write_queue import MemoryWriteRequest

    db_path = str(tmp_path / "queued.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch, delay=0.05)
    monkeypatch.setattr(shutdown_module, "memory", mem)
    monkeypatch.setattr(
        shutdown_module.graph_supervisor, "stop", lambda: None, raising=False
    )

    monkeypatch.setattr(memory_module, "WRITE_QUEUE_ENABLED", True)
    await mem.start_write_queue()
    assert mem._write_queue is not None

    future = asyncio.get_running_loop().create_future()
    await mem._write_queue.queue.put(
        MemoryWriteRequest(_long_content(), "test", "general", None, future)
    )

    await shutdown_module.ShutdownManager().graceful_shutdown()

    memory_id = await future
    assert _chunk_rows(db_path, memory_id), (
        "chunk task spawned while draining the write queue was never awaited"
    )


@pytest.mark.asyncio
async def test_stdio_lifespan_drains_after_yield(monkeypatch, tmp_path):
    """Gotcha 1: the drain must run inside the loop, on teardown, not after it.

    Placing it in main()'s finally would execute after mcp.run() closed the loop,
    where it cannot await anything. Exercising the lifespan context manager is what
    distinguishes a real drain from one aimed at a dead loop.
    """
    from marm_mcp_server import server_stdio

    db_path = str(tmp_path / "stdio.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch, delay=0.05)
    monkeypatch.setattr(server_stdio, "memory", mem)

    assert server_stdio.mcp.settings.lifespan is not None, (
        "FastMCP was constructed without the lifespan hook"
    )

    async with server_stdio._stdio_lifespan(server_stdio.mcp):
        memory_id = await mem.store_memory(_long_content(), "test")
        assert _chunk_rows(db_path, memory_id) == []

    assert _chunk_rows(db_path, memory_id), (
        "STDIO teardown did not wait for the pending chunk write"
    )


@pytest.mark.asyncio
async def test_stdio_lifespan_drains_when_the_session_raises(monkeypatch, tmp_path):
    """A crashed or cancelled session is when pending chunks matter most.

    An exception thrown into the generator at the yield skips everything after it,
    so the drain only survives this if it sits in a finally.
    """
    from marm_mcp_server import server_stdio

    db_path = str(tmp_path / "stdio-raise.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch, delay=0.05)
    monkeypatch.setattr(server_stdio, "memory", mem)

    with pytest.raises(RuntimeError, match="session died"):
        async with server_stdio._stdio_lifespan(server_stdio.mcp):
            memory_id = await mem.store_memory(_long_content(), "test")
            assert _chunk_rows(db_path, memory_id) == []
            raise RuntimeError("session died")

    assert _chunk_rows(db_path, memory_id), (
        "drain was skipped because the lifespan body raised"
    )


@pytest.mark.asyncio
async def test_stdio_lifespan_drains_inside_a_cancelled_anyio_scope(
    monkeypatch, tmp_path
):
    """Cancellation is the common real case: the client closes the pipe.

    This must cancel a real anyio scope, not raise CancelledError by hand. FastMCP
    runs on anyio, whose cancellation is level-triggered: inside a cancelled scope
    every await raises immediately, so an unshielded drain is skipped. Raising the
    exception manually leaves the scope uncancelled and passes either way, which
    makes it useless as a guard.
    """
    from marm_mcp_server import server_stdio

    db_path = str(tmp_path / "stdio-cancel.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch, delay=0.05)
    monkeypatch.setattr(server_stdio, "memory", mem)

    memory_id = None
    with anyio.CancelScope() as scope:
        async with server_stdio._stdio_lifespan(server_stdio.mcp):
            memory_id = await mem.store_memory(_long_content(), "test")
            assert _chunk_rows(db_path, memory_id) == []
            scope.cancel()
            await anyio.sleep(10)

    assert _chunk_rows(db_path, memory_id), (
        "drain was skipped by level-triggered cancellation; it needs shielding"
    )


@pytest.mark.asyncio
async def test_stdio_lifespan_drains_the_write_queue_before_chunks(
    monkeypatch, tmp_path
):
    """STDIO starts the write queue lazily and otherwise never stops it.

    A write still queued at teardown spawns its chunk task only when the queue
    drains, so without stopping the queue first the chunk drain sees an empty set
    and the write is lost. Same defect the HTTP path already covers.
    """
    from marm_mcp_server import server_stdio
    from marm_mcp_server.core.write_queue import MemoryWriteRequest

    db_path = str(tmp_path / "stdio-queue.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch, delay=0.05)
    monkeypatch.setattr(server_stdio, "memory", mem)
    monkeypatch.setattr(memory_module, "WRITE_QUEUE_ENABLED", True)

    future = asyncio.get_running_loop().create_future()
    async with server_stdio._stdio_lifespan(server_stdio.mcp):
        await mem.start_write_queue()
        assert mem._write_queue is not None
        await mem._write_queue.queue.put(
            MemoryWriteRequest(_long_content(), "test", "general", None, future)
        )

    memory_id = await future
    assert _chunk_rows(db_path, memory_id), (
        "queued write's chunks were lost because the queue was not drained first"
    )


@pytest.mark.asyncio
async def test_write_chunks_abort_releases_the_write_lock(monkeypatch, tmp_path):
    """The staleness abort must ROLLBACK, not leave BEGIN IMMEDIATE to conn.close()."""
    db_path = str(tmp_path / "abort.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch)

    memory_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, content_hash, timestamp)"
            " VALUES (?, 's1', 'content', 'hash-current', '2026-01-01T00:00:00+00:00')",
            (memory_id,),
        )
        conn.commit()

    await _write_chunks(mem, db_path, memory_id, ["chunk one"], "hash-stale")

    assert _chunk_rows(db_path, memory_id) == [], "stale write should insert nothing"

    other = sqlite3.connect(db_path, timeout=0.5)
    try:
        other.execute("BEGIN IMMEDIATE")
        other.execute("ROLLBACK")
    finally:
        other.close()


@pytest.mark.asyncio
async def test_back_to_back_resave_stays_idempotent(monkeypatch, tmp_path):
    """The OR REPLACE upsert plus the dedup index, still intact after the changes."""
    db_path = str(tmp_path / "resave.db")
    mem = MARMMemory(db_path)
    _stub_encoder(mem, monkeypatch)

    memory_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, content_hash, timestamp)"
            " VALUES (?, 's1', 'content', 'hash-same', '2026-01-01T00:00:00+00:00')",
            (memory_id,),
        )
        conn.commit()

    chunks = ["chunk one", "chunk two"]
    await asyncio.gather(
        _write_chunks(mem, db_path, memory_id, chunks, "hash-same"),
        _write_chunks(mem, db_path, memory_id, chunks, "hash-same"),
    )

    assert _chunk_rows(db_path, memory_id) == chunks
