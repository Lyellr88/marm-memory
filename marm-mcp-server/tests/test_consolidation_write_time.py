"""Tests for consolidation Layer 2 — semantic near-duplicate merge."""

import json

import numpy as np
import pytest

from marm_mcp_server.core.consolidation import find_semantic_duplicate
from marm_mcp_server.core.memory import MARMMemory


# --- update_memory direct tests ---

@pytest.mark.asyncio
async def test_update_memory_appends_content(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    memory_id = await mem.store_memory("original content", "session-a")
    await mem.update_memory(memory_id, "additional content")

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT content FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()

    assert "original content" in row[0]
    assert "[merged] additional content" in row[0]


@pytest.mark.asyncio
async def test_update_memory_records_merge_history_in_metadata(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    memory_id = await mem.store_memory("original content", "session-a")
    await mem.update_memory(memory_id, "first merge")
    await mem.update_memory(memory_id, "second merge")

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT metadata FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()

    metadata = json.loads(row[0])
    assert "merge_history" in metadata
    assert len(metadata["merge_history"]) == 2
    assert metadata["merge_history"][0]["content_preview"] == "first merge"
    assert metadata["merge_history"][1]["content_preview"] == "second merge"
    assert "merged_at" in metadata["merge_history"][0]


@pytest.mark.asyncio
async def test_update_memory_is_silent_for_missing_id(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    # Should not raise — returns None gracefully
    await mem.update_memory("nonexistent-id", "some content")


@pytest.mark.asyncio
async def test_update_memory_recomputes_content_hash(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    memory_id = await mem.store_memory("original content", "session-a")

    with mem.get_connection() as conn:
        original_hash = conn.execute(
            "SELECT content_hash FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()[0]

    await mem.update_memory(memory_id, "additional content")

    with mem.get_connection() as conn:
        updated_hash = conn.execute(
            "SELECT content_hash FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()[0]

    assert updated_hash != original_hash
    assert len(updated_hash) == 64


@pytest.mark.asyncio
async def test_update_memory_clears_stale_embedding_when_encoder_unavailable(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))

    # Seed a row with a fake embedding so we can verify the stale vector is cleared.
    import uuid
    from datetime import datetime, timezone
    memory_id = str(uuid.uuid4())
    fake_embedding = b"\x00" * 16
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (memory_id, "session-a", "original content", fake_embedding, "abc123", datetime.now(timezone.utc).isoformat(), "general", "{}"),
        )

    mem._encoder_failed = True
    await mem.update_memory(memory_id, "additional content")

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT embedding FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()

    assert row[0] is None


# --- find_semantic_duplicate unit tests ---

@pytest.mark.asyncio
async def test_find_semantic_duplicate_returns_id_when_similarity_above_threshold(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))

    monkeypatched_recall_called = []

    async def mock_recall(query, session=None, limit=5, query_vec=None):
        monkeypatched_recall_called.append(query)
        return [{"id": "existing-id", "similarity": 0.95, "content": "similar content"}]

    mem._load_encoder_lazily = lambda: True
    mem.recall_similar = mock_recall

    result = await find_semantic_duplicate(mem, "near duplicate content", "session-a", 0.92)

    assert result == "existing-id"
    assert len(monkeypatched_recall_called) == 1


@pytest.mark.asyncio
async def test_find_semantic_duplicate_returns_none_when_similarity_below_threshold(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))

    async def mock_recall(query, session=None, limit=5, query_vec=None):
        return [{"id": "existing-id", "similarity": 0.85, "content": "similar content"}]

    mem._load_encoder_lazily = lambda: True
    mem.recall_similar = mock_recall

    result = await find_semantic_duplicate(mem, "different content", "session-a", 0.92)

    assert result is None


@pytest.mark.asyncio
async def test_find_semantic_duplicate_returns_none_when_no_results(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))

    async def mock_recall(query, session=None, limit=5, query_vec=None):
        return []

    mem._load_encoder_lazily = lambda: True
    mem.recall_similar = mock_recall

    result = await find_semantic_duplicate(mem, "content", "session-a", 0.92)

    assert result is None


@pytest.mark.asyncio
async def test_find_semantic_duplicate_returns_none_when_encoder_unavailable(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    result = await find_semantic_duplicate(mem, "content", "session-a", 0.92)

    assert result is None


# --- store_memory Layer 2 integration tests ---

@pytest.mark.asyncio
async def test_semantic_merge_returns_existing_id_and_skips_new_row(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    first_id = await mem.store_memory("fixed the authentication bug in login flow", "session-a")

    async def mock_semantic_dup(memory, content, session_name, threshold, query_vec=None):
        return first_id

    monkeypatch.setattr(memory_module, "find_semantic_duplicate", mock_semantic_dup)

    second_id = await mem.store_memory("auth error resolved in login flow", "session-a")

    assert second_id == first_id

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]

    assert count == 1


@pytest.mark.asyncio
async def test_semantic_merge_writes_merged_content_to_existing_row(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    first_id = await mem.store_memory("fixed the authentication bug", "session-a")

    async def mock_semantic_dup(memory, content, session_name, threshold, query_vec=None):
        return first_id

    monkeypatch.setattr(memory_module, "find_semantic_duplicate", mock_semantic_dup)

    await mem.store_memory("auth error resolved", "session-a")

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT content, metadata FROM memories WHERE id = ?", (first_id,)
        ).fetchone()

    assert "[merged] auth error resolved" in row[0]
    metadata = json.loads(row[1])
    assert len(metadata["merge_history"]) == 1


@pytest.mark.asyncio
async def test_dissimilar_content_stores_as_new_row(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))

    class FakeEncoder:
        def encode(self, text):
            return np.ones(3, dtype=np.float32)

    mem.encoder = FakeEncoder()

    first_id = await mem.store_memory("fixed the authentication bug", "session-a")

    async def mock_no_match(memory, content, session_name, threshold, query_vec=None):
        assert query_vec is not None
        return None

    monkeypatch.setattr(memory_module, "find_semantic_duplicate", mock_no_match)

    second_id = await mem.store_memory("deployed kubernetes cluster", "session-a")

    assert second_id != first_id

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]

    assert count == 2


