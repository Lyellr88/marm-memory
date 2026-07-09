"""Real-SQLite tests for core/concept_db.py -- own file, own pool, schema
behavior. No mocks: every assertion reads back actual rows written through
ConceptDB's real connection pool.
"""

import json

import numpy as np
import pytest

from marm_mcp_server.core.concept_db import ConceptDB


@pytest.fixture
def concept_db(tmp_path):
    return ConceptDB(db_path=str(tmp_path / "marm_index.db"))


def test_own_file_created_separately_from_memory_db(tmp_path):
    db_path = tmp_path / "marm_index.db"
    assert not db_path.exists()
    ConceptDB(db_path=str(db_path))
    assert db_path.exists()


def test_get_or_create_entity_dedups_same_name_session_project(concept_db):
    with concept_db.get_connection() as conn:
        id_first, created_first = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-1", "proj-a", "mem-1"
        )
        id_second, created_second = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-1", "proj-a", "mem-2"
        )

    assert id_first == id_second
    assert created_first is True
    assert created_second is False

    with concept_db.get_connection() as conn:
        row = conn.execute(
            "SELECT source_memory_ids FROM entities WHERE id = ?", (id_first,)
        ).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]

    assert count == 1
    assert json.loads(row[0]) == ["mem-1", "mem-2"]


def test_same_name_session_different_project_stored_as_two_rows(concept_db):
    with concept_db.get_connection() as conn:
        id_a, _ = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-1", "proj-a", "mem-1"
        )
        id_b, _ = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-1", "proj-b", "mem-2"
        )

    assert id_a != id_b
    with concept_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    assert count == 2


def test_store_relationship_creates_row_between_two_entities(concept_db):
    with concept_db.get_connection() as conn:
        id_a, _ = concept_db.get_or_create_entity(
            conn, "rate limiter", "pattern", "sess-1", None, "mem-1"
        )
        id_b, _ = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-1", None, "mem-1"
        )
        concept_db.store_relationship(conn, id_a, id_b, "co_occurs_with", "mem-1", None)

    with concept_db.get_connection() as conn:
        rows = conn.execute(
            "SELECT source_id, target_id, predicate FROM relationships"
        ).fetchall()

    assert rows == [(id_a, id_b, "co_occurs_with")]


def test_store_relationship_skips_self_loop(concept_db):
    with concept_db.get_connection() as conn:
        entity_id, _ = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-1", None, "mem-1"
        )
        concept_db.store_relationship(
            conn, entity_id, entity_id, "co_occurs_with", "mem-1", None
        )

    with concept_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    assert count == 0


def test_store_code_link_persists_label_and_file_path(concept_db):
    with concept_db.get_connection() as conn:
        entity_id, _ = concept_db.get_or_create_entity(
            conn, "CbmClient", "concept", "sess-1", "proj-a", "mem-1"
        )
        concept_db.store_code_link(
            conn,
            entity_id,
            "marm_graph.core.cbm_client.CbmClient",
            "proj-a",
            confidence=1.0,
            label="class",
            file_path="marm_graph/core/cbm_client.py",
        )

    with concept_db.get_connection() as conn:
        row = conn.execute(
            "SELECT graph_qualified_name, label, file_path FROM entity_code_links "
            "WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()

    assert row == (
        "marm_graph.core.cbm_client.CbmClient",
        "class",
        "marm_graph/core/cbm_client.py",
    )


def test_relationship_fk_constraint_rejects_missing_entity(concept_db):
    with pytest.raises(Exception):
        with concept_db.get_connection() as conn:
            concept_db.store_relationship(
                conn, 999, 998, "co_occurs_with", "mem-1", None
            )


def test_concept_pool_is_independent_instance(concept_db, tmp_path):
    """The concept DB's connection pool must never be the same pool instance
    used by marm-mcp's own memory DB -- this is the one hard boundary that
    makes running in-process safe."""
    from marm_mcp_server.core.memory import memory as marm_memory

    assert concept_db.connection_pool is not marm_memory.connection_pool
    assert concept_db.db_path != marm_memory.connection_pool.db_path


# ── Goal 3: entity resolution via embedding similarity ──────────────


def _vec(*values) -> bytes:
    """3-dim float32 vector -> bytes, matching _embedding_to_bytes's layout."""
    return np.asarray(values, dtype=np.float32).tobytes()


def test_get_or_create_entity_stores_embedding_only_on_insert(concept_db):
    with concept_db.get_connection() as conn:
        entity_id, created = concept_db.get_or_create_entity(
            conn,
            "auth module",
            "concept",
            "sess-1",
            None,
            "mem-1",
            name_embedding=_vec(1.0, 0.0, 0.0),
        )
        assert created is True

        # Re-mention with a different embedding -- must not overwrite.
        same_id, created_again = concept_db.get_or_create_entity(
            conn,
            "auth module",
            "concept",
            "sess-1",
            None,
            "mem-2",
            name_embedding=_vec(0.0, 1.0, 0.0),
        )
        assert same_id == entity_id
        assert created_again is False

    with concept_db.get_connection() as conn:
        row = conn.execute(
            "SELECT name_embedding FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
    assert np.frombuffer(row[0], dtype=np.float32).tolist() == [1.0, 0.0, 0.0]


def test_find_similar_entities_returns_candidates_above_threshold(concept_db):
    with concept_db.get_connection() as conn:
        existing_id, _ = concept_db.get_or_create_entity(
            conn,
            "auth module",
            "concept",
            "sess-1",
            None,
            "mem-1",
            name_embedding=_vec(1.0, 0.0, 0.0),
        )
        candidates = concept_db.find_similar_entities(
            conn,
            _vec(0.99, 0.01, 0.0),  # near-identical direction
            "sess-1",
            None,
            threshold=0.9,
        )

    assert len(candidates) == 1
    assert candidates[0]["entity_id"] == existing_id
    assert candidates[0]["name"] == "auth module"
    assert candidates[0]["similarity"] >= 0.9


def test_find_similar_entities_excludes_below_threshold(concept_db):
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn,
            "auth module",
            "concept",
            "sess-1",
            None,
            "mem-1",
            name_embedding=_vec(1.0, 0.0, 0.0),
        )
        candidates = concept_db.find_similar_entities(
            conn,
            _vec(0.0, 1.0, 0.0),  # orthogonal -- similarity 0.0
            "sess-1",
            None,
            threshold=0.9,
        )

    assert candidates == []


def test_find_similar_entities_scoped_to_session_and_project(concept_db):
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn,
            "auth module",
            "concept",
            "sess-1",
            "proj-a",
            "mem-1",
            name_embedding=_vec(1.0, 0.0, 0.0),
        )
        # Same near-identical embedding, but a different session -- must not
        # be treated as a cross-session duplicate candidate.
        candidates = concept_db.find_similar_entities(
            conn,
            _vec(0.99, 0.01, 0.0),
            "sess-2",
            "proj-a",
            threshold=0.9,
        )

    assert candidates == []


def test_find_similar_entities_excludes_self_via_exclude_id(concept_db):
    with concept_db.get_connection() as conn:
        entity_id, _ = concept_db.get_or_create_entity(
            conn,
            "auth module",
            "concept",
            "sess-1",
            None,
            "mem-1",
            name_embedding=_vec(1.0, 0.0, 0.0),
        )
        candidates = concept_db.find_similar_entities(
            conn,
            _vec(1.0, 0.0, 0.0),  # identical vector to itself
            "sess-1",
            None,
            threshold=0.9,
            exclude_id=entity_id,
        )

    assert candidates == []
