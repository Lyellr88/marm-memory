import asyncio
import sqlite3

import numpy as np

from marm_mcp_server.config.settings import DEFAULT_SEMANTIC_MODEL
from marm_mcp_server.core.memory_db import init_database
from marm_mcp_server.utils.embedding_state import (
    check_embedding_compatibility,
    inspect_embedding_state,
)


def _vector(dim: int) -> bytes:
    return np.ones(dim, dtype=np.float32).tobytes()


def test_fresh_state_seeds_marker_without_creating_concept_db(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "missing" / "marm_index.db"
    init_database(str(memory_path))
    warnings = []

    state = check_embedding_compatibility(
        memory_db_path=str(memory_path),
        concept_db_path=str(concept_path),
        warn=warnings.append,
    )

    assert state.compatible
    assert warnings == []
    assert not concept_path.exists()
    with sqlite3.connect(memory_path) as conn:
        marker = conn.execute(
            "SELECT value FROM user_settings WHERE key = 'embedding_model'"
        ).fetchone()[0]
    assert marker == DEFAULT_SEMANTIC_MODEL


def test_old_notebook_vector_requires_migration_when_memories_are_empty(tmp_path):
    memory_path = tmp_path / "memory.db"
    init_database(str(memory_path))
    with sqlite3.connect(memory_path) as conn:
        conn.execute(
            "INSERT INTO notebook_entries (name, data, embedding) VALUES (?, ?, ?)",
            ("notes", "old notebook vector", _vector(384)),
        )
    warnings = []

    state = check_embedding_compatibility(
        memory_db_path=str(memory_path),
        concept_db_path=str(tmp_path / "missing.db"),
        warn=warnings.append,
    )

    assert state.incompatible == 1
    assert len(warnings) == 1
    assert "--migrate-embeddings" in warnings[0]
    with sqlite3.connect(memory_path) as conn:
        assert (
            conn.execute(
                "SELECT value FROM user_settings WHERE key = 'embedding_model'"
            ).fetchone()
            is None
        )


def test_restored_old_concept_vectors_override_current_marker(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "concept.db"
    init_database(str(memory_path))
    with sqlite3.connect(memory_path) as conn:
        conn.execute(
            "INSERT INTO user_settings (key, value) VALUES ('embedding_model', ?)",
            (DEFAULT_SEMANTIC_MODEL,),
        )
    with sqlite3.connect(concept_path) as conn:
        conn.execute(
            "CREATE TABLE entities (id INTEGER PRIMARY KEY, name_embedding BLOB)"
        )
        conn.execute(
            "INSERT INTO entities (name_embedding) VALUES (?)", (_vector(384),)
        )

    state = inspect_embedding_state(str(memory_path), str(concept_path))

    assert state.marker == DEFAULT_SEMANTIC_MODEL
    assert state.incompatible == 1
    assert not state.compatible


def test_pre_embedding_concept_schema_is_inspected_without_ddl(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "concept.db"
    init_database(str(memory_path))
    with sqlite3.connect(concept_path) as conn:
        conn.execute("CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT)")

    state = inspect_embedding_state(str(memory_path), str(concept_path))

    assert state.compatible
    with sqlite3.connect(concept_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(entities)")}
    assert "name_embedding" not in columns


def test_corrupt_concept_database_warns_without_raising_or_repairing(tmp_path):
    memory_path = tmp_path / "memory.db"
    concept_path = tmp_path / "concept.db"
    init_database(str(memory_path))
    concept_path.write_bytes(b"not a sqlite database")
    warnings = []

    state = check_embedding_compatibility(
        memory_db_path=str(memory_path),
        concept_db_path=str(concept_path),
        warn=warnings.append,
    )

    assert not state.compatible
    assert len(state.errors) == 1
    assert len(warnings) == 1
    assert "core memory remains available" in warnings[0]
    assert concept_path.read_bytes() == b"not a sqlite database"


def test_http_lifespan_runs_shared_compatibility_check(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    server = load_isolated_server(monkeypatch, tmp_path)
    memory_path = tmp_path / "marm_memory.db"
    with sqlite3.connect(memory_path) as conn:
        conn.execute(
            "INSERT INTO notebook_entries (name, data, embedding) VALUES (?, ?, ?)",
            ("old", "old vector", _vector(384)),
        )
    warnings = []
    real_check = check_embedding_compatibility
    monkeypatch.setattr(
        server,
        "check_embedding_compatibility",
        lambda **kwargs: real_check(
            memory_db_path=str(memory_path),
            concept_db_path=str(tmp_path / "missing-concept.db"),
            warn=warnings.append,
        ),
    )

    async def run_lifespan():
        async with server.lifespan(server.app):
            pass

    asyncio.run(run_lifespan())
    assert len(warnings) == 1
    assert "--migrate-embeddings" in warnings[0]


def test_stdio_main_runs_shared_compatibility_check(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    load_isolated_server(monkeypatch, tmp_path)
    import marm_mcp_server.server_stdio as stdio

    memory_path = stdio.memory.db_path
    with sqlite3.connect(memory_path) as conn:
        conn.execute(
            "INSERT INTO notebook_entries (name, data, embedding) VALUES (?, ?, ?)",
            ("stdio-old", "old vector", _vector(384)),
        )
    warnings = []
    real_check = check_embedding_compatibility
    monkeypatch.setattr(
        stdio,
        "check_embedding_compatibility",
        lambda **kwargs: real_check(
            memory_db_path=memory_path,
            concept_db_path=str(tmp_path / "missing-concept.db"),
            warn=warnings.append,
        ),
    )
    monkeypatch.setattr(stdio.memory, "restore_active_session", lambda: None)
    monkeypatch.setattr(stdio.mcp, "run", lambda: None)
    monkeypatch.setattr(stdio, "_stop_graph_supervisor_safely", lambda: None)

    stdio.main()

    assert len(warnings) == 1
    assert "--migrate-embeddings" in warnings[0]