@pytest.mark.asyncio
async def test_encoder_failure_skips_layer2_and_stores_normally(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True  # encoder unavailable — Layer 2 must not block write

    first_id = await mem.store_memory("fixed the authentication bug", "session-a")
    second_id = await mem.store_memory("auth error resolved in login flow", "session-a")

    assert second_id != first_id

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]

    assert count == 2


@pytest.mark.asyncio
async def test_find_semantic_duplicate_passes_correct_session_to_recall(tmp_path):
    # Verifies recall_similar is called with the write's session_name, not a different session.
    mem = MARMMemory(str(tmp_path / "memory.db"))

    sessions_seen = []

    async def mock_recall(query, session=None, limit=5, query_vec=None):
        sessions_seen.append(session)
        return []

    mem._load_encoder_lazily = lambda: True
    mem.recall_similar = mock_recall

    await find_semantic_duplicate(mem, "some content", "session-b", 0.92)

    assert sessions_seen == ["session-b"]


@pytest.mark.asyncio
async def test_similar_content_in_different_session_stores_as_new_row(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    first_id = await mem.store_memory("fixed the authentication bug", "session-a")

    # find_semantic_duplicate is session-scoped; no match exists in session-b
    async def mock_no_cross_session_match(memory, content, session_name, threshold, query_vec=None):
        assert session_name == "session-b"
        return None

    monkeypatch.setattr(memory_module, "find_semantic_duplicate", mock_no_cross_session_match)

    second_id = await mem.store_memory("auth error resolved in login", "session-b")

    assert second_id != first_id

    with mem.get_connection() as conn:
        a_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-a",)
        ).fetchone()[0]
        b_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?", ("session-b",)
        ).fetchone()[0]

    assert a_count == 1
    assert b_count == 1
