import sqlite3

import numpy as np
import pytest

from marm_mcp_server.config.settings import (
    DEFAULT_SEMANTIC_DIM,
    DEFAULT_SEMANTIC_MODEL,
)
from marm_mcp_server.core.concept_db import init_concept_database
from marm_mcp_server.core.memory_db import init_database
from marm_mcp_server.utils import embedding_migration
from marm_mcp_server.utils.embedding_migration import migrate_embeddings
from marm_mcp_server.utils.embedding_state import inspect_embedding_state


def _vector(dim: int) -> bytes:
    return np.ones(dim, dtype=np.float32).tobytes()


class FakeEncoder:
    def __init__(self, *, fail_on: str | None = None, dim: int = DEFAULT_SEMANTIC_DIM):
        self.fail_on = fail_on
        self.dim = dim
        self.calls = []

    def embed(self, texts):
        texts = list(texts)
        self.calls.append(texts)
        if self.fail_on and any(self.fail_on in text for text in texts):
            raise RuntimeError("injected encoder failure")
        return iter(
            np.full(self.dim, index + 1, dtype=np.float32)
            for index, _ in enumerate(texts)
        )


def _seed_databases(memory_path, concept_path):
    init_database(str(memory_path))
    with sqlite3.connect(memory_path) as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, embedding, timestamp) "
            "VALUES ('m1', 's1', 'memory text', ?, '2026-01-01T00:00:00Z')",
            (_vector(384),),
        )
        conn.execute(
            "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding) "
            "VALUES ('m1', 0, 'chunk text', ?)",
            (_vector(384),),
        )
        conn.execute(
            "INSERT INTO notebook_entries (name, data, embedding) "
            "VALUES ('n1', 'notebook text', ?)",
            (_vector(384),),
        )
    init_concept_database(str(concept_path))
    with sqlite3.connect(concept_path) as conn:
        conn.execute(
            "INSERT INTO entities "
            "(name, type, session_name, project, name_embedding) "
            "VALUES ('entity text', 'concept', 's1', 'p1', ?)",
            (_vector(384),),
        )


