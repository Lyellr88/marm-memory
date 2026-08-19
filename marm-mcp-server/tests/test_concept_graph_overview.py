"""Tests for the Console's safe and explicitly requested concept atlases."""

from fastapi.testclient import TestClient

from marm_mcp_server.console import concept_graph_overview
from marm_mcp_server.console.app import app
from marm_mcp_server.core.concept_db import ConceptDB


def _seed_entities(db: ConceptDB, count: int) -> None:
    with db.get_connection() as connection:
        connection.executemany(
            "INSERT INTO entities (name, type, source_memory_ids) VALUES (?, 'concept', '[]')",
            [(f"entity-{index}",) for index in range(count)],
        )


def test_full_atlas_is_only_returned_when_explicitly_requested(tmp_path):
    db_path = tmp_path / "marm_index.db"
    database = ConceptDB(str(db_path))
    _seed_entities(database, 751)

    sampled = concept_graph_overview.graph_overview(db_path)
    full = concept_graph_overview.graph_overview(db_path, force_full=True)

    assert sampled["mode"] == "sampled"
    assert sampled["rendered"]["nodes"] == 600
    assert full["mode"] == "full"
    assert full["rendered"] == {"nodes": 751, "edges": 0}
    assert full["truncated"] is False


def test_graph_endpoint_forwards_the_explicit_full_request(monkeypatch):
    from marm_mcp_server.console.endpoints import concepts

    seen: dict[str, bool] = {}

    def fake_graph_overview(_path, *, force_full=False):
        seen["force_full"] = force_full
        return {"mode": "full", "nodes": [], "edges": []}

    monkeypatch.setattr(concepts, "graph_overview", fake_graph_overview)
    with TestClient(app) as client:
        response = client.get("/api/concepts/graph?full=true")

    assert response.status_code == 200
    assert seen == {"force_full": True}
