"""The --rechunk backfill: re-split, fill, delete, and refuse.

Chunk sizing constants changed after rows were already written, and
migrate_embeddings re-embeds chunk_text in place, so stale boundaries survive
every migration. These tests cover each repair case plus the guards that keep the
backfill from writing mixed-dimension vectors or racing a live server.
"""

import sqlite3

import numpy as np
import pytest

from marm_mcp_server.config.settings import DEFAULT_SEMANTIC_DIM, DEFAULT_SEMANTIC_MODEL
from marm_mcp_server.core.memory_db import init_database
from marm_mcp_server.core.memory_utils import (
    DOC_CHUNK_OVERLAP_WORDS,
    DOC_CHUNK_TARGET_WORDS,
    DOC_CHUNK_THRESHOLD_WORDS,
    MEMORY_CHUNK_OVERLAP_WORDS,
    MEMORY_CHUNK_TARGET_WORDS,
    MEMORY_CHUNK_THRESHOLD_WORDS,
    _chunk_text,
)
from marm_mcp_server.utils.chunk_backfill import RechunkRefused, rechunk_memories
from marm_mcp_server.utils.embedding_state import (
    EMBEDDING_MODEL_SETTING,
    write_embedding_model_marker,
)


class CountingEncoder:
    """Real-shaped vectors, and a call log so tests can prove no encoding happened."""

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        texts = list(texts)
        self.calls.append(texts)
        return iter(
            np.full(DEFAULT_SEMANTIC_DIM, index + 1, dtype=np.float32)
            for index, _ in enumerate(texts)
        )


def _words(count: int) -> str:
    return " ".join(f"w{i}" for i in range(count))


def _memory_chunks(text: str) -> list[str]:
    return _chunk_text(
        text,
        threshold=MEMORY_CHUNK_THRESHOLD_WORDS,
        target_size=MEMORY_CHUNK_TARGET_WORDS,
        overlap=MEMORY_CHUNK_OVERLAP_WORDS,
    )


def _doc_chunks(text: str) -> list[str]:
    return _chunk_text(
        text,
        threshold=DOC_CHUNK_THRESHOLD_WORDS,
        target_size=DOC_CHUNK_TARGET_WORDS,
        overlap=DOC_CHUNK_OVERLAP_WORDS,
    )


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "memory.db"
    init_database(str(path))
    write_embedding_model_marker(str(path))
    return path


def _insert_memory(
    db_path,
    memory_id: str,
    content: str,
    *,
    context_type: str = "general",
    compaction_role: str | None = None,
    chunks: list[str] | None = None,
):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories"
            " (id, session_name, content, content_hash, timestamp, context_type,"
            "  compaction_role)"
            " VALUES (?, 's1', ?, ?, '2026-01-01T00:00:00+00:00', ?, ?)",
            (memory_id, content, f"hash-{memory_id}", context_type, compaction_role),
        )
        for index, chunk in enumerate(chunks or []):
            conn.execute(
                "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding)"
                " VALUES (?, ?, ?, ?)",
                (
                    memory_id,
                    index,
                    chunk,
                    np.zeros(DEFAULT_SEMANTIC_DIM, dtype=np.float32).tobytes(),
                ),
            )
        conn.commit()


def _stored(db_path, memory_id: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT chunk_text FROM memory_chunks WHERE memory_id = ?"
                " ORDER BY chunk_index",
                (memory_id,),
            )
        ]


def _run(db_path, encoder=None):
    encoder = encoder or CountingEncoder()
    result = rechunk_memories(
        str(db_path),
        concept_db_path=str(db_path.parent / "absent-concepts.db"),
        encoder_factory=lambda: encoder,
        progress=lambda _message: None,
    )
    return result, encoder


def test_oversplit_rows_are_resplit_to_current_config(db):
    """The legacy 150-word era left far more chunks than current config produces."""
    content = _words(1400)
    legacy = [_words(150) for _ in range(16)]
    _insert_memory(db, "m1", content, chunks=legacy)

    result, _ = _run(db)

    expected = _memory_chunks(content)
    assert _stored(db, "m1") == expected
    assert len(expected) < len(legacy), "fixture must actually shrink to be meaningful"
    assert result["memories_rechunked"] == 1
    assert result["chunks_before"] == 16
    assert result["chunks_after"] == len(expected)


def test_missing_chunks_are_filled(db):
    """The fire-and-forget loss case: over threshold, zero chunk rows."""
    content = _words(1100)
    _insert_memory(db, "m1", content, chunks=[])

    _run(db)

    assert _stored(db, "m1") == _memory_chunks(content)


