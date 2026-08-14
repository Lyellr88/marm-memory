import asyncio
import sqlite3

import pytest
from conftest import load_isolated_server, local_client

from marm_mcp_server.core import concept_db as concept_db_module
from marm_mcp_server.core.concept_db import (
    ConceptDB,
    backup_and_reset_concept_database,
    inspect_concept_schema,
    mark_schema_current,
)
from marm_mcp_server.core.response_limiter import MCPResponseLimiter
from marm_mcp_server.services import recall as recall_service
from marm_mcp_server.services.graph_context import (
    attach_graph_context,
    get_graph_context,
)


def _seed_graph(db_path):
    graph = ConceptDB(str(db_path))
    with graph.get_connection() as conn:
        queue_id, _ = graph.get_or_create_entity(
            conn,
            "write queue",
            "component",
            "sess-a",
            "marm-memory",
            "mem-1",
            platform="claude-code",
        )
        worker_id, _ = graph.get_or_create_entity(
            conn,
            "embedding worker",
            "component",
            "sess-a",
            "marm-memory",
            "mem-1",
            platform="claude-code",
        )
        graph.store_relationship(
            conn,
            queue_id,
            worker_id,
            "feeds",
            "mem-1",
            "marm-memory",
            platform="claude-code",
        )
        cursor_id, _ = graph.get_or_create_entity(
            conn,
            "write queue",
            "component",
            "sess-a",
            "marm-memory",
            "mem-2",
            platform="cursor",
        )
        other_id, _ = graph.get_or_create_entity(
            conn,
            "cursor worker",
            "component",
            "sess-a",
            "marm-memory",
            "mem-2",
            platform="cursor",
        )
        graph.store_relationship(
            conn,
            cursor_id,
            other_id,
            "feeds",
            "mem-2",
            "marm-memory",
            platform="cursor",
        )
    graph.close()


def test_graph_context_uses_memory_provenance_and_platform_scope(monkeypatch, tmp_path):
    db_path = tmp_path / "marm_index.db"
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(db_path))
    _seed_graph(db_path)

    context = get_graph_context(
        query="how are pending writes processed?",
        memory_ids=["mem-1"],
        session_name="sess-a",
        project="marm-memory",
        platform="claude-code",
        depth=2,
    )

    assert context["status"] == "available"
    assert {entity["name"] for entity in context["entities"]} == {
        "write queue",
        "embedding worker",
    }
    assert context["seed_sources"]["memory_results"] == 2
    assert "cursor worker" not in {item["name"] for item in context["related_entities"]}


def test_entity_identity_includes_platform(tmp_path):
    graph = ConceptDB(str(tmp_path / "marm_index.db"))
    with graph.get_connection() as conn:
        claude_id, _ = graph.get_or_create_entity(
            conn, "shared", "concept", "sess", "project", "m1", platform="claude"
        )
        cursor_id, _ = graph.get_or_create_entity(
            conn, "shared", "concept", "sess", "project", "m2", platform="cursor"
        )
    graph.close()

    assert claude_id != cursor_id


def test_graph_context_direct_name_match_can_upgrade_no_results(monkeypatch, tmp_path):
    db_path = tmp_path / "marm_index.db"
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(db_path))
    _seed_graph(db_path)

    context = get_graph_context(
        query="write queue",
        session_name="sess-a",
        project="marm-memory",
        platform="claude-code",
    )
    response = attach_graph_context(
        {"status": "no_results", "results": [], "query": "write queue"}, context
    )

    assert response["status"] == "success"
    assert response["results"] == []
    assert response["graph_context"]["seed_sources"]["query_match"] == 1


def test_missing_graph_is_not_created_by_recall(monkeypatch, tmp_path):
    db_path = tmp_path / "missing" / "marm_index.db"
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(db_path))

    context = get_graph_context(query="anything", session_name="sess-a")

    assert context["status"] == "unavailable"
    assert not db_path.exists()


