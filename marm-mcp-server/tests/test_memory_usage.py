"""Which memories get recalled, counted without slowing recall down."""

import asyncio
import importlib
import sqlite3
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
