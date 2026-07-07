"""Tests for endpoints/concepts.py's build/recall orchestration.

_fetch_memory_rows and the concept-DB read/write paths run against real
SQLite (tmp_path-backed, via conftest.load_isolated_server). extract_entities
is monkeypatched at the endpoints module boundary for build tests -- spaCy's
actual model isn't installable in this sandbox (see test_concept_extraction.py),
and these tests exercise _run_build's write/orchestration logic, not NER
accuracy, so a fake ExtractionResult at that one boundary is appropriate
(testing-philosophy.md: mock only where it doesn't weaken what's being tested).
"""

import importlib
import sys

import pytest
from conftest import load_isolated_server


def _fresh_concepts_module(monkeypatch, tmp_path, concept_db_path=None):
    server = load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "MARM_CONCEPT_DB_PATH", str(concept_db_path or tmp_path / "marm_index.db")
    )
    concepts = importlib.import_module("marm_mcp_server.endpoints.concepts")
    return server, concepts


def _seed_memory(memory_module, rows):
    """rows: list of (id, session_name, content, project) tuples."""
    with memory_module.memory.get_connection() as conn:
        for mem_id, session_name, content, project in rows:
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp, project) "
                "VALUES (?, ?, ?, datetime('now'), ?)",
                (mem_id, session_name, content, project),
            )


@pytest.fixture
def concepts_env(monkeypatch, tmp_path):
    server, concepts = _fresh_concepts_module(monkeypatch, tmp_path)
    memory_module = sys.modules["marm_mcp_server.core.memory"]
    return server, concepts, memory_module


def test_fetch_memory_rows_scoped_by_session(concepts_env):
    _server, concepts, memory_module = concepts_env
    _seed_memory(
        memory_module,
        [
            ("m1", "sess-a", "first memory", None),
            ("m2", "sess-b", "second memory", None),
        ],
    )
    rows = concepts._fetch_memory_rows(
        session_name="sess-a", project=None, search_all=False
    )
    assert [r[0] for r in rows] == ["m1"]


def test_fetch_memory_rows_requires_explicit_scope(concepts_env):
    """No session_name, no project, search_all=False must raise -- not
    silently fall through to scanning every memory in the DB."""
    _server, concepts, _memory_module = concepts_env
    with pytest.raises(ValueError, match="session_name, project, or search_all"):
        concepts._fetch_memory_rows(session_name=None, project=None, search_all=False)


def test_fetch_memory_rows_excludes_marm_system_session(concepts_env):
    _server, concepts, memory_module = concepts_env
    _seed_memory(
        memory_module,
        [
            ("m1", "marm_system", "internal bookkeeping row", None),
            ("m2", "sess-a", "real content", None),
        ],
    )
    rows = concepts._fetch_memory_rows(session_name=None, project=None, search_all=True)
    assert [r[0] for r in rows] == ["m2"]


def test_fetch_memory_rows_search_all_respects_row_cap(concepts_env, monkeypatch):
    _server, concepts, memory_module = concepts_env
    monkeypatch.setattr(concepts, "CONCEPT_BUILD_ROW_CAP", 3)
    _seed_memory(
        memory_module,
        [(f"m{i}", "sess-a", f"content {i}", None) for i in range(10)],
    )
    rows = concepts._fetch_memory_rows(session_name=None, project=None, search_all=True)
    assert len(rows) == 3


def test_run_build_writes_entities_and_relationship_for_two_entities(
    concepts_env, monkeypatch
):
    _server, concepts, memory_module = concepts_env
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    monkeypatch.setattr(
        concepts,
        "extract_entities",
        lambda content: ExtractionResult(
            entities=[
                Entity("auth module", "concept"),
                Entity("rate limiter", "pattern"),
            ],
            relationship_pairs=[("auth module", "rate limiter")],
        ),
    )
    monkeypatch.setattr(concepts, "is_graph_available", lambda: False)

    rows = [("m1", "auth module talks to the rate limiter", "sess-a", "proj-a")]
    result = concepts._run_build(rows)

    assert result["entities_extracted"] == 2
    assert result["relationships_created"] == 1
    assert result["code_links_created"] == 0

    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        rel_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    assert entity_count == 2
    assert rel_count == 1