def test_corrupt_graph_fails_open_without_changing_primary_results(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "marm_index.db"
    db_path.write_bytes(b"not a sqlite database")
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(db_path))
    primary = {"status": "success", "results": [{"id": "m1", "content": "kept"}]}

    context = get_graph_context(query="anything", memory_ids=["m1"])
    result = attach_graph_context(primary, context)

    assert context["status"] == "unavailable"
    assert result["status"] == "success"
    assert result["results"] == primary["results"]


def test_platformless_graph_requires_explicit_reset(monkeypatch, tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE entities (
                id INTEGER PRIMARY KEY, name TEXT, type TEXT,
                session_name TEXT, project TEXT, source_memory_ids TEXT
            );
            CREATE TABLE relationships (
                id INTEGER PRIMARY KEY, source_id INTEGER, target_id INTEGER,
                predicate TEXT, memory_id TEXT, project TEXT
            );
            INSERT INTO entities VALUES (1, 'legacy', 'concept', 'sess-a', NULL, '["m1"]');
            """)
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(db_path))

    assert inspect_concept_schema(str(db_path)) == "rebuild_required"
    assert get_graph_context(query="legacy")["status"] == "rebuild_required"

    backup = backup_and_reset_concept_database(str(db_path))

    assert backup
    # Still rebuild_required: the reset emptied the graph but nothing has been
    # extracted into it yet. Marking it current here is what would let a
    # rebuild that dies partway pass for a finished one.
    assert inspect_concept_schema(str(db_path)) == "rebuild_required"
    mark_schema_current(str(db_path))
    assert inspect_concept_schema(str(db_path)) == "current"
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT name FROM entities").fetchone()[0] == "legacy"


def test_a_reset_never_writes_the_version_even_briefly(tmp_path):
    """Writing the marker and deleting it again leaves a window where a crash,
    or another process reading the schema state, sees an empty graph reported
    as current. The reset must never write it at all."""
    db_path = tmp_path / "legacy.db"
    graph = ConceptDB(str(db_path))
    with graph.get_connection() as conn:
        graph.get_or_create_entity(
            conn, "old", "concept", "sess-a", None, "m1", platform="cli"
        )
    graph.close()

    seen = []
    real_init = concept_db_module.init_concept_database

    def watching_init(path, mark_current=True):
        real_init(path, mark_current=mark_current)
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT value FROM concept_schema_metadata WHERE key = 'schema_version'"
            ).fetchone()
        seen.append(row)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(concept_db_module, "init_concept_database", watching_init)
        backup_and_reset_concept_database(str(db_path))

    assert seen == [None], f"the reset stamped a version mid-flight: {seen}"
    assert inspect_concept_schema(str(db_path)) == "rebuild_required"


def test_constructing_conceptdb_does_not_restamp_an_older_graph(tmp_path):
    """init_concept_database runs on every ConceptDB(...) construction. If it
    writes the current schema version unconditionally, one construction marks
    a graph built under an older rule as current and its rebuild never
    fires."""
    db_path = tmp_path / "older.db"
    graph = ConceptDB(str(db_path))
    with graph.get_connection() as conn:
        graph.get_or_create_entity(
            conn, "stale entity", "concept", "sess-a", None, "m1", platform="cli"
        )
        conn.execute(
            "UPDATE concept_schema_metadata SET value = '1' WHERE key = 'schema_version'"
        )
    graph.close()

    assert inspect_concept_schema(str(db_path)) == "rebuild_required"

    ConceptDB(str(db_path)).close()

    with sqlite3.connect(db_path) as conn:
        version = conn.execute(
            "SELECT value FROM concept_schema_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert version == "1"
    assert inspect_concept_schema(str(db_path)) == "rebuild_required"


def test_console_delete_cleanup_leaves_an_older_graph_needing_rebuild(
    monkeypatch, tmp_path
):
    """The real path that constructs a ConceptDB outside a build: deleting a
    memory in the Console runs provenance cleanup, which must not double as a
    schema blessing."""
    db_path = tmp_path / "older.db"
    graph = ConceptDB(str(db_path))
    with graph.get_connection() as conn:
        graph.get_or_create_entity(
            conn, "stale entity", "concept", "sess-a", None, "m1", platform="cli"
        )
        conn.execute(
            "UPDATE concept_schema_metadata SET value = '1' WHERE key = 'schema_version'"
        )
    graph.close()
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(db_path))

    from marm_mcp_server.endpoints import memory as memory_endpoints

    result = memory_endpoints._cleanup_deleted_concepts(["m1"])

    # Not just "did not fail": a missing concept database returns
    # status="skipped", which would satisfy that and prove nothing about
    # whether construction restamped the version.
    assert result["status"] == "success"
    assert result["entities_deleted"] == 1
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
    assert inspect_concept_schema(str(db_path)) == "rebuild_required"


def test_targeted_build_cannot_reset_platformless_graph(monkeypatch, tmp_path):
    from marm_mcp_server.core.models import ConceptBuildRequest
    from marm_mcp_server.endpoints import concepts

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, type TEXT);
            CREATE TABLE relationships (
                id INTEGER PRIMARY KEY, source_id INTEGER, target_id INTEGER,
                predicate TEXT
            );
            """)
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(db_path))
    if concepts._concept_db is not None:
        concepts._concept_db.close()
    concepts._concept_db = None

    with pytest.raises(ValueError, match="rebuild_required"):
        concepts._prepare_build_schema(ConceptBuildRequest(session_name="sess-a"))

    assert inspect_concept_schema(str(db_path)) == "rebuild_required"
    assert concepts._prepare_build_schema(ConceptBuildRequest(search_all=True)) is True
    # Preparing the schema resets the graph; it does not declare it rebuilt.
    # The version is stamped by the build that follows, so an interrupted
    # rebuild is still asked for on the next start.
    assert inspect_concept_schema(str(db_path)) == "rebuild_required"


