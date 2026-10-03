"""Which memories get recalled, counted without slowing recall down."""

import asyncio
import importlib
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
from conftest import load_isolated_server, local_client


def _usage(db: Path) -> dict[str, tuple[int, str]]:
    with sqlite3.connect(db) as conn:
        return {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT memory_id, recall_count, last_recalled_at FROM memory_usage"
            )
        }


def _memory_row(db: Path, memory_id: str) -> None:
    """A real memories row: usage rows reference one."""
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp) "
            "VALUES (?, 'marm_system', 'MARM protocol text', ?)",
            (memory_id, datetime.now(timezone.utc).isoformat()),
        )


def _drain() -> None:
    usage = importlib.import_module("marm_mcp_server.core.memory_usage")
    asyncio.run(usage.drain())


def _log(client, text: str) -> str:
    response = client.post(
        "/marm_log_entry",
        json={"entry": f"2026-09-27-note-{text}", "session_name": "usage"},
    )
    assert response.status_code == 200, response.text
    return response.json()["memory_id"]


def test_http_recall_counts_the_memories_it_returned(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    wanted = _log(client, "the write queue serialises memory writes")
    other = _log(client, "lunch was at noon on thursday")

    for _ in range(2):
        response = client.post(
            "/marm_smart_recall",
            json={
                "query": "write queue serialises",
                "session_name": "usage",
                "limit": 1,
            },
        )
        assert response.status_code == 200
        assert [r["id"] for r in response.json()["results"]] == [wanted]
    _drain()

    usage = _usage(tmp_path / "marm_memory.db")
    assert usage[wanted][0] == 2 and usage[wanted][1]
    assert other not in usage


def test_stdio_recall_counts_the_same_way(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    wanted = _log(local_client(server.app), "the write queue serialises memory writes")
    recall = importlib.import_module("marm_mcp_server.services.recall")

    async def run():
        result = await recall.smart_recall(
            "write queue serialises", session_name="usage", limit=1
        )
        await importlib.import_module("marm_mcp_server.core.memory_usage").drain()
        return result

    result = asyncio.run(run())

    assert [r["id"] for r in result["results"]] == [wanted]
    assert _usage(tmp_path / "marm_memory.db")[wanted][0] == 1


def test_a_failed_count_never_fails_the_recall(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    wanted = _log(client, "the write queue serialises memory writes")
    usage = importlib.import_module("marm_mcp_server.core.memory_usage")

    def boom(*_args):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(usage, "_increment", boom)

    with structlog.testing.capture_logs() as logs:
        response = client.post(
            "/marm_smart_recall",
            json={"query": "write queue serialises", "session_name": "usage"},
        )
        _drain()

    assert response.status_code == 200
    assert wanted in [r["id"] for r in response.json()["results"]]
    # A lost count must be visible, not swallowed by the background future.
    assert any(e.get("event") == "memory_usage.write_failed" for e in logs)


def test_cold_memories_are_the_ones_nobody_recalls(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    recalled = _log(client, "the write queue serialises memory writes")
    never = _log(client, "lunch was at noon on thursday")
    stale = _log(client, "the old deploy script lives in tools")
    young = _log(client, "a note written today about indexing")
    folded = _log(client, "a note folded into a compaction summary")

    db = tmp_path / "marm_memory.db"
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE memories SET timestamp = ? WHERE id != ?", (old, young))
        conn.execute(
            "UPDATE memories SET compaction_role = 'source' WHERE id = ?", (folded,)
        )
    client.post(
        "/marm_smart_recall",
        json={"query": "write queue serialises", "session_name": "usage", "limit": 1},
    )
    _drain()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO memory_usage (memory_id, recall_count, last_recalled_at) "
            "VALUES (?, 3, ?)",
            (stale, old),
        )

    store = importlib.import_module("marm_mcp_server.console.memory_store")
    cold = store.cold_memories(db, days=30, limit=10)

    ids = [row["id"] for row in cold["memories"]]
    assert ids == [never, stale]
    assert recalled not in ids
    assert young not in ids, "too new to have had a chance to be recalled"
    assert folded not in ids, "recall never returns compacted sources"
    assert cold["memories"][0]["recall_count"] == 0
    assert cold["memories"][1]["recall_count"] == 3


def test_http_shutdown_drains_counts_before_closing_the_pool(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    usage = importlib.import_module("marm_mcp_server.core.memory_usage")
    shutdown = importlib.import_module("marm_mcp_server.core.shutdown_manager")
    memory = importlib.import_module("marm_mcp_server.core.memory").memory
    events = []

    async def drain():
        events.append("drain")

    close = memory.connection_pool.close_all
    monkeypatch.setattr(usage, "drain", drain)
    monkeypatch.setattr(
        memory.connection_pool,
        "close_all",
        lambda: (events.append("close"), close())[1],
    )

    asyncio.run(shutdown.ShutdownManager().graceful_shutdown())

    assert events.index("drain") < events.index("close")


def test_stdio_teardown_drains_counts(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    usage = importlib.import_module("marm_mcp_server.core.memory_usage")
    # Imported inside the test, as test_chunk_durability does.
    server_stdio = importlib.import_module("marm_mcp_server.server_stdio")
    drained = []

    async def drain():
        drained.append(True)

    monkeypatch.setattr(usage, "drain", drain)

    async def run():
        async with server_stdio._stdio_lifespan(server_stdio.mcp):
            pass

    asyncio.run(run())
    assert drained


def test_system_documentation_returned_by_the_fallback_is_counted(
    monkeypatch, tmp_path
):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    memory = importlib.import_module("marm_mcp_server.core.memory").memory
    doc_id = "doc-row"
    _memory_row(tmp_path / "marm_memory.db", doc_id)

    doc = {
        "id": doc_id,
        "content": "MARM protocol text",
        "session_name": "marm_system",
        "similarity": 0.9,
        "timestamp": "2026-09-27T00:00:00+00:00",
        "context_type": "general",
    }

    # The main lane returns (results, meta); the documentation fallback takes
    # the session positionally and a bare list.
    async def recall_similar(query, session=None, *args, **kwargs):
        if session == "marm_system":
            return [doc]
        return [], {}

    monkeypatch.setattr(memory, "recall_similar", recall_similar)
    response = client.post(
        "/marm_smart_recall", json={"query": "protocol", "session_name": "usage"}
    )
    _drain()

    assert response.status_code == 200
    assert doc_id in [r.get("id") for r in response.json().get("system_results", [])]
    assert _usage(tmp_path / "marm_memory.db")[doc_id][0] == 1


def test_the_cold_route_answers_over_http(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "marm_memory.db"))
    from fastapi.testclient import TestClient

    console = importlib.import_module("marm_mcp_server.console.endpoints.memory")
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(console.router)
    client = TestClient(app)

    ok = client.get("/api/memories/cold", params={"days": 30, "limit": 5})
    assert ok.status_code == 200, ok.text
    assert set(ok.json()) == {"days", "cutoff", "memories"}
    assert client.get("/api/memories/cold", params={"days": 0}).status_code == 422

    with sqlite3.connect(tmp_path / "marm_memory.db") as conn:
        conn.execute("DROP TABLE memory_usage")
    assert client.get("/api/memories/cold").status_code == 503


def test_stdio_counts_system_documentation_the_same_way(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    _memory_row(tmp_path / "marm_memory.db", "doc-row")
    memory = importlib.import_module("marm_mcp_server.core.memory").memory
    recall = importlib.import_module("marm_mcp_server.services.recall")
    doc = {
        "id": "doc-row",
        "content": "MARM protocol text",
        "session_name": "marm_system",
        "similarity": 0.9,
        "timestamp": "2026-09-27T00:00:00+00:00",
        "context_type": "general",
    }

    async def recall_similar(query, session=None, *args, **kwargs):
        if session == "marm_system":
            return [doc]
        return [], {}

    monkeypatch.setattr(memory, "recall_similar", recall_similar)

    async def run():
        result = await recall.smart_recall("protocol", session_name="usage")
        await importlib.import_module("marm_mcp_server.core.memory_usage").drain()
        return result

    result = asyncio.run(run())
    assert [r["id"] for r in result["system_results"]] == ["doc-row"]
    assert _usage(tmp_path / "marm_memory.db")["doc-row"][0] == 1


def test_finished_counts_leave_nothing_pending(monkeypatch, tmp_path):
    """The future joins the pending set before its callback is registered, and
    a callback on a future that has already finished runs at once, so no
    completed future can be left behind."""
    load_isolated_server(monkeypatch, tmp_path)
    usage = importlib.import_module("marm_mcp_server.core.memory_usage")

    for i in range(7):
        _memory_row(tmp_path / "marm_memory.db", f"m{i}")

    for i in range(500):
        usage.record_recalled([f"m{i % 7}"])
    asyncio.run(usage.drain())

    assert usage._pending == set()


def test_an_older_count_never_moves_last_recalled_backwards(monkeypatch, tmp_path):
    """HTTP and STDIO are separate processes sharing one store, so a slower
    writer can arrive with an earlier time than the one already recorded."""
    load_isolated_server(monkeypatch, tmp_path)
    usage = importlib.import_module("marm_mcp_server.core.memory_usage")

    _memory_row(tmp_path / "marm_memory.db", "m")
    usage._increment(["m"], "2026-09-27T10:00:00+00:00")
    usage._increment(["m"], "2026-09-27T09:00:00+00:00")

    count, last = _usage(tmp_path / "marm_memory.db")["m"]
    assert (count, last) == (2, "2026-09-27T10:00:00+00:00")


def test_deleting_a_memory_removes_its_usage(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    wanted = _log(client, "the write queue serialises memory writes")
    client.post(
        "/marm_smart_recall",
        json={"query": "write queue serialises", "session_name": "usage", "limit": 1},
    )
    _drain()
    db = tmp_path / "marm_memory.db"
    assert wanted in _usage(db)

    memory = importlib.import_module("marm_mcp_server.core.memory").memory
    with memory.get_connection() as conn:
        conn.execute("DELETE FROM memories WHERE id = ?", (wanted,))

    assert wanted not in _usage(db), "a deleted memory left a usage row behind"


def test_an_overloaded_store_drops_counts_instead_of_queueing_them(
    monkeypatch, tmp_path
):
    """Recall must not build a backlog while the store cannot take writes."""
    load_isolated_server(monkeypatch, tmp_path)
    usage = importlib.import_module("marm_mcp_server.core.memory_usage")
    release = threading.Event()
    monkeypatch.setattr(usage, "_increment", lambda *_a: release.wait(30))
    try:
        with structlog.testing.capture_logs() as logs:
            for i in range(usage.MAX_PENDING * 3):
                usage.record_recalled([f"m{i}"])
            pending = len(usage._pending)
    finally:
        release.set()
    asyncio.run(usage.drain())

    assert pending <= usage.MAX_PENDING
    assert any(e.get("event") == "memory_usage.dropped" for e in logs)
    assert usage._pending == set()


def test_drain_returns_with_nothing_pending_even_if_callbacks_lag(
    monkeypatch, tmp_path
):
    """wait() can return before a done callback runs; drain must not rely on it."""
    load_isolated_server(monkeypatch, tmp_path)
    usage = importlib.import_module("marm_mcp_server.core.memory_usage")
    started, released = threading.Event(), threading.Event()
    real_forget = usage._forget

    def late_forget(future):
        released.wait(5)
        real_forget(future)

    # The write is still running when the callback is attached, so the
    # callback runs on the worker after completion, and is held there.
    monkeypatch.setattr(usage, "_increment", lambda *_a: started.wait(5))
    monkeypatch.setattr(usage, "_forget", late_forget)
    try:
        usage.record_recalled(["m1"])
        started.set()
        asyncio.run(usage.drain())
        assert usage._pending == set()
    finally:
        released.set()
