"""Bounded-traversal and overview tests for concept_store against a real
SQLite database using the production schema from marm-mcp-server."""

import sqlite3
from array import array
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re


from marm_mcp_server.console import (
    concept_graph_overview,
    concept_neighborhood,
    concept_store,
)
from marm_mcp_server.console.endpoints import concepts as concepts_endpoint


def test_console_schema_version_tracks_mcp_source() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "marm-mcp-server"
        / "marm_mcp_server"
        / "core"
        / "concept_db.py"
    ).read_text(encoding="utf-8")
    match = re.search(r"CONCEPT_SCHEMA_VERSION = (\d+)", source)

    assert match is not None
    assert concept_store._CURRENT_CONCEPT_SCHEMA_VERSION == match.group(1)


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "marm_index.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            session_name TEXT,
            project TEXT,
            platform TEXT,
            source_memory_ids TEXT DEFAULT '[]',
            name_embedding BLOB,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, session_name, project, platform)
        );
        CREATE TABLE relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            predicate TEXT NOT NULL,
            memory_id TEXT,
            project TEXT,
            platform TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(source_id) REFERENCES entities(id),
            FOREIGN KEY(target_id) REFERENCES entities(id)
        );
        CREATE TABLE entity_code_links (
            entity_id INTEGER NOT NULL,
            graph_qualified_name TEXT NOT NULL,
            project TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            label TEXT,
            file_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(entity_id) REFERENCES entities(id)
        );
        CREATE TABLE concept_build_runs (
            id TEXT PRIMARY KEY,
            scope_type TEXT NOT NULL,
            scope_value TEXT,
            status TEXT NOT NULL,
            memories_processed INTEGER NOT NULL DEFAULT 0,
            entities_extracted INTEGER NOT NULL DEFAULT 0,
            relationships_created INTEGER NOT NULL DEFAULT 0,
            code_links_created INTEGER NOT NULL DEFAULT 0,
            duplicate_candidates INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            error_code TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE TABLE concept_schema_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT INTO concept_schema_metadata (key, value)
        VALUES ('schema_version', '2');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def add_entity(db_path: Path, name: str, type_: str = "concept") -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.execute("INSERT INTO entities (name, type) VALUES (?, ?)", (name, type_))
    conn.commit()
    conn.close()
    return cur.lastrowid


def add_edge(db_path: Path, source: int, target: int, predicate: str) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO relationships (source_id, target_id, predicate) VALUES (?, ?, ?)",
        (source, target, predicate),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def set_embedding(db_path: Path, entity_id: int, *values: float) -> None:
    vector = array("f", values)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE entities SET name_embedding = ? WHERE id = ?",
        (vector.tobytes(), entity_id),
    )
    conn.commit()
    conn.close()


def test_summary_reports_rebuild_for_existing_database_without_graph_schema(tmp_path):
    db_path = tmp_path / "marm_index.db"
    sqlite3.connect(db_path).close()

    result = concept_store.summary(db_path)

    assert result["schema_status"] == "rebuild_required"
    assert result["entities"] == 0
    assert result["relationships"] == 0


