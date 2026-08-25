import sqlite3
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest

from marm_mcp_server.config.settings import DEFAULT_SEMANTIC_DIM
from marm_mcp_server.core.memory import (
    DOC_CHUNK_OVERLAP_WORDS,
    DOC_CHUNK_TARGET_WORDS,
    DOC_CHUNK_THRESHOLD_WORDS,
    MEMORY_CHUNK_OVERLAP_WORDS,
    MEMORY_CHUNK_TARGET_WORDS,
    MEMORY_CHUNK_THRESHOLD_WORDS,
    MARMMemory,
    _chunk_text,
    _score_chunk_aware,
)
from marm_mcp_server.core.memory_ops import _update_memory
from marm_mcp_server.core.memory_utils import _split_evenly


def _mem_chunk(text: str) -> list[str]:
    return _chunk_text(
        text,
        threshold=MEMORY_CHUNK_THRESHOLD_WORDS,
        target_size=MEMORY_CHUNK_TARGET_WORDS,
        overlap=MEMORY_CHUNK_OVERLAP_WORDS,
    )


def test_chunk_text_returns_empty_for_short_content():
    words = ["word"] * (MEMORY_CHUNK_THRESHOLD_WORDS - 1)
    assert _mem_chunk(" ".join(words)) == []


def test_chunk_text_returns_empty_at_exact_threshold():
    words = ["word"] * MEMORY_CHUNK_THRESHOLD_WORDS
    assert _mem_chunk(" ".join(words)) == []


def test_chunk_text_splits_content_above_threshold():
    words = ["word"] * (MEMORY_CHUNK_THRESHOLD_WORDS + 1)
    chunks = _mem_chunk(" ".join(words))
    assert len(chunks) >= 1


def test_chunk_text_covers_all_words():
    words = [f"w{i}" for i in range(MEMORY_CHUNK_THRESHOLD_WORDS + 100)]
    text = " ".join(words)
    chunks = _mem_chunk(text)
    all_chunk_words = set()
    for chunk in chunks:
        all_chunk_words.update(chunk.split())
    assert all(w in all_chunk_words for w in words)


def test_chunk_text_doc_profile_uses_larger_threshold_and_target():
    n = MEMORY_CHUNK_THRESHOLD_WORDS + 50
    words = [f"w{i}" for i in range(n)]
    text = " ".join(words)

    memory_chunks = _mem_chunk(text)
    doc_chunks = _chunk_text(
        text,
        threshold=DOC_CHUNK_THRESHOLD_WORDS,
        target_size=DOC_CHUNK_TARGET_WORDS,
        overlap=DOC_CHUNK_OVERLAP_WORDS,
    )

    assert len(memory_chunks) >= 1
    assert doc_chunks == []


def test_chunk_text_even_split_avoids_tiny_trailing_fragment():
    """The user-identified failure mode: content just over threshold must
    not split into one full-size chunk plus a tiny low-value fragment
    (e.g. 250 + 30 words). Uses the same threshold/target shape as the
    original bug report (180/150) so the assertion targets the algorithm
    itself, independent of whichever profile constants are configured."""
    n = 280
    words = [f"w{i}" for i in range(n)]
    chunks = _chunk_text(" ".join(words), threshold=180, target_size=150, overlap=50)

    assert len(chunks) == 2
    sizes = [len(c.split()) for c in chunks]
    assert min(sizes) / max(sizes) > 0.5


def test_chunk_text_memory_profile_produces_balanced_chunks_at_threshold_edge():
    """With the configured memory profile (threshold == 2x target), the
    smallest content that chunks at all lands on 3 balanced spans, not a
    full-size chunk plus a sliver -- confirms the fix holds for the actual
    shipped constants, not just the algorithm in isolation."""
    n = MEMORY_CHUNK_THRESHOLD_WORDS + 1
    words = [f"w{i}" for i in range(n)]
    chunks = _mem_chunk(" ".join(words))

    assert len(chunks) == 3
    sizes = [len(c.split()) for c in chunks]
    assert min(sizes) / max(sizes) > 0.5


def test_split_evenly_distributes_remainder_across_first_spans():
    words = list(range(10))
    spans = _split_evenly(words, 3)
    sizes = [end - start for start, end in spans]
    assert sizes == [4, 3, 3]
    assert spans[0] == (0, 4)
    assert spans[-1][1] == 10


def test_split_evenly_covers_all_indices_with_no_gaps_or_overlap():
    words = list(range(97))
    spans = _split_evenly(words, 7)
    covered = []
    for start, end in spans:
        covered.extend(range(start, end))
    assert covered == list(range(97))


def _make_unit_vec(dim: int = DEFAULT_SEMANTIC_DIM) -> np.ndarray:
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
    zero_bytes = np.zeros(DEFAULT_SEMANTIC_DIM, dtype=np.float32).tobytes()
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, zero_bytes)
    chunks_by_id = {mem_id: [unit_vec.tobytes()]}
    results, _ = _score_chunk_aware([row], chunks_by_id, unit_vec)
    assert len(results) == 1
    assert abs(results[0][1] - 1.0) < 1e-4


def test_score_chunk_aware_takes_max_over_chunks():
    query = _make_unit_vec()
    ortho = np.zeros(DEFAULT_SEMANTIC_DIM, dtype=np.float32)
    ortho[0] = 1.0
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, None)
    chunks_by_id = {mem_id: [query.tobytes(), ortho.tobytes()]}
    results, _ = _score_chunk_aware([row], chunks_by_id, query)
    assert len(results) == 1
    assert results[0][1] > 0.9


