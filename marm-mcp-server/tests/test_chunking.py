"""Tests for embedding chunking feature (memory_chunks sidecar table)."""

import sqlite3
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest

from marm_mcp_server.core.memory import (
    MARMMemory,
    _chunk_text,
    _score_chunk_aware,
    CHUNK_THRESHOLD_WORDS,
    CHUNK_TOKEN_LIMIT,
    CHUNK_OVERLAP_TOKENS,
)


# --- _chunk_text unit tests ---


def test_chunk_text_returns_empty_for_short_content():
    words = ["word"] * (CHUNK_THRESHOLD_WORDS - 1)
    assert _chunk_text(" ".join(words)) == []


def test_chunk_text_returns_empty_at_exact_threshold():
    words = ["word"] * CHUNK_THRESHOLD_WORDS
    assert _chunk_text(" ".join(words)) == []


def test_chunk_text_splits_content_above_threshold():
    words = ["word"] * (CHUNK_THRESHOLD_WORDS + 1)
    chunks = _chunk_text(" ".join(words))
    assert len(chunks) >= 1


def test_chunk_text_chunk_size_does_not_exceed_limit():
    words = [f"w{i}" for i in range(500)]
    chunks = _chunk_text(" ".join(words))
    for chunk in chunks:
        assert len(chunk.split()) <= CHUNK_TOKEN_LIMIT


def test_chunk_text_chunks_overlap_correctly():
    words = [f"w{i}" for i in range(300)]
    chunks = _chunk_text(" ".join(words))
    step = CHUNK_TOKEN_LIMIT - CHUNK_OVERLAP_TOKENS
    # Second chunk should start at word `step`, not word `CHUNK_TOKEN_LIMIT`
    second_chunk_words = chunks[1].split()
    assert second_chunk_words[0] == words[step]


def test_chunk_text_covers_all_words():
    words = [f"w{i}" for i in range(400)]
    text = " ".join(words)
    chunks = _chunk_text(text)
    all_chunk_words = set()
    for chunk in chunks:
        all_chunk_words.update(chunk.split())
    assert all(w in all_chunk_words for w in words)


# --- _score_chunk_aware unit tests ---


def _make_unit_vec(dim: int = 384) -> np.ndarray:
    v = np.ones(dim, dtype=np.float32)
    return v / np.linalg.norm(v)


def _make_sqlite_row(mem_id: str, embedding_bytes: bytes | None = None):
    """Return a dict-like object matching the sqlite3.Row fields used by _score_chunk_aware."""
    return {
        "id": mem_id,
        "session_name": "test",
        "content": "test content",
        "embedding": embedding_bytes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context_type": "general",
        "metadata": "{}",
    }


def test_score_chunk_aware_uses_parent_embedding_when_no_chunks():
    unit_vec = _make_unit_vec()
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, unit_vec.tobytes())
    results, skipped = _score_chunk_aware([row], {}, unit_vec)
    assert len(results) == 1
    assert abs(results[0][1] - 1.0) < 1e-4
    assert skipped == 0


def test_score_chunk_aware_uses_chunk_embeddings_over_parent():
    unit_vec = _make_unit_vec()
    # Parent embedding is zero (would score 0), chunk embedding is unit (scores 1.0)
    zero_bytes = np.zeros(384, dtype=np.float32).tobytes()
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, zero_bytes)
    chunks_by_id = {mem_id: [unit_vec.tobytes()]}
    results, _ = _score_chunk_aware([row], chunks_by_id, unit_vec)
    assert len(results) == 1
    assert abs(results[0][1] - 1.0) < 1e-4


def test_score_chunk_aware_takes_max_over_chunks():
    query = _make_unit_vec()
    # One chunk aligned with query (score ~1.0), one orthogonal (score ~0)
    ortho = np.zeros(384, dtype=np.float32)
    ortho[0] = 1.0
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, None)
    chunks_by_id = {mem_id: [query.tobytes(), ortho.tobytes()]}
    results, _ = _score_chunk_aware([row], chunks_by_id, query)
    assert len(results) == 1
    # MAX should be close to 1.0 (from the aligned chunk), not 0.5 (average)
    assert results[0][1] > 0.9


def test_score_chunk_aware_deduplicates_to_one_result_per_memory():
    unit_vec = _make_unit_vec()
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, unit_vec.tobytes())
    # Even if multiple chunks exist, only one result per memory
    chunks_by_id = {
        mem_id: [unit_vec.tobytes(), unit_vec.tobytes(), unit_vec.tobytes()]
    }
    results, _ = _score_chunk_aware([row], chunks_by_id, unit_vec)
    assert len(results) == 1


def test_score_chunk_aware_skips_memory_with_no_embedding_and_no_chunks():
    unit_vec = _make_unit_vec()
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, None)
    results, _ = _score_chunk_aware([row], {}, unit_vec)
    assert results == []


def test_score_chunk_aware_handles_mixed_chunked_and_unchunked():
    unit_vec = _make_unit_vec()
    id_chunked = str(uuid.uuid4())
    id_plain = str(uuid.uuid4())
    rows = [
        _make_sqlite_row(id_chunked, None),
        _make_sqlite_row(id_plain, unit_vec.tobytes()),
    ]
    chunks_by_id = {id_chunked: [unit_vec.tobytes()]}
    results, _ = _score_chunk_aware(rows, chunks_by_id, unit_vec)
    result_ids = {r[0]["id"] for r in results}
    assert id_chunked in result_ids
    assert id_plain in result_ids
    assert len(results) == 2