def test_migrates_both_databases_then_sets_marker_and_is_idempotent(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "concept.db"
    _seed_databases(memory_path, concept_path)
    first_encoder = FakeEncoder()

    result = migrate_embeddings(
        str(memory_path),
        str(concept_path),
        batch_size=2,
        encoder_factory=lambda: first_encoder,
        progress=lambda _message: None,
    )

    assert result == {"rows_migrated": 4, "concept_db_present": True}
    state = inspect_embedding_state(str(memory_path), str(concept_path))
    assert state.compatible
    assert state.marker == DEFAULT_SEMANTIC_MODEL

    second_encoder = FakeEncoder()
    second = migrate_embeddings(
        str(memory_path),
        str(concept_path),
        encoder_factory=lambda: second_encoder,
        progress=lambda _message: None,
    )
    assert second["rows_migrated"] == 0
    assert second_encoder.calls == [["MARM embedding migration dimension check"]]


def test_migrates_same_dimension_vectors_when_model_marker_differs(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "concept.db"
    init_database(str(memory_path))
    with sqlite3.connect(memory_path) as conn:
        conn.execute(
            "INSERT INTO notebook_entries (name, data, embedding) VALUES (?, ?, ?)",
            ("n1", "same-dimension text", _vector(DEFAULT_SEMANTIC_DIM)),
        )
        conn.execute(
            "INSERT INTO notebook_entries (name, data, embedding) VALUES (?, ?, ?)",
            ("n2", "second same-dimension text", _vector(DEFAULT_SEMANTIC_DIM)),
        )
        conn.execute(
            "INSERT INTO user_settings (key, value) VALUES ('embedding_model', ?)",
            ("other-512-dimension-model",),
        )

    encoder = FakeEncoder()
    result = migrate_embeddings(
        str(memory_path),
        str(concept_path),
        batch_size=1,
        encoder_factory=lambda: encoder,
        progress=lambda _message: None,
    )

    assert result == {"rows_migrated": 2, "concept_db_present": False}
    assert encoder.calls == [
        ["MARM embedding migration dimension check"],
        ["same-dimension text"],
        ["second same-dimension text"],
    ]
    assert inspect_embedding_state(str(memory_path), str(concept_path)).compatible


def test_backfills_missing_embeddings_during_normal_migration(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "missing-concept.db"
    init_database(str(memory_path))
    with sqlite3.connect(memory_path) as conn:
        conn.execute(
            "INSERT INTO notebook_entries (name, data, embedding) VALUES (?, ?, NULL)",
            ("n1", "missing embedding"),
        )

    result = migrate_embeddings(
        str(memory_path),
        str(concept_path),
        encoder_factory=FakeEncoder,
        progress=lambda _message: None,
    )

    assert result == {"rows_migrated": 1, "concept_db_present": False}
    with sqlite3.connect(memory_path) as conn:
        embedding = conn.execute(
            "SELECT embedding FROM notebook_entries WHERE name = 'n1'"
        ).fetchone()[0]
    assert len(embedding) == DEFAULT_SEMANTIC_DIM * 4


def test_missing_concept_database_is_not_created(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "missing" / "concept.db"
    init_database(str(memory_path))

    result = migrate_embeddings(
        str(memory_path),
        str(concept_path),
        encoder_factory=FakeEncoder,
        progress=lambda _message: None,
    )

    assert result == {"rows_migrated": 0, "concept_db_present": False}
    assert not concept_path.exists()


def test_missing_memory_database_exits_without_loading_encoder_or_creating_files(
    tmp_path,
):
    memory_path = tmp_path / "missing-memory.db"
    concept_path = tmp_path / "missing-concept.db"

    result = migrate_embeddings(
        str(memory_path),
        str(concept_path),
        encoder_factory=lambda: pytest.fail("encoder must not load"),
        progress=lambda _message: None,
    )

    assert result == {"rows_migrated": 0, "concept_db_present": False}
    assert not memory_path.exists()
    assert not concept_path.exists()


def test_pre_embedding_concept_schema_is_upgraded_only_by_migration(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "concept.db"
    init_database(str(memory_path))
    with sqlite3.connect(concept_path) as conn:
        conn.execute("CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT)")

    result = migrate_embeddings(
        str(memory_path),
        str(concept_path),
        encoder_factory=FakeEncoder,
        progress=lambda _message: None,
    )

    assert result == {"rows_migrated": 0, "concept_db_present": True}
    with sqlite3.connect(concept_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(entities)")}
    assert "name_embedding" in columns


def test_interrupted_run_commits_finished_database_and_resumes(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "concept.db"
    _seed_databases(memory_path, concept_path)

    with pytest.raises(RuntimeError, match="injected encoder failure"):
        migrate_embeddings(
            str(memory_path),
            str(concept_path),
            encoder_factory=lambda: FakeEncoder(fail_on="entity text"),
            progress=lambda _message: None,
        )

    state = inspect_embedding_state(str(memory_path), str(concept_path))
    assert state.incompatible == 1
    assert state.marker is None

    result = migrate_embeddings(
        str(memory_path),
        str(concept_path),
        encoder_factory=FakeEncoder,
        progress=lambda _message: None,
    )
    assert result["rows_migrated"] == 1
    assert inspect_embedding_state(str(memory_path), str(concept_path)).compatible


def test_preflight_dimension_mismatch_aborts_before_writes(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "concept.db"
    _seed_databases(memory_path, concept_path)

    with pytest.raises(RuntimeError, match="Configured embedding dimension"):
        migrate_embeddings(
            str(memory_path),
            str(concept_path),
            encoder_factory=lambda: FakeEncoder(dim=384),
            progress=lambda _message: None,
        )

    assert (
        inspect_embedding_state(str(memory_path), str(concept_path)).incompatible == 4
    )


def test_verification_failure_blocks_marker(tmp_path, monkeypatch):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "concept.db"
    _seed_databases(memory_path, concept_path)
    real_migrate_database = embedding_migration._migrate_database

    def skip_concept(path, tables, encoder, batch_size, progress):
        if path == concept_path:
            return 0
        return real_migrate_database(path, tables, encoder, batch_size, progress)

    monkeypatch.setattr(embedding_migration, "_migrate_database", skip_concept)

    with pytest.raises(RuntimeError, match="Verification failed"):
        migrate_embeddings(
            str(memory_path),
            str(concept_path),
            encoder_factory=FakeEncoder,
            progress=lambda _message: None,
        )
    with sqlite3.connect(memory_path) as conn:
        assert (
            conn.execute(
                "SELECT value FROM user_settings WHERE key = 'embedding_model'"
            ).fetchone()
            is None
        )


def test_concept_similarity_logs_mixed_dimension_skips(tmp_path, capsys):
    from marm_mcp_server.core.concept_db import ConceptDB

    db = ConceptDB(str(tmp_path / "concept.db"))
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO entities "
            "(name, type, session_name, project, name_embedding) "
            "VALUES ('old entity', 'concept', 's1', 'p1', ?)",
            (_vector(384),),
        )
        matches = db.find_similar_entities(
            conn,
            _vector(DEFAULT_SEMANTIC_DIM),
            "s1",
            "p1",
            0.8,
        )

    assert matches == []
    assert "--migrate-embeddings" in capsys.readouterr().err