def test_run_build_is_idempotent_on_repeat_runs(concepts_env, monkeypatch):
    """Re-running marm_concept_build on the same corpus (documented expected
    usage -- MARMIS may schedule it, or an agent may call it more than once)
    must not create duplicate relationship/code-link rows. Reproduces the
    review finding directly: entities dedup correctly via UNIQUE, but
    relationships/code_links had no dedup at all before the fix."""
    _server, concepts, _memory_module = concepts_env
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    monkeypatch.setattr(
        concepts,
        "extract_entities",
        lambda content: ExtractionResult(
            entities=[
                Entity("auth module", "concept"),
                Entity("rate limiter", "pattern"),
            ],
            relationship_pairs=[("auth module", "rate limiter")],
        ),
    )
    monkeypatch.setattr(concepts, "is_graph_available", lambda: True)
    monkeypatch.setattr(
        concepts,
        "find_code_match",
        lambda name, project: {
            "qualified_name": f"marm_graph.core.{name.replace(' ', '_')}",
            "label": "class",
            "file_path": "x.py",
        },
    )

    rows = [("m1", "auth module talks to the rate limiter", "sess-a", "proj-a")]
    first = concepts._run_build(rows)
    second = concepts._run_build(rows)

    assert first["relationships_created"] == 1
    assert first["code_links_created"] == 2  # one per entity
    # Second run re-processes the same memory but every row already exists.
    assert second["relationships_created"] == 0
    assert second["code_links_created"] == 0

    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        rel_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        link_count = conn.execute("SELECT COUNT(*) FROM entity_code_links").fetchone()[
            0
        ]
    assert rel_count == 1
    assert link_count == 2


def test_run_recall_does_not_return_duplicate_linked_code_after_repeat_build(
    concepts_env, monkeypatch
):
    """Direct regression test for the review's reproduction: before the dedup
    fix, an entity linked across a repeat build surfaced the same code link
    multiple times in marm_concept_recall's response."""
    _server, concepts, _memory_module = concepts_env
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    monkeypatch.setattr(
        concepts,
        "extract_entities",
        lambda content: ExtractionResult(
            entities=[Entity("CbmClient", "concept")], relationship_pairs=[]
        ),
    )
    monkeypatch.setattr(concepts, "is_graph_available", lambda: True)
    monkeypatch.setattr(
        concepts,
        "find_code_match",
        lambda name, project: {
            "qualified_name": "marm_graph.core.cbm_client.CbmClient",
            "label": "class",
            "file_path": "marm_graph/core/cbm_client.py",
        },
    )

    rows = [("m1", "CbmClient reference", "sess-a", "proj-a")]
    concepts._run_build(rows)
    concepts._run_build(rows)  # repeat build, same corpus

    result = concepts._run_recall("CbmClient", session_name=None, limit=10)
    assert len(result["linked_code"]) == 1


def test_run_build_same_entity_across_two_memories_dedups_in_same_session(
    concepts_env, monkeypatch
):
    _server, concepts, memory_module = concepts_env
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    monkeypatch.setattr(
        concepts,
        "extract_entities",
        lambda content: ExtractionResult(
            entities=[Entity("auth module", "concept")], relationship_pairs=[]
        ),
    )
    monkeypatch.setattr(concepts, "is_graph_available", lambda: False)

    rows = [
        ("m1", "auth module content one", "sess-a", None),
        ("m2", "auth module content two", "sess-a", None),
    ]
    result = concepts._run_build(rows)
    assert result["entities_extracted"] == 2  # two mentions processed

    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    assert entity_count == 1  # but one distinct entity row


def test_run_build_with_graph_unavailable_creates_zero_code_links(
    concepts_env, monkeypatch
):
    _server, concepts, memory_module = concepts_env
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    monkeypatch.setattr(
        concepts,
        "extract_entities",
        lambda content: ExtractionResult(
            entities=[Entity("CbmClient", "concept")], relationship_pairs=[]
        ),
    )
    monkeypatch.setattr(concepts, "is_graph_available", lambda: False)
    monkeypatch.setattr(
        concepts,
        "find_code_match",
        lambda *a, **k: pytest.fail("should never be called when graph is unavailable"),
    )

    result = concepts._run_build([("m1", "CbmClient reference", "sess-a", "proj-a")])
    assert result["code_links_created"] == 0


def test_run_build_links_code_when_graph_available(concepts_env, monkeypatch):
    _server, concepts, memory_module = concepts_env
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    monkeypatch.setattr(
        concepts,
        "extract_entities",
        lambda content: ExtractionResult(
            entities=[Entity("CbmClient", "concept")], relationship_pairs=[]
        ),
    )
    monkeypatch.setattr(concepts, "is_graph_available", lambda: True)
    monkeypatch.setattr(
        concepts,
        "find_code_match",
        lambda name, project: {
            "qualified_name": "marm_graph.core.cbm_client.CbmClient",
            "label": "class",
            "file_path": "marm_graph/core/cbm_client.py",
        },
    )

    result = concepts._run_build([("m1", "CbmClient reference", "sess-a", "proj-a")])
    assert result["code_links_created"] == 1


