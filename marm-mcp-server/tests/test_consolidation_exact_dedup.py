"""Tests for consolidation Layer 1 — content hash dedup."""

import pytest

from marm_mcp_server.core.consolidation import compute_content_hash, find_exact_duplicate
from marm_mcp_server.core.memory import MARMMemory


# --- compute_content_hash unit tests ---

def test_compute_content_hash_normalizes_case():
    assert compute_content_hash("Fixed Login Bug") == compute_content_hash("fixed login bug")
    assert compute_content_hash("HELLO WORLD") == compute_content_hash("hello world")


def test_compute_content_hash_normalizes_leading_trailing_whitespace():
    assert compute_content_hash("  fixed login bug  ") == compute_content_hash("fixed login bug")
    assert compute_content_hash("fixed login bug\n") == compute_content_hash("fixed login bug")


def test_compute_content_hash_different_content_produces_different_hashes():
    assert compute_content_hash("fixed login bug") != compute_content_hash("deployed new feature")


def test_compute_content_hash_returns_sha256_hex_string():
    result = compute_content_hash("any content")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


# --- Layer 1 integration tests against real SQLite ---

@pytest.mark.asyncio
async def test_exact_duplicate_in_same_session_is_skipped(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    first_id = await mem.store_memory("fixed the login bug", "session-a")
    second_id = await mem.store_memory("fixed the login bug", "session-a")

    assert second_id == first_id

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]

    assert count == 1


@pytest.mark.asyncio
async def test_exact_duplicate_in_different_session_stores_as_new_row(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    first_id = await mem.store_memory("fixed the login bug", "session-a")
    second_id = await mem.store_memory("fixed the login bug", "session-b")

    assert second_id != first_id

    with mem.get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    assert total == 2


@pytest.mark.asyncio
async def test_case_and_whitespace_variants_deduplicate_within_session(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    first_id = await mem.store_memory("Fixed The Login Bug", "session-a")
    lower_id = await mem.store_memory("fixed the login bug", "session-a")
    padded_id = await mem.store_memory("  Fixed The Login Bug  ", "session-a")

    assert lower_id == first_id
    assert padded_id == first_id

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]

    assert count == 1


@pytest.mark.asyncio
async def test_content_hash_column_populated_on_all_writes_regardless_of_consolidation_flag(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", False)
    # Even with consolidation disabled, hash is still stored on every write.
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    memory_id = await mem.store_memory("some content to hash", "session-a")

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT content_hash FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()

    assert row is not None
    assert row[0] is not None
    assert len(row[0]) == 64


@pytest.mark.asyncio
async def test_hash_collision_stores_as_new_row_not_false_dedup(monkeypatch, tmp_path):
    # Simulate a SHA-256 collision: two different contents producing the same hash.
    # Both should store as separate rows because find_exact_duplicate compares
    # normalized content after the hash match — different content means no dedup.
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    # Must patch on memory_module — store_memory() calls the name bound in that namespace.
    monkeypatch.setattr(memory_module, "compute_content_hash", lambda _: "collision_hash")

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    first_id = await mem.store_memory("content one", "session-a")
    second_id = await mem.store_memory("content two", "session-a")

    assert second_id != first_id

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]

    assert count == 2


@pytest.mark.asyncio
async def test_consolidation_disabled_stores_duplicates_normally(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", False)
    # With consolidation disabled, identical writes always insert new rows.
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    first_id = await mem.store_memory("identical content", "session-a")
    second_id = await mem.store_memory("identical content", "session-a")

    assert second_id != first_id

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]

    assert count == 2


@pytest.mark.asyncio
async def test_concurrent_identical_writes_produce_one_row(monkeypatch, tmp_path):
    # Regression: check-then-insert race — two concurrent writes of the same content must
    # not bypass Layer 1 dedup and insert duplicate rows. BEGIN IMMEDIATE closes the gap.
    import asyncio
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    id_a, id_b = await asyncio.gather(
        mem.store_memory("duplicate content", "session-a"),
        mem.store_memory("duplicate content", "session-a"),
    )

    assert id_a == id_b

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]

    assert count == 1


@pytest.mark.asyncio
async def test_race_window_sealed_by_begin_immediate(monkeypatch, tmp_path):
    # Stronger concurrency regression: park both coroutines after the soft preflight
    # check and before BEGIN IMMEDIATE, then release them together. The under-lock
    # re-check must still collapse the duplicate write to a single row.
    import asyncio
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    original_find_semantic = memory_module.find_semantic_duplicate
    started = 0
    release_both = asyncio.Event()

    async def yielding_find_semantic(memory, content, session_name, threshold, query_vec=None):
        nonlocal started
        started += 1
        if started == 2:
            release_both.set()
        await release_both.wait()
        return await original_find_semantic(
            memory, content, session_name, threshold, query_vec=query_vec
        )

    monkeypatch.setattr(memory_module, "find_semantic_duplicate", yielding_find_semantic)

    id_a, id_b = await asyncio.gather(
        mem.store_memory("duplicate content", "session-a"),
        mem.store_memory("duplicate content", "session-a"),
    )

    assert id_a == id_b

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]

    assert count == 1
