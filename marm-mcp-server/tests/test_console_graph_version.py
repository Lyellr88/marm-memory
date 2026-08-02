"""Tests for the graph change marker the Console Explorer polls.

Without this the Explorer reads the graph once and background indexing is
invisible until a reload, which would make the automation pointless from the
user's side.
"""

import sqlite3

import pytest

from marm_mcp_server.console import concept_store
from marm_mcp_server.core.concept_db import CONCEPT_SCHEMA_VERSION, ConceptDB


@pytest.fixture
def graph(tmp_path):
    db_path = tmp_path / "marm_index.db"
    concept_db = ConceptDB(str(db_path))
    yield concept_db, db_path
    concept_db.close()


def _add_entity(concept_db, name, memory_id="m1"):
    with concept_db.get_connection() as conn:
        return concept_db.get_or_create_entity(
            conn, name, "concept", "sess-a", None, memory_id, platform="cli"
        )


def test_version_is_stable_while_nothing_changes(graph):
    concept_db, db_path = graph
    _add_entity(concept_db, "auth module")

    first = concept_store.graph_version(db_path)
    second = concept_store.graph_version(db_path)

    assert first["schema_status"] == "current"
    assert first == second


def test_version_moves_when_an_entity_is_added(graph):
    concept_db, db_path = graph
    before = concept_store.graph_version(db_path)["version"]

    _add_entity(concept_db, "rate limiter")

    assert concept_store.graph_version(db_path)["version"] != before


def test_version_moves_when_a_relationship_is_added(graph):
    concept_db, db_path = graph
    first, _ = _add_entity(concept_db, "auth module")
    second, _ = _add_entity(concept_db, "rate limiter")
    before = concept_store.graph_version(db_path)["version"]

    with concept_db.get_connection() as conn:
        concept_db.store_relationship(
            conn, first, second, "uses", "m1", None, platform="cli"
        )

    assert concept_store.graph_version(db_path)["version"] != before


def test_version_moves_when_an_entity_is_removed(graph):
    """Counts as well as max ids, so a delete is not invisible."""
    concept_db, db_path = graph
    _add_entity(concept_db, "auth module")
    _add_entity(concept_db, "rate limiter")
    before = concept_store.graph_version(db_path)["version"]

    concept_db.cleanup_deleted_memory_provenance(["m1"])

    assert concept_store.graph_version(db_path)["version"] != before


def test_version_reports_a_graph_that_needs_rebuilding(graph):
    concept_db, db_path = graph
    with concept_db.get_connection() as conn:
        conn.execute(
            "UPDATE concept_schema_metadata SET value = '1' WHERE key = 'schema_version'"
        )

    result = concept_store.graph_version(db_path)

    assert result["schema_status"] == "rebuild_required"
    assert result["version"] == "rebuild_required"


def test_version_on_a_missing_database_is_not_an_error(tmp_path):
    result = concept_store.graph_version(tmp_path / "nothing.db")

    assert result["schema_status"] == "unavailable"


def test_console_reads_the_schema_version_from_the_writer(graph):
    """The Console used to restate the version as a literal. On the next bump
    it would have called every freshly rebuilt graph stale."""
    _concept_db, db_path = graph

    assert concept_store._CURRENT_CONCEPT_SCHEMA_VERSION == str(CONCEPT_SCHEMA_VERSION)
    with sqlite3.connect(db_path) as conn:
        stored = conn.execute(
            "SELECT value FROM concept_schema_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert stored == concept_store._CURRENT_CONCEPT_SCHEMA_VERSION
    assert concept_store.graph_version(db_path)["schema_status"] == "current"
