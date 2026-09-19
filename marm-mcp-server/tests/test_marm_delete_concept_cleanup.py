"""`marm_delete` must clean up concepts, exactly as the memory endpoints do.

Two delete paths removed the same rows and disagreed about the follow-up:
`endpoints/memory.py` ran the concept cleanup on single delete, bulk delete and
replace; `services/log_entry.py` never mentioned concepts. So a memory removed
through `/internal/memories/bulk-delete` was cleaned and the same memory removed
through `marm_delete` was not, leaving entities that keep their relationships
and go on steering `marm_concept_recall` with nothing evidencing them.
"""

from unittest.mock import patch

import pytest

from marm_mcp_server.services import log_entry as log_entry_module


@pytest.mark.asyncio
async def test_deleting_a_log_entry_cleans_up_its_concepts(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(log_entry_module, "memory", mem)

    entry_id = "entry-1"
    memory_id = await mem.store_memory(
        "a decision worth remembering",
        "delete-me",
        metadata={"source": "log_entry", "log_entry_id": entry_id},
    )
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO log_entries (id, session_name, entry_date, topic, summary,"
            " full_entry, created_at) VALUES (?,?,?,?,?,?,?)",
            (entry_id, "delete-me", "2026-09-19", "topic", "s", "full", "2026-09-19"),
        )
        conn.commit()

    seen: list[list[str]] = []

    async def fake_cleanup(ids):
        seen.append(list(ids))
        return {"status": "success", "entities_removed": len(ids)}

    with patch(
        "marm_mcp_server.endpoints.memory._cleanup_deleted_concepts_async", fake_cleanup
    ):
        result = await log_entry_module.delete_log_or_notebook_entry(
            "log", entry_id, "delete-me"
        )

    assert result["memories_deleted"] == 1
    assert seen == [[memory_id]], (
        "the deleted memory's id must reach the concept cleanup"
    )
    assert result["concept_cleanup"]["status"] == "success"


@pytest.mark.asyncio
async def test_deleting_a_whole_session_cleans_up_its_concepts(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(log_entry_module, "memory", mem)

    ids = [
        await mem.store_memory(
            f"decision {n}",
            "doomed",
            metadata={"source": "log_entry", "log_entry_id": f"e{n}"},
        )
        for n in range(3)
    ]

    seen: list[list[str]] = []

    async def fake_cleanup(memory_ids):
        seen.append(sorted(memory_ids))
        return {"status": "success", "entities_removed": len(memory_ids)}

    with patch(
        "marm_mcp_server.endpoints.memory._cleanup_deleted_concepts_async", fake_cleanup
    ):
        result = await log_entry_module.delete_log_or_notebook_entry(
            "log", "doomed", None
        )

    assert result["memories_deleted"] == 3
    assert seen == [sorted(ids)], "every deleted memory must reach the cleanup"


@pytest.mark.asyncio
async def test_a_delete_that_removes_no_memory_skips_the_cleanup(monkeypatch, tmp_path):
    """No memories removed means nothing to clean -- and no pointless call."""
    from marm_mcp_server.core import memory as memory_module

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(log_entry_module, "memory", mem)

    called = False

    async def fake_cleanup(memory_ids):
        nonlocal called
        called = True
        return {"status": "success"}

    with patch(
        "marm_mcp_server.endpoints.memory._cleanup_deleted_concepts_async", fake_cleanup
    ):
        result = await log_entry_module.delete_log_or_notebook_entry(
            "log", "no-such-session", None
        )

    assert called is False
    assert result["concept_cleanup"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_a_failing_cleanup_does_not_fail_the_delete(monkeypatch, tmp_path):
    """The rows are already gone; reporting an error would be a lie."""
    from marm_mcp_server.core import memory as memory_module

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(log_entry_module, "memory", mem)

    await mem.store_memory(
        "a decision",
        "doomed",
        metadata={"source": "log_entry", "log_entry_id": "e0"},
    )

    async def boom(memory_ids):
        raise RuntimeError("index unavailable")

    with patch(
        "marm_mcp_server.endpoints.memory._cleanup_deleted_concepts_async", boom
    ):
        result = await log_entry_module.delete_log_or_notebook_entry(
            "log", "doomed", None
        )

    assert result["status"] == "success"
    assert result["memories_deleted"] == 1
    assert result["concept_cleanup"]["status"] == "error"


@pytest.mark.asyncio
async def test_the_memory_connection_is_released_before_the_cleanup_awaits(
    monkeypatch, tmp_path
):
    """The cleanup awaits on the CONCEPT database, so it must not run while a
    pooled MEMORY connection is checked out. Holding one across that await lets
    concurrent deletes exhaust the pool and fail unrelated queries.

    Measured by pool depth rather than by reading the code: the pool is full
    again by the time the cleanup is entered.
    """
    from marm_mcp_server.core import memory as memory_module

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(log_entry_module, "memory", mem)

    await mem.store_memory(
        "a decision",
        "doomed",
        metadata={"source": "log_entry", "log_entry_id": "e0"},
    )

    # Baseline with nothing checked out, taken the same way as the measurement.
    with mem.get_connection():
        held_depth = mem.connection_pool.pool.qsize()
    free_depth = mem.connection_pool.pool.qsize()
    assert free_depth > held_depth, "a checked-out connection must lower the depth"

    seen_depth = {}

    async def fake_cleanup(memory_ids):
        seen_depth["at_cleanup"] = mem.connection_pool.pool.qsize()
        return {"status": "success"}

    with patch(
        "marm_mcp_server.endpoints.memory._cleanup_deleted_concepts_async", fake_cleanup
    ):
        result = await log_entry_module.delete_log_or_notebook_entry(
            "log", "doomed", None
        )

    assert result["concept_cleanup"]["status"] == "success"
    assert seen_depth["at_cleanup"] == free_depth, (
        "a memory connection was still checked out when the cleanup awaited"
    )


@pytest.mark.asyncio
async def test_a_failing_import_does_not_fail_the_delete(monkeypatch, tmp_path):
    """The lazy import must be inside the try, not above it.

    `endpoints.memory` is imported at call time to avoid a cycle. An
    ImportError there is a cleanup failure like any other, and by then the
    delete has already committed -- so raising would report a completed delete
    as a failure. Simulated by replacing the module with one that does not
    carry the symbol, which is exactly what `from x import y` raises on.
    """
    import sys
    import types

    from marm_mcp_server.core import memory as memory_module

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(log_entry_module, "memory", mem)

    await mem.store_memory(
        "a decision",
        "doomed",
        metadata={"source": "log_entry", "log_entry_id": "e0"},
    )

    monkeypatch.setitem(
        sys.modules,
        "marm_mcp_server.endpoints.memory",
        types.ModuleType("marm_mcp_server.endpoints.memory"),
    )

    result = await log_entry_module.delete_log_or_notebook_entry("log", "doomed", None)

    assert result["status"] == "success", "the delete committed; it did not fail"
    assert result["memories_deleted"] == 1
    assert result["concept_cleanup"]["status"] == "error"