def test_rows_below_threshold_lose_their_chunks(db):
    """A 166-word row would not be chunked at all today, so its chunks must go."""
    content = _words(166)
    _insert_memory(db, "m1", content, chunks=[_words(83), _words(83)])

    result, encoder = _run(db)

    assert _stored(db, "m1") == []
    assert result["chunks_after"] == 0
    assert encoder.calls == [], "a delete-only run must not load or call the encoder"


def test_correct_rows_are_skipped_without_encoding(db):
    content = _words(1100)
    _insert_memory(db, "m1", content, chunks=_memory_chunks(content))

    result, encoder = _run(db)

    assert result["memories_rechunked"] == 0
    assert result["memories_skipped"] == 1
    assert encoder.calls == [], (
        "the idempotence check must be textual, not vector-based"
    )


def test_second_run_is_idempotent(db):
    content = _words(1400)
    _insert_memory(db, "m1", content, chunks=[_words(150) for _ in range(16)])

    _run(db)
    first_pass = _stored(db, "m1")
    result, encoder = _run(db)

    assert _stored(db, "m1") == first_pass
    assert result["memories_rechunked"] == 0
    assert encoder.calls == []


def test_short_unchunked_rows_are_left_alone(db):
    """The common case: most memories are short and have no chunks. Nothing to do."""
    _insert_memory(db, "m1", _words(40), chunks=[])

    result, encoder = _run(db)

    assert result["memories_rechunked"] == 0
    assert result["memories_skipped"] == 0
    assert encoder.calls == []


def test_doc_mirrors_use_the_doc_profile_and_converge(db):
    """context_type = 'doc' is the discriminator, and the result must be stable."""
    content = _words(1400)
    _insert_memory(db, "m1", content, context_type="doc", chunks=[_words(100)])

    _run(db)

    expected = _doc_chunks(content)
    assert _stored(db, "m1") == expected
    assert expected != _memory_chunks(content), (
        "fixture length must distinguish the two profiles"
    )

    result, _ = _run(db)
    assert result["memories_rechunked"] == 0, (
        "doc rows must converge, not rewrite forever"
    )


def test_documentation_indexed_rows_use_the_memory_profile(db):
    """services/documentation.py rows carry doc-ish context types but are not mirrors.

    They go through _store_memory, so the memory profile applies. Routing them to
    the doc profile because they came from .md files would be wrong.
    """
    content = _words(900)
    _insert_memory(db, "m1", content, context_type="installation", chunks=[])

    _run(db)

    assert _stored(db, "m1") == _memory_chunks(content)
    assert _doc_chunks(content) == [], (
        "fixture must sit between the two thresholds to be meaningful"
    )


def test_compaction_source_rows_are_skipped(db):
    """The semantic scan excludes them, so encoding their chunks is wasted work."""
    content = _words(1100)
    _insert_memory(db, "m1", content, compaction_role="source", chunks=[])

    result, encoder = _run(db)

    assert _stored(db, "m1") == []
    assert result["memories_rechunked"] == 0
    assert encoder.calls == []


def test_refuses_on_embedding_marker_mismatch_and_writes_nothing(db):
    content = _words(1400)
    legacy = [_words(150) for _ in range(16)]
    _insert_memory(db, "m1", content, chunks=legacy)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE user_settings SET value = 'some/other-model' WHERE key = ?",
            (EMBEDDING_MODEL_SETTING,),
        )
        conn.commit()

    with pytest.raises(RechunkRefused, match="migrate-embeddings"):
        _run(db)

    assert _stored(db, "m1") == legacy, "a refused run must leave chunk rows untouched"


def test_refuses_on_wrong_dimension_vectors(db):
    """A matching marker is not enough: stale dimensions are the same hazard."""
    content = _words(1400)
    _insert_memory(db, "m1", content, chunks=[])
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE memories SET embedding = ? WHERE id = 'm1'",
            (np.ones(384, dtype=np.float32).tobytes(),),
        )
        conn.commit()

    with pytest.raises(RechunkRefused, match="migrate-embeddings"):
        _run(db)

    assert _stored(db, "m1") == []


def test_missing_database_is_a_no_op(tmp_path):
    result = rechunk_memories(str(tmp_path / "absent.db"))

    assert result["memories_rechunked"] == 0
    assert result["chunks_after"] == 0


def test_marker_matching_the_configured_model_is_accepted(db):
    """Guard against the refusal firing on a healthy database."""
    content = _words(1100)
    _insert_memory(db, "m1", content, chunks=[])

    _run(db)

    assert _stored(db, "m1") == _memory_chunks(content)
    assert DEFAULT_SEMANTIC_MODEL, "sanity: a model must be configured"
