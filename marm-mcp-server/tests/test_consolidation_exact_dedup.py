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
    mem = MARMMemory(str(tmp_path / "memory.db"))
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
    mem = MARMMemory(str(tmp_path / "memory.db"))
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
async def test_content_hash_column_populated_on_all_writes_regardless_of_consolidation_flag(tmp_path):
    # CONSOLIDATION_ENABLED defaults to False — hash is still stored on every write
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
async def test_consolidation_disabled_stores_duplicates_normally(tmp_path):
    # With CONSOLIDATION_ENABLED=False (default), identical writes always insert new rows
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
