from array import array

import pytest

from marm_mcp_server.console import concept_store
from marm_mcp_server.core.concept_db import ConceptDB


@pytest.fixture
def graph(tmp_path):
    db_path = tmp_path / "marm_index.db"
    concept_db = ConceptDB(str(db_path))
    yield concept_db, db_path
    concept_db.close()


def _vec(*values):
    return array("f", values).tobytes()


def _add(concept_db, name, vector):
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn, name, "concept", "s", "p", "m1", name_embedding=vector
        )


def test_versions_are_not_offered_as_duplicates(graph):
    """An embedding scores `v2.1.0` against `v2.0.0` at 0.99; they are two
    releases, and the panel offered every such pair for review."""
    concept_db, db_path = graph
    _add(concept_db, "v2.1.0", _vec(1.0, 0.0, 0.0))
    _add(concept_db, "v2.0.0", _vec(0.999, 0.01, 0.0))
    _add(concept_db, "fix", _vec(0.0, 1.0, 0.0))
    _add(concept_db, "the fix", _vec(0.0, 0.999, 0.01))

    report = concept_store.duplicate_report(db_path)

    names = [
        {item["entity_a"]["name"], item["entity_b"]["name"]} for item in report["items"]
    ]
    assert names == [{"fix", "the fix"}]
    assert report["total"] == 1