def test_score_chunk_aware_deduplicates_to_one_result_per_memory():
    unit_vec = _make_unit_vec()
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, unit_vec.tobytes())
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


def test_score_chunk_aware_batched_path_counts_wrong_dim_chunk_as_skipped():
    """Batched scoring must still skip a wrong-dimension chunk, score the
    remaining good chunk, and count the skip -- the collapse cannot silently
    drop dim mismatches."""
    unit_vec = _make_unit_vec()
    wrong_dim = np.ones(DEFAULT_SEMANTIC_DIM + 1, dtype=np.float32)
    wrong_dim /= np.linalg.norm(wrong_dim)
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, None)
    chunks_by_id = {mem_id: [wrong_dim.tobytes(), unit_vec.tobytes()]}

    results, skipped = _score_chunk_aware([row], chunks_by_id, unit_vec)

    assert skipped == 1
    assert len(results) == 1
    assert abs(results[0][1] - 1.0) < 1e-4


def test_score_chunk_aware_batched_path_excludes_wrong_dim_parent():
    """A memory whose only embedding is the wrong dimension is excluded and
    counted as skipped, even in the batched path."""
    unit_vec = _make_unit_vec()
    wrong_dim = np.ones(DEFAULT_SEMANTIC_DIM + 1, dtype=np.float32)
    mem_id = str(uuid.uuid4())
    row = _make_sqlite_row(mem_id, wrong_dim.tobytes())

    results, skipped = _score_chunk_aware([row], {}, unit_vec)

    assert results == []
    assert skipped == 1


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

    long_content = " ".join(["word"] * (MEMORY_CHUNK_THRESHOLD_WORDS + 50))
    mid = await mem.store_memory(long_content, "test")

    assert mid is not None
    with mem.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
    assert count == 0


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

    await _update_memory(mem, mid, "new merged content")

    with sqlite3.connect(db_path) as conn:
        remaining = conn.execute(
            "SELECT chunk_text FROM memory_chunks WHERE memory_id = ?", (mid,)
        ).fetchall()

    stale = [r[0] for r in remaining if r[0] == "stale chunk"]
    assert stale == []


@pytest.mark.asyncio
async def test_write_chunks_same_content_hash_twice_does_not_duplicate_rows(tmp_path):
    """Two resaves with unchanged content share the same content_hash, so
    _write_chunks' own staleness guard (compares expected_content_hash
    against memories.content_hash) can't tell them apart -- this is
    exactly what a doc save() followed immediately by an identical resave
    produces. Without a uniqueness guard on (memory_id, chunk_index), both
    fire-and-forget writes could each insert a full set of chunk rows.
    INSERT OR REPLACE plus the unique index must keep this idempotent."""
    from marm_mcp_server.core.memory_utils import _write_chunks

    db_path = str(tmp_path / "memory.db")
    mem = MARMMemory(db_path)
    mem.encoder = type(
        "_FakeEncoder", (), {"encode": staticmethod(lambda text: _make_unit_vec())}
    )()

    mid = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    content_hash = "same-hash-both-writes"
    chunks = ["chunk one text", "chunk two text"]

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories "
            "(id, session_name, content, timestamp, context_type, metadata, content_hash)"
            " VALUES (?, 'test', 'content', ?, 'general', '{}', ?)",
            (mid, ts, content_hash),
        )
        conn.commit()

    await _write_chunks(mem, db_path, mid, chunks, content_hash)
    await _write_chunks(mem, db_path, mid, chunks, content_hash)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT chunk_index, chunk_text FROM memory_chunks WHERE memory_id = ? "
            "ORDER BY chunk_index",
            (mid,),
        ).fetchall()

    assert len(rows) == len(chunks), (
        "duplicate chunk rows accumulated across identical-content writes"
    )
    assert [r[1] for r in rows] == chunks


def test_init_database_collapses_preexisting_duplicate_chunks_before_indexing(
    tmp_path,
):
    """A database written before idx_memory_chunks_dedup existed could
    already contain duplicate (memory_id, chunk_index) rows from the exact
    race test_write_chunks_same_content_hash_twice_does_not_duplicate_rows
    guards against. CREATE UNIQUE INDEX on such a database must not raise
    -- init_database has to collapse existing duplicates first (keeping
    the newest row) rather than leaving upgraded users unable to start
    the server at all."""
    from marm_mcp_server.core.memory_db import init_database

    db_path = tmp_path / "memory.db"
    init_database(str(db_path))

    mid = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_memory_chunks_dedup")
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, context_type, metadata)"
            " VALUES (?, 'test', 'content', ?, 'general', '{}')",
            (mid, ts),
        )
        conn.executemany(
            "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding)"
            " VALUES (?, ?, ?, ?)",
            [
                (mid, 0, "stale duplicate", b"\x00" * 4),
                (mid, 0, "current duplicate", b"\x01" * 4),
                (mid, 1, "only copy", b"\x02" * 4),
            ],
        )
        conn.commit()

    init_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        rows = conn.execute(
            "SELECT chunk_index, chunk_text FROM memory_chunks WHERE memory_id = ? "
            "ORDER BY chunk_index",
            (mid,),
        ).fetchall()

    assert "idx_memory_chunks_dedup" in indexes
    assert rows == [(0, "current duplicate"), (1, "only copy")]