def test_neighborhood_enforces_200_node_limit(tmp_path):
    db = make_db(tmp_path)
    hub = add_entity(db, "hub")
    for i in range(250):
        spoke = add_entity(db, f"spoke-{i}")
        add_edge(db, hub, spoke, "uses")

    result = concept_neighborhood.neighborhood(db, hub, depth=1)

    assert result is not None
    assert len(result["nodes"]) <= 200
    assert hub in {n["id"] for n in result["nodes"]}
    assert result["truncated"] is True
    # Every returned edge must connect nodes that are actually in the response
    node_ids = {n["id"] for n in result["nodes"]}
    for edge in result["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


def test_neighborhood_truncation_prefers_typed_edges_over_co_occurrence(tmp_path):
    db = make_db(tmp_path)
    hub = add_entity(db, "hub")
    # co_occurs_with edges get the LOWER relationship ids on purpose: only the
    # predicate ranking, not insertion order, can keep the typed edges alive.
    co_spokes = [add_entity(db, f"co-{i}") for i in range(150)]
    for spoke in co_spokes:
        add_edge(db, hub, spoke, "co_occurs_with")
    typed_spokes = [add_entity(db, f"typed-{i}") for i in range(150)]
    typed_edge_ids = [add_edge(db, hub, s, "uses") for s in typed_spokes]

    result = concept_neighborhood.neighborhood(db, hub, depth=1)

    returned_edge_ids = {e["id"] for e in result["edges"]}
    assert set(typed_edge_ids) <= returned_edge_ids, (
        "node-cap truncation dropped typed edges while co_occurs_with survived"
    )
    assert result["truncated"] is True


def test_neighborhood_depth_is_bounded_traversal(tmp_path):
    db = make_db(tmp_path)
    a = add_entity(db, "a")
    b = add_entity(db, "b")
    c = add_entity(db, "c")
    d = add_entity(db, "d")
    add_edge(db, a, b, "uses")
    add_edge(db, b, c, "uses")
    add_edge(db, c, d, "uses")

    depth1 = concept_neighborhood.neighborhood(db, a, depth=1)
    depth2 = concept_neighborhood.neighborhood(db, a, depth=2)
    depth3 = concept_neighborhood.neighborhood(db, a, depth=3)

    assert {n["id"] for n in depth1["nodes"]} == {a, b}
    assert {n["id"] for n in depth2["nodes"]} == {a, b, c}
    assert {n["id"] for n in depth3["nodes"]} == {a, b, c, d}
    # depth is clamped to [1, 3]
    clamped = concept_neighborhood.neighborhood(db, a, depth=99)
    assert {n["id"] for n in clamped["nodes"]} == {a, b, c, d}


def test_neighborhood_hidden_neighbor_count_reflects_real_degree(tmp_path):
    db = make_db(tmp_path)
    a = add_entity(db, "a")
    b = add_entity(db, "b")
    add_edge(db, a, b, "uses")
    # b has 5 more neighbors that a depth-1 query from a will not include
    for i in range(5):
        other = add_entity(db, f"other-{i}")
        add_edge(db, b, other, "uses")

    result = concept_neighborhood.neighborhood(db, a, depth=1)

    by_id = {n["id"]: n for n in result["nodes"]}
    assert by_id[b]["degree"] == 6
    assert by_id[b]["hidden_neighbor_count"] == 5
    assert by_id[a]["hidden_neighbor_count"] == 0


def test_graph_overview_returns_complete_graph_under_budget(tmp_path):
    db = make_db(tmp_path)
    hub = add_entity(db, "hub")
    spokes = [add_entity(db, f"spoke-{i}") for i in range(20)]
    for spoke in spokes:
        add_edge(db, hub, spoke, "uses")
    add_entity(db, "isolated")

    result = concept_graph_overview.graph_overview(db)

    node_ids = {n["id"] for n in result["nodes"]}
    assert result["mode"] == "full"
    assert len(result["nodes"]) == 22
    assert hub in node_ids
    assert "isolated" in {n["name"] for n in result["nodes"]}
    by_id = {n["id"]: n for n in result["nodes"]}
    assert by_id[hub]["hidden_neighbor_count"] == 0
    assert result["total"] == {"nodes": 22, "edges": 20}
    assert result["rendered"] == {"nodes": 22, "edges": 20}
    for edge in result["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


def test_graph_overview_is_deterministic_across_calls(tmp_path):
    db = make_db(tmp_path)
    entities = [add_entity(db, f"e-{i}") for i in range(30)]
    for i in range(29):
        predicate = "co_occurs_with" if i % 2 else "uses"
        add_edge(db, entities[i], entities[i + 1], predicate)

    first = concept_graph_overview.graph_overview(db)
    second = concept_graph_overview.graph_overview(db)

    assert [e["id"] for e in first["edges"]] == [e["id"] for e in second["edges"]]
    assert [n["id"] for n in first["nodes"]] == [n["id"] for n in second["nodes"]]


def test_graph_overview_aggregates_visual_evidence(tmp_path):
    db = make_db(tmp_path)
    source = add_entity(db, "source")
    target = add_entity(db, "target")
    add_edge(db, source, target, "uses")
    add_edge(db, source, target, "uses")

    result = concept_graph_overview.graph_overview(db)

    assert result["total"]["edges"] == 2
    assert result["rendered"]["edges"] == 1
    assert result["edges"][0]["weight"] == 2
    assert result["edges"][0]["evidence_count"] == 2


def test_graph_overview_samples_deterministically_and_keeps_connections(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(concept_graph_overview, "FULL_ATLAS_MAX_NODES", 5)
    monkeypatch.setattr(concept_graph_overview, "FULL_ATLAS_MAX_EDGES", 5)
    monkeypatch.setattr(concept_graph_overview, "SAMPLED_ATLAS_MAX_NODES", 6)
    monkeypatch.setattr(concept_graph_overview, "SAMPLED_ATLAS_MAX_EDGES", 6)
    db = make_db(tmp_path)
    entities = [add_entity(db, f"node-{index}") for index in range(12)]
    for source, target in zip(entities, entities[1:]):
        add_edge(db, source, target, "uses")

    first = concept_graph_overview.graph_overview(db)
    second = concept_graph_overview.graph_overview(db)

    assert first["mode"] == "sampled"
    assert first["truncated"] is True
    assert first["rendered"]["nodes"] == 6
    assert [node["id"] for node in first["nodes"]] == [
        node["id"] for node in second["nodes"]
    ]
    selected_ids = {node["id"] for node in first["nodes"]}
    connected_ids = {
        endpoint
        for edge in first["edges"]
        for endpoint in (edge["source"], edge["target"])
    }
    assert connected_ids == selected_ids


def test_graph_overview_bounds_sampled_raw_edge_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(concept_graph_overview, "FULL_ATLAS_MAX_NODES", 3)
    monkeypatch.setattr(concept_graph_overview, "FULL_ATLAS_MAX_EDGES", 3)
    monkeypatch.setattr(concept_graph_overview, "SAMPLED_ATLAS_MAX_NODES", 4)
    monkeypatch.setattr(concept_graph_overview, "SAMPLED_ATLAS_MAX_EDGES", 4)
    monkeypatch.setattr(concept_graph_overview, "SAMPLED_ATLAS_RAW_EDGE_LIMIT", 2)
    db = make_db(tmp_path)
    entities = [add_entity(db, f"node-{index}") for index in range(4)]
    for index in range(6):
        add_edge(db, entities[index % 4], entities[(index + 1) % 4], f"uses-{index}")

    result = concept_graph_overview.graph_overview(db)

    assert result["mode"] == "sampled"
    assert len(result["edges"]) <= 2


def test_graph_overview_marks_platformless_schema_for_rebuild(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, type TEXT);
            CREATE TABLE relationships (
                id INTEGER PRIMARY KEY, source_id INTEGER, target_id INTEGER,
                predicate TEXT
            );
            """
        )

    result = concept_graph_overview.graph_overview(db)

    assert result["schema_status"] == "rebuild_required"
    assert result["nodes"] == []


def test_missing_db_and_missing_seed_fail_safely(tmp_path):
    missing = tmp_path / "nope.db"
    overview = concept_graph_overview.graph_overview(missing)
    assert overview["nodes"] == [] and overview["edges"] == []
    assert concept_neighborhood.neighborhood(missing, 1) is None

    db = make_db(tmp_path)
    assert concept_neighborhood.neighborhood(db, 12345) is None


def test_neighborhood_respects_direction_and_predicate_filters(tmp_path):
    db = make_db(tmp_path)
    a = add_entity(db, "a")
    b = add_entity(db, "b")
    c = add_entity(db, "c")
    add_edge(db, a, b, "uses")
    add_edge(db, c, a, "calls")

    outgoing = concept_neighborhood.neighborhood(db, a, direction="outgoing")
    incoming = concept_neighborhood.neighborhood(db, a, direction="incoming")
    predicate = concept_neighborhood.neighborhood(db, a, predicate="calls")

    assert {node["id"] for node in outgoing["nodes"]} == {a, b}
    assert {node["id"] for node in incoming["nodes"]} == {a, c}
    assert {node["id"] for node in predicate["nodes"]} == {a, c}


def test_build_runs_and_duplicate_candidates_are_readable(tmp_path):
    db = make_db(tmp_path)
    first = add_entity(db, "first")
    second = add_entity(db, "second")
    other_scope = add_entity(db, "other")
    set_embedding(db, first, 1.0, 0.0, 0.0)
    set_embedding(db, second, 0.99, 0.01, 0.0)
    set_embedding(db, other_scope, 1.0, 0.0, 0.0)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE entities SET session_name = 'sess-a' WHERE id IN (?, ?)",
        (first, second),
    )
    conn.execute(
        "UPDATE entities SET session_name = 'sess-b' WHERE id = ?", (other_scope,)
    )
    conn.execute(
        """INSERT INTO concept_build_runs
           (id, scope_type, scope_value, status, memories_processed, created_at, finished_at)
           VALUES ('run-1', 'session', 'sess-a', 'success', 2, '2026-07-12T00:00:00Z', '2026-07-12T00:00:01Z')"""
    )
    conn.commit()
    conn.close()

    runs = concept_store.build_runs(db)
    duplicates = concept_store.duplicates(db, threshold=0.9)

    assert runs[0]["id"] == "run-1"
    assert runs[0]["memories_processed"] == 2
    assert len(duplicates) == 1
    assert {duplicates[0]["entity_a"]["id"], duplicates[0]["entity_b"]["id"]} == {
        first,
        second,
    }


def test_stale_build_result_stops_console_polling():
    stale = {
        "status": "running",
        "started_at": (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat(),
        "created_at": "2026-07-12T00:00:00+00:00",
        "error_code": None,
        "finished_at": None,
    }
    fresh = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "created_at": "2026-07-12T00:00:00+00:00",
        "error_code": None,
        "finished_at": None,
    }

    stale_result = concepts_endpoint._stale_build_result(stale)

    assert stale_result["status"] == "error"
    assert stale_result["error_code"] == "stale_run"
    assert stale_result["finished_at"] is not None
    assert concepts_endpoint._stale_build_result(fresh) is fresh


def test_rejected_concept_build_updates_launch_status(monkeypatch):
    job_id = "rejected-build"
    launch = ({"status": "queued", "error_code": None}, 0.0)
    with concepts_endpoint._launching_concept_builds_lock:
        concepts_endpoint._launching_concept_builds[job_id] = launch
    monkeypatch.setattr(
        concepts_endpoint.mcp_client,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            concepts_endpoint.mcp_client.McpRequestError(422, "invalid scope")
        ),
    )

    try:
        concepts_endpoint._run_concept_build(job_id, {})
        assert launch[0]["status"] == "error"
        assert launch[0]["error_code"] == "mcp_request_error"
        assert launch[0]["finished_at"] is not None
    finally:
        with concepts_endpoint._launching_concept_builds_lock:
            concepts_endpoint._launching_concept_builds.pop(job_id, None)
