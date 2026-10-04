import hashlib

import pytest
from fastapi.testclient import TestClient

from marm_mcp_server.console import concept_store
from marm_mcp_server.core.concept_db import ConceptDB

LEGACY = ["**apply**", "`claim()`", "- bullet item", "| Column | Value", "MIT license("]


@pytest.fixture
def graph(tmp_path):
    db_path = tmp_path / "marm_index.db"
    concept_db = ConceptDB(str(db_path))
    yield concept_db, db_path
    concept_db.close()


def _add(concept_db, *names):
    with concept_db.get_connection() as conn:
        for name in names:
            concept_db.get_or_create_entity(
                conn, name, "concept", "sess-a", None, "m1", platform="cli"
            )


def test_names_the_extractor_would_clean_are_counted(graph):
    concept_db, db_path = graph
    _add(concept_db, *LEGACY, "auth module")

    report = concept_store.legacy_names(db_path)

    assert report["count"] == len(LEGACY)
    assert report["checked"] == len(LEGACY) + 1
    assert set(report["sample"]) <= set(LEGACY)
    assert "auth module" not in report["sample"]


def test_the_sample_is_bounded(graph):
    concept_db, db_path = graph
    _add(concept_db, *(f"**name {i}**" for i in range(20)))

    report = concept_store.legacy_names(db_path, sample_limit=5)

    assert report["count"] == 20
    assert len(report["sample"]) == 5


def test_a_clean_graph_reports_nothing(graph):
    concept_db, db_path = graph
    _add(concept_db, "auth module", "MARM (Memory)", "__init__", ".env", "-1 offset")

    assert concept_store.legacy_names(db_path) == {
        "count": 0,
        "checked": 5,
        "sample": [],
    }


def test_a_missing_graph_reports_nothing(tmp_path):
    assert concept_store.legacy_names(tmp_path / "absent.db") == {
        "count": 0,
        "checked": 0,
        "sample": [],
    }


def test_the_check_writes_nothing(graph):
    concept_db, db_path = graph
    _add(concept_db, *LEGACY)
    concept_db.close()
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    concept_store.legacy_names(db_path)

    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_the_endpoint_returns_the_report(graph, monkeypatch):
    from marm_mcp_server.console.app import app
    from marm_mcp_server.console.endpoints import concepts

    concept_db, db_path = graph
    _add(concept_db, "**apply**", "auth module")
    monkeypatch.setattr(concepts, "get_concept_db_path", lambda: db_path)

    with TestClient(app) as client:
        response = client.get("/api/concepts/legacy-names")

    assert response.status_code == 200
    assert response.json() == {"count": 1, "checked": 2, "sample": ["**apply**"]}


def test_the_check_cannot_write(graph, monkeypatch):
    import sqlite3

    concept_db, db_path = graph
    _add(concept_db, "**apply**")
    real_connect = sqlite3.connect
    refused = []

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.execute("BEGIN")
        try:
            connection.execute("CREATE TABLE write_probe (x)")
        except sqlite3.OperationalError:
            refused.append(True)
        else:
            refused.append(False)
        connection.rollback()
        return connection

    monkeypatch.setattr(concept_store.sqlite3, "connect", connect)
    concept_store.legacy_names(db_path)

    assert refused == [True]