# --- DB schema tests ---


@pytest.mark.asyncio
async def test_memory_chunks_table_created_on_init(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "memory_chunks" in tables


@pytest.mark.asyncio
async def test_memory_chunks_index_created_on_init(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    assert "idx_memory_chunks_memory_id" in indexes


@pytest.mark.asyncio
async def test_short_content_writes_no_chunk_rows(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    short = "This is a short memory."
    mid = await mem.store_memory(short, "test")

    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
    assert count == 0


@pytest.mark.asyncio
async def test_cascade_delete_removes_chunk_rows(tmp_path):
    """Deleting a parent memory must cascade to memory_chunks."""
    db_path = str(tmp_path / "memory.db")
    mem = MARMMemory(db_path)
    mem._encoder_failed = True

    unit_vec = _make_unit_vec()
    mid = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, context_type, metadata)"
            " VALUES (?, 'test', 'content', ?, 'general', '{}')",
            (mid, ts),
        )
        conn.execute(
            "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding)"
            " VALUES (?, 0, 'chunk text', ?)",
            (mid, unit_vec.tobytes()),
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
    assert count == 0


@pytest.mark.asyncio
async def test_encoder_unavailable_long_content_no_crash_no_chunks(tmp_path):
    """Long content with no encoder: memory stored, no chunks, no exception."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    long_content = " ".join(["word"] * (CHUNK_THRESHOLD_WORDS + 50))
    mid = await mem.store_memory(long_content, "test")

    assert mid is not None
    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
    assert count == 0


# --- Scoring integration tests (real embeddings if available) ---


@pytest.mark.asyncio
async def test_recall_returns_parent_content_not_chunk_text(tmp_path):
    """recall_similar must return full parent memory content, not chunk text."""
    db_path = str(tmp_path / "memory.db")
    mem = MARMMemory(db_path)

    if not mem._load_encoder_lazily():
        pytest.skip("Encoder not available")

    unit_vec = _make_unit_vec()
    mid = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    parent_content = (
        "This is the full parent memory content that agents should receive."
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, embedding, timestamp, context_type, metadata)"
            " VALUES (?, 'test', ?, ?, ?, 'general', '{}')",
            (mid, parent_content, unit_vec.tobytes(), ts),
        )
        conn.execute(
            "INSERT INTO memories_fts(rowid, content) SELECT rowid, content FROM memories WHERE id = ?",
            (mid,),
        )
        conn.execute(
            "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding)"
            " VALUES (?, 0, 'chunk text only', ?)",
            (mid, unit_vec.tobytes()),
        )
        conn.commit()

    results = await mem.recall_similar("parent memory content", session="test", limit=5)
    assert any(r["id"] == mid for r in results)
    matched = next(r for r in results if r["id"] == mid)
    assert matched["content"] == parent_content
    assert "chunk text only" not in matched["content"]


@pytest.mark.asyncio
async def test_chunked_memory_appears_once_in_results(tmp_path):
    """A memory with multiple chunk matches must appear exactly once in recall results."""
    db_path = str(tmp_path / "memory.db")
    mem = MARMMemory(db_path)

    if not mem._load_encoder_lazily():
        pytest.skip("Encoder not available")

    unit_vec = _make_unit_vec()
    mid = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, embedding, timestamp, context_type, metadata)"
            " VALUES (?, 'test', 'architecture design decision', ?, ?, 'general', '{}')",
            (mid, unit_vec.tobytes(), ts),
        )
        conn.execute(
            "INSERT INTO memories_fts(rowid, content) SELECT rowid, content FROM memories WHERE id = ?",
            (mid,),
        )
        for i in range(5):
            conn.execute(
                "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding)"
                " VALUES (?, ?, 'architecture design', ?)",
                (mid, i, unit_vec.tobytes()),
            )
        conn.commit()

    results = await mem.recall_similar("architecture design", session="test", limit=10)
    ids = [r["id"] for r in results]
    assert ids.count(mid) == 1


@pytest.mark.asyncio
async def test_merge_path_deletes_stale_chunks(tmp_path):
    """update_memory must remove old chunk rows before writing new ones."""
    db_path = str(tmp_path / "memory.db")
    mem = MARMMemory(db_path)
    mem._encoder_failed = True

    unit_vec = _make_unit_vec()
    mid = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, embedding, timestamp, context_type, metadata)"
            " VALUES (?, 'test', 'original content', ?, ?, 'general', '{}')",
            (mid, unit_vec.tobytes(), ts),
        )
        for i in range(3):
            conn.execute(
                "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding)"
                " VALUES (?, ?, 'stale chunk', ?)",
                (mid, i, unit_vec.tobytes()),
            )
        conn.commit()

    await mem.update_memory(mid, "new merged content")

    with sqlite3.connect(db_path) as conn:
        remaining = conn.execute(
            "SELECT chunk_text FROM memory_chunks WHERE memory_id = ?", (mid,)
        ).fetchall()

    # All stale chunks must be gone (encoder is disabled so no new chunks written)
    stale = [r[0] for r in remaining if r[0] == "stale chunk"]
    assert stale == []