def test_graph_context_is_reduced_before_primary_results(monkeypatch):
    monkeypatch.setattr(MCPResponseLimiter, "CONTENT_LIMIT", 700)
    response = {
        "status": "success",
        "results": [{"id": "m1", "content": "primary result"}],
    }
    context = {
        "status": "available",
        "entities": [{"name": "x" * 100, "type": "concept"}] * 10,
        "related_entities": [{"name": "y" * 100, "predicate": "uses"}] * 10,
        "linked_code": [{"qualified_name": "z" * 100}] * 10,
        "seed_sources": {"memory_results": 1, "query_match": 0},
        "truncated": False,
    }

    result = attach_graph_context(response, context)

    assert result["results"] == response["results"]
    assert result["graph_context"]["truncated"] is True
    assert MCPResponseLimiter.estimate_response_size(result) <= 700


def test_http_graph_only_recall_keeps_empty_primary_results(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    from marm_mcp_server.endpoints import memory as memory_endpoint

    monkeypatch.setattr(
        memory_endpoint,
        "get_graph_context",
        lambda **kwargs: {
            "status": "available",
            "entities": [{"name": "graph-only", "type": "concept"}],
            "related_entities": [],
            "linked_code": [],
            "seed_sources": {"memory_results": 0, "query_match": 1},
            "truncated": False,
        },
    )
    client = local_client(server.app)

    response = client.post(
        "/marm_smart_recall",
        json={"query": "graph-only", "session_name": "sess-a"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["results"] == []
    assert response.json()["graph_context"]["status"] == "available"


def test_stdio_service_returns_same_graph_only_contract(monkeypatch):
    class EmptyMemory:
        async def recall_similar(self, *args, include_scan_metadata=False, **kwargs):
            if include_scan_metadata:
                return [], {"scan": "none"}
            return []

    monkeypatch.setattr(recall_service, "memory", EmptyMemory())
    monkeypatch.setattr(
        recall_service,
        "get_graph_context",
        lambda **kwargs: {
            "status": "available",
            "entities": [{"name": "graph-only", "type": "concept"}],
            "related_entities": [],
            "linked_code": [],
            "seed_sources": {"memory_results": 0, "query_match": 1},
            "truncated": False,
        },
    )

    result = asyncio.run(
        recall_service.smart_recall("graph-only", search_all=True, limit=5)
    )

    assert result["status"] == "success"
    assert result["results"] == []
    assert result["graph_context"]["status"] == "available"