def test_run_recall_lookup_mode_returns_matching_entities(concepts_env):
    _server, concepts, memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-a", None, "m1"
        )

    result = concepts._run_recall("auth", session_name=None, limit=10)
    assert len(result["entities"]) == 1
    assert result["entities"][0]["name"] == "auth module"
    assert result["linked_code"] == []


def test_run_recall_related_to_prefix_strips_and_still_matches(concepts_env):
    _server, concepts, memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-a", None, "m1"
        )

    result = concepts._run_recall("related to auth module", session_name=None, limit=10)
    assert len(result["entities"]) == 1


def test_run_recall_returns_related_entities_from_relationships(concepts_env):
    _server, concepts, memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_a = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-a", None, "m1"
        )
        id_b = concept_db.get_or_create_entity(
            conn, "rate limiter", "pattern", "sess-a", None, "m1"
        )
        concept_db.store_relationship(conn, id_a, id_b, "co_occurs_with", "m1", None)

    result = concepts._run_recall("auth module", session_name=None, limit=10)
    related_names = {r["name"] for r in result["related_entities"]}
    assert "rate limiter" in related_names


def test_run_recall_on_entity_with_no_code_match_returns_empty_not_error(concepts_env):
    _server, concepts, memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-a", None, "m1"
        )

    result = concepts._run_recall("auth module", session_name=None, limit=10)
    assert result["linked_code"] == []


def test_run_recall_on_entity_with_code_match_populates_linked_code(concepts_env):
    _server, concepts, memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        entity_id = concept_db.get_or_create_entity(
            conn, "CbmClient", "concept", "sess-a", "proj-a", "m1"
        )
        concept_db.store_code_link(
            conn,
            entity_id,
            "marm_graph.core.cbm_client.CbmClient",
            "proj-a",
            label="class",
            file_path="marm_graph/core/cbm_client.py",
        )

    result = concepts._run_recall("CbmClient", session_name=None, limit=10)
    assert result["linked_code"] == [
        {
            "qualified_name": "marm_graph.core.cbm_client.CbmClient",
            "label": "class",
            "file_path": "marm_graph/core/cbm_client.py",
        }
    ]


def test_concept_build_never_imports_smart_recall():
    """marm_concept_build must read the memory DB layer directly, never through
    marm_smart_recall's ranked/limited recall path."""
    from marm_mcp_server.endpoints import concepts

    assert "smart_recall" not in concepts.__dict__


def test_tool_count_includes_both_concept_tools():
    from marm_mcp_server.server import MCP_TOOL_OPERATIONS

    assert "marm_concept_build" in MCP_TOOL_OPERATIONS
    assert "marm_concept_recall" in MCP_TOOL_OPERATIONS


def test_base_install_without_concepts_extra_still_registers_tools(concepts_env):
    """CONCEPTS_AVAILABLE is False in this sandbox (no en_core_web_sm model) --
    this genuinely exercises the base-install path, not a simulation."""
    from marm_mcp_server.config.settings import CONCEPTS_AVAILABLE
    from marm_mcp_server.server import MCP_TOOL_OPERATIONS

    assert CONCEPTS_AVAILABLE is False
    assert "marm_concept_build" in MCP_TOOL_OPERATIONS

    _server, concepts, _memory_module = concepts_env
    rows = concepts._fetch_memory_rows(session_name=None, project=None, search_all=True)
    result = concepts._run_build(rows)
    assert result["entities_extracted"] == 0


def test_get_concept_db_lock_serializes_concurrent_first_calls(
    concepts_env, monkeypatch
):
    """Both tools dispatch via asyncio.to_thread, so first-use is genuinely
    concurrent-capable. Before the lock, two concurrent first calls could
    each construct (and one leak) a ConceptDB/connection pool -- mirrors
    test_dashboard_encoder_lock.py's proven mutation-test pattern."""
    import threading

    _server, concepts, _memory_module = concepts_env
    concepts._concept_db = None

    entered = threading.Event()
    release = threading.Event()
    instances_created = {"count": 0}

    real_concept_db_cls = concepts.ConceptDB

    class _SlowConceptDB(real_concept_db_cls):
        def __init__(self, *a, **k):
            instances_created["count"] += 1
            entered.set()
            release.wait(timeout=5)
            super().__init__(*a, **k)

    monkeypatch.setattr(concepts, "ConceptDB", _SlowConceptDB)

    results = []

    def _caller():
        results.append(concepts._get_concept_db())

    first = threading.Thread(target=_caller)
    first.start()
    assert entered.wait(timeout=5), "first caller never reached ConceptDB construction"

    second = threading.Thread(target=_caller)
    second.start()
    second.join(timeout=0.2)
    assert second.is_alive(), "second caller proceeded before the lock released"

    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert instances_created["count"] == 1
    assert results[0] is results[1]
