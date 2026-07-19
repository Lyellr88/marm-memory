"""Tests for endpoints/concepts.py's build/recall orchestration.

_fetch_memory_rows and the concept-DB read/write paths run against real
SQLite (tmp_path-backed, via conftest.load_isolated_server). extract_entities
is monkeypatched at the endpoints module boundary for build tests -- spaCy's
actual model isn't installable in this sandbox (see test_concept_extraction.py),
and these tests exercise _run_build's write/orchestration logic, not NER
accuracy, so a fake ExtractionResult at that one boundary is appropriate
(testing-philosophy.md: mock only where it doesn't weaken what's being tested).
"""

import asyncio
import importlib
import sys

import numpy as np
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


def test_promoted_doc_mirror_reachable_by_matching_scoped_build(monkeypatch, tmp_path):
    """notebook-scratch-and-docs-db.md's Testing Checklist: a promoted
    doc's memories mirror must be picked up by a marm_concept_build call
    scoped to the doc's own project/session, and must NOT be picked up by
    a build scoped to a different project. Drives the real action='save'
    path (not a hand-inserted memories row) so this proves the actual
    mirror-write wiring, not just that _fetch_memory_rows' SQL is capable
    of finding a row shaped like one."""
    from conftest import load_isolated_server

    load_isolated_server(monkeypatch, tmp_path, write_queue_enabled=True)
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(tmp_path / "marm_index.db"))
    monkeypatch.setenv("MARM_DOCS_DB_PATH", str(tmp_path / "marm_docs.db"))
    concepts = importlib.import_module("marm_mcp_server.endpoints.concepts")
    notebook_service = importlib.import_module("marm_mcp_server.services.notebook")

    result = asyncio.run(
        notebook_service.notebook_dispatch(
            action="save",
            name="architecture-doc",
            data="MARM uses three separate SQLite databases for memory, index, and docs.",
            session_name="main",
            project="marm-systems",
            platform=None,
        )
    )
    assert result["status"] == "success"
    assert result["mirror_status"] == "synced"

    matching_rows = concepts._fetch_memory_rows(
        session_name=None, project="marm-systems", search_all=False
    )
    assert result["memory_id"] in [r[0] for r in matching_rows]

    other_project_rows = concepts._fetch_memory_rows(
        session_name=None, project="a-different-project", search_all=False
    )
    assert result["memory_id"] not in [r[0] for r in other_project_rows]


def test_marm_concept_build_route_returns_static_message_on_missing_scope(
    concepts_env,
):
    """The HTTP route's ValueError handler must return the known-good
    literal, not str(e) -- regression coverage for the CodeQL
    exception-info-exposure fix: same response text as before, but no
    longer built from a live exception object.

    ConceptBuildRequest's own model_validator already rejects this same
    input at the pydantic layer (a different message, enforced before the
    route body ever runs), so _fetch_memory_rows' runtime ValueError is
    unreachable via a normally-constructed request -- model_construct
    bypasses that validation to exercise the route's own except-ValueError
    handling directly, same as it would need to if _fetch_memory_rows'
    check were ever the only guard left."""
    _server, concepts, _memory_module = concepts_env
    from marm_mcp_server.core.models import ConceptBuildRequest

    req = ConceptBuildRequest.model_construct(
        session_name=None, project=None, search_all=False
    )
    result = asyncio.run(concepts.marm_concept_build(req))

    assert result == {
        "status": "error",
        "message": concepts._MISSING_BUILD_SCOPE_MESSAGE,
    }


def test_marm_concept_build_reports_degraded_when_concepts_are_unavailable(
    concepts_env, monkeypatch
):
    _server, concepts, _memory_module = concepts_env
    from marm_mcp_server.core.models import ConceptBuildRequest

    monkeypatch.setattr(concepts, "CONCEPTS_AVAILABLE", False)
    result = asyncio.run(
        concepts.marm_concept_build(ConceptBuildRequest(session_name="sess-a"))
    )

    assert result["status"] == "degraded"
    assert result["error_code"] == "concepts_unavailable"
    assert result["entities_extracted"] == 0


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


def test_fetch_memory_rows_excludes_compacted_source_rows(concepts_env):
    """Mirrors core/memory_recall.py's active-recall filter -- a compacted
    session's stale source rows must not be indexed alongside their summary,
    or a build reintroduces obsolete concepts/relationships and inflates
    mention counts."""
    _server, concepts, memory_module = concepts_env
    with memory_module.memory.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, project) "
            "VALUES ('m1', 'sess-a', 'stale source content', datetime('now'), NULL)"
        )
        conn.execute("UPDATE memories SET compaction_role = 'source' WHERE id = 'm1'")
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, project) "
            "VALUES ('m2', 'sess-a', 'compaction summary content', datetime('now'), NULL)"
        )

    rows = concepts._fetch_memory_rows(
        session_name="sess-a", project=None, search_all=False
    )
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
            relationship_pairs=[("auth module", "rate limiter", "uses")],
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
            relationship_pairs=[("auth module", "rate limiter", "uses")],
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
    _server, concepts, _memory_module = concepts_env
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
    _server, concepts, _memory_module = concepts_env
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

    result = concepts._run_build([("m1", "CbmClient reference", "sess-a", "proj-a")])
    assert result["code_links_created"] == 1


def test_run_build_reports_no_duplicates_when_embedding_unavailable(
    concepts_env, monkeypatch
):
    """Default state: conftest.load_isolated_server forces _encoder_failed =
    True for test isolation, so _try_embed fails open for real (not
    simulated) and possible_duplicates stays empty rather than erroring."""
    _server, concepts, _memory_module = concepts_env
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    monkeypatch.setattr(
        concepts,
        "extract_entities",
        lambda content: ExtractionResult(
            entities=[Entity("auth module", "concept")], relationship_pairs=[]
        ),
    )
    monkeypatch.setattr(concepts, "is_graph_available", lambda: False)

    result = concepts._run_build([("m1", "auth module content", "sess-a", None)])
    assert result["possible_duplicates"] == []


def test_run_build_reports_possible_duplicate_when_similar_entity_exists(
    concepts_env, monkeypatch
):
    """_try_embed monkeypatched at the module boundary (same convention as
    extract_entities/find_code_match) with deterministic fake vectors --
    exercises find_similar_entities' real SQL/numpy cosine logic without
    depending on a real model being loadable."""
    _server, concepts, _memory_module = concepts_env
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    fake_vectors = {
        "Auth": np.asarray([1.0, 0.0, 0.0], dtype=np.float32).tobytes(),
        "OAuth": np.asarray([0.99, 0.01, 0.0], dtype=np.float32).tobytes(),
    }
    monkeypatch.setattr(concepts, "_try_embed", lambda name: fake_vectors[name])
    monkeypatch.setattr(concepts, "is_graph_available", lambda: False)

    extraction_by_content = {
        "Auth content": ExtractionResult(
            entities=[Entity("Auth", "concept")], relationship_pairs=[]
        ),
        "OAuth content": ExtractionResult(
            entities=[Entity("OAuth", "concept")], relationship_pairs=[]
        ),
    }
    monkeypatch.setattr(
        concepts, "extract_entities", lambda content: extraction_by_content[content]
    )

    rows = [
        ("m1", "Auth content", "sess-a", None),
        ("m2", "OAuth content", "sess-a", None),
    ]
    result = concepts._run_build(rows)

    assert len(result["possible_duplicates"]) == 1
    dup = result["possible_duplicates"][0]
    assert dup["entity"] == "OAuth"
    assert dup["candidates"][0]["name"] == "Auth"
    assert dup["candidates"][0]["similarity"] >= 0.9


def test_run_build_caches_embed_calls_across_repeated_entity_names(
    concepts_env, monkeypatch
):
    """get_or_create_entity only stores an embedding on the INSERT branch --
    re-mentions of the same name across multiple memories in one build must
    not re-run the (encoder-lock-serialized) embed call for a result that's
    discarded every time but the first."""
    _server, concepts, _memory_module = concepts_env
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    call_count = {"n": 0}

    def _counting_embed(name):
        call_count["n"] += 1
        return np.asarray([1.0, 0.0, 0.0], dtype=np.float32).tobytes()

    monkeypatch.setattr(concepts, "_try_embed", _counting_embed)
    monkeypatch.setattr(concepts, "is_graph_available", lambda: False)
    monkeypatch.setattr(
        concepts,
        "extract_entities",
        lambda content: ExtractionResult(
            entities=[Entity("auth module", "concept")], relationship_pairs=[]
        ),
    )

    rows = [
        ("m1", "auth module content one", "sess-a", None),
        ("m2", "auth module content two", "sess-a", None),
        ("m3", "auth module content three", "sess-a", None),
    ]
    result = concepts._run_build(rows)

    assert result["entities_extracted"] == 3  # three mentions processed
    assert call_count["n"] == 1  # but the name was only ever embedded once


def test_try_embed_real_fastembed_end_to_end(concepts_env):
    """The one place real-model coverage is actually possible in this
    sandbox for Goal 3 -- fastembed itself is installed (unlike spaCy's
    en_core_web_sm), but its model weights are also network-blocked here
    (confirmed: 403 on download), so this dynamically skips rather than
    asserting a specific outcome if loading genuinely isn't possible in the
    current environment."""
    _server, concepts, memory_module = concepts_env
    memory_module.memory._encoder_failed = False
    memory_module.memory.encoder = None

    emb_bytes = concepts._try_embed("auth module")
    if emb_bytes is None:
        pytest.skip("fastembed model weights not downloadable in this sandbox")

    assert isinstance(emb_bytes, bytes)
    assert len(emb_bytes) % 4 == 0  # whole number of float32 values


def test_run_recall_lookup_mode_returns_matching_entities(concepts_env):
    _server, concepts, _memory_module = concepts_env
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
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-a", None, "m1"
        )

    result = concepts._run_recall("related to auth module", session_name=None, limit=10)
    assert len(result["entities"]) == 1


def test_run_recall_returns_related_entities_from_relationships(concepts_env):
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_a, _ = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-a", None, "m1"
        )
        id_b, _ = concept_db.get_or_create_entity(
            conn, "rate limiter", "pattern", "sess-a", None, "m1"
        )
        concept_db.store_relationship(conn, id_a, id_b, "co_occurs_with", "m1", None)

    result = concepts._run_recall("auth module", session_name=None, limit=10)
    related_names = {r["name"] for r in result["related_entities"]}
    assert "rate limiter" in related_names


def test_run_recall_project_scoping_excludes_other_projects(concepts_env):
    """entities.UNIQUE(name, session_name, project) treats project as part
    of an entity's identity -- two projects can each have their own
    same-named entity as distinct rows. Recall must not blend them together
    when a project is given."""
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn, "config", "concept", "sess-a", "proj-a", "m1"
        )
        concept_db.get_or_create_entity(
            conn, "config", "concept", "sess-a", "proj-b", "m2"
        )

    unscoped = concepts._run_recall("config", session_name=None, limit=10)
    assert len(unscoped["entities"]) == 2

    scoped = concepts._run_recall(
        "config", session_name=None, limit=10, project="proj-a"
    )
    assert len(scoped["entities"]) == 1
    assert scoped["entities"][0]["name"] == "config"


# ── Goal 2: multi-hop traversal ──────────────────────────────────────


def _build_chain_graph(concept_db, conn):
    """A -> B -> C, plus a D -> A back-edge to make a genuine cycle
    (A -> B -> C, D -> A) without any entity pointing directly at itself."""
    id_a, _ = concept_db.get_or_create_entity(
        conn, "A", "concept", "sess-a", None, "m1"
    )
    id_b, _ = concept_db.get_or_create_entity(
        conn, "B", "concept", "sess-a", None, "m1"
    )
    id_c, _ = concept_db.get_or_create_entity(
        conn, "C", "concept", "sess-a", None, "m1"
    )
    id_d, _ = concept_db.get_or_create_entity(
        conn, "D", "concept", "sess-a", None, "m1"
    )
    concept_db.store_relationship(conn, id_a, id_b, "uses", "m1", None)
    concept_db.store_relationship(conn, id_b, id_c, "uses", "m1", None)
    concept_db.store_relationship(conn, id_d, id_a, "uses", "m1", None)
    return id_a, id_b, id_c, id_d


def test_traverse_depth_1_reproduces_one_hop_behavior(concepts_env):
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_a, _id_b, _id_c, _id_d = _build_chain_graph(concept_db, conn)
        results = concepts._traverse(conn, [id_a], depth=1, direction="both", limit=10)

    names = {r["name"] for r in results}
    assert names == {"B", "D"}  # A's direct neighbors only, not C
    assert all(r["hop"] == 1 for r in results)
    assert all("path" not in r for r in results)  # depth=1: no path field


def test_traverse_emits_direct_edges_between_two_seeds(concepts_env):
    """Regression test: recall's `name LIKE '%query%'` routinely matches a
    cluster of related entities that are themselves directly connected --
    e.g. "auth module" and "auth service" both match a query for "auth".
    Those direct edges are exactly the most relevant relationships to
    surface, but an earlier version of _traverse silently suppressed them
    (both seeds were pre-loaded into a single visited set, so neither could
    ever be emitted as the other's neighbor)."""
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_module, _ = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-a", None, "m1"
        )
        id_service, _ = concept_db.get_or_create_entity(
            conn, "auth service", "concept", "sess-a", None, "m1"
        )
        concept_db.store_relationship(conn, id_module, id_service, "uses", "m1", None)

        results = concepts._traverse(
            conn, [id_module, id_service], depth=1, direction="both", limit=10
        )

    names = {r["name"] for r in results}
    assert names == {"auth module", "auth service"}


def test_run_recall_emits_direct_edges_between_two_matched_seeds(concepts_env):
    """Same regression, exercised through the real marm_concept_recall path
    (name LIKE matching two related entities), not just _traverse directly."""
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_module, _ = concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-a", None, "m1"
        )
        id_service, _ = concept_db.get_or_create_entity(
            conn, "auth service", "concept", "sess-a", None, "m1"
        )
        concept_db.store_relationship(conn, id_module, id_service, "uses", "m1", None)

    result = concepts._run_recall("auth", session_name=None, limit=10)
    related_names = {r["name"] for r in result["related_entities"]}
    assert related_names == {"auth module", "auth service"}


def test_traverse_multi_hop_finds_second_degree_neighbor(concepts_env):
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_a, _id_b, _id_c, _id_d = _build_chain_graph(concept_db, conn)
        results = concepts._traverse(conn, [id_a], depth=2, direction="both", limit=10)

    by_name = {r["name"]: r for r in results}
    assert "C" in by_name  # only reachable at hop 2 (A -> B -> C)
    assert by_name["C"]["hop"] == 2
    assert by_name["B"]["hop"] == 1
    assert by_name["C"]["path"] == [
        {"predicate": "uses", "name": "B"},
        {"predicate": "uses", "name": "C"},
    ]


def test_traverse_handles_cycles_without_infinite_loop_or_duplicates(concepts_env):
    """A -> B -> C -> A is a genuine 3-node cycle. Traversing outgoing from
    A at depth=5 must terminate (not loop forever re-visiting A) and must
    not return A itself or duplicate B/C -- proves the visited-set is
    actually load-bearing, not just documentation."""
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_a, _ = concept_db.get_or_create_entity(
            conn, "A", "concept", "sess-a", None, "m1"
        )
        id_b, _ = concept_db.get_or_create_entity(
            conn, "B", "concept", "sess-a", None, "m1"
        )
        id_c, _ = concept_db.get_or_create_entity(
            conn, "C", "concept", "sess-a", None, "m1"
        )
        concept_db.store_relationship(conn, id_a, id_b, "uses", "m1", None)
        concept_db.store_relationship(conn, id_b, id_c, "uses", "m1", None)
        concept_db.store_relationship(conn, id_c, id_a, "uses", "m1", None)

        results = concepts._traverse(
            conn, [id_a], depth=5, direction="outgoing", limit=100
        )

    names = [r["name"] for r in results]
    assert names.count("A") == 0  # seed itself never re-appears as a result
    assert names.count("B") == 1
    assert names.count("C") == 1


def test_traverse_direction_outgoing_only_excludes_incoming(concepts_env):
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_a, _id_b, _id_c, _id_d = _build_chain_graph(concept_db, conn)
        results = concepts._traverse(
            conn, [id_a], depth=1, direction="outgoing", limit=10
        )

    names = {r["name"] for r in results}
    assert names == {"B"}  # D -> A is incoming, excluded


def test_traverse_direction_incoming_only_excludes_outgoing(concepts_env):
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_a, _id_b, _id_c, _id_d = _build_chain_graph(concept_db, conn)
        results = concepts._traverse(
            conn, [id_a], depth=1, direction="incoming", limit=10
        )

    names = {r["name"] for r in results}
    assert names == {"D"}  # A -> B is outgoing, excluded


def test_traverse_respects_limit_across_whole_traversal(concepts_env):
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        id_a, _id_b, _id_c, _id_d = _build_chain_graph(concept_db, conn)
        results = concepts._traverse(conn, [id_a], depth=5, direction="both", limit=1)

    assert len(results) == 1


def test_run_recall_depth_2_returns_second_hop_entity(concepts_env):
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        _build_chain_graph(concept_db, conn)

    result = concepts._run_recall(
        "A", session_name=None, limit=10, depth=2, direction="both"
    )
    names = {r["name"] for r in result["related_entities"]}
    assert "C" in names


def test_run_recall_default_depth_matches_prior_one_hop_behavior(concepts_env):
    """Omitting depth/direction (STDIO callers, or older client code) must
    reproduce exactly today's one-hop behavior -- backward-compatible
    defaults, not a breaking change to marm_concept_recall."""
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        _build_chain_graph(concept_db, conn)

    result = concepts._run_recall("A", session_name=None, limit=10)
    names = {r["name"] for r in result["related_entities"]}
    assert names == {"B", "D"}
    assert "C" not in names


def test_run_recall_on_entity_with_no_code_match_returns_empty_not_error(concepts_env):
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn, "auth module", "concept", "sess-a", None, "m1"
        )

    result = concepts._run_recall("auth module", session_name=None, limit=10)
    assert result["linked_code"] == []


def test_run_recall_on_entity_with_code_match_populates_linked_code(concepts_env):
    _server, concepts, _memory_module = concepts_env
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        entity_id, _ = concept_db.get_or_create_entity(
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
    """marm_concept_build/marm_concept_recall must be registered regardless of
    whether the [concepts] extra (spaCy + en_core_web_sm) is installed -- that
    part is environment-independent and always checked.

    Whether extraction itself runs for real depends on what's actually
    installed in this environment, so we detect CONCEPTS_AVAILABLE instead of
    assuming a fixed value: no model installed exercises the fail-open path
    (0 entities from real content, since extract_entities degrades gracefully
    per its own docstring); a model installed exercises the real NER path
    with real content and expects it to actually find something."""
    from marm_mcp_server.config.settings import CONCEPTS_AVAILABLE
    from marm_mcp_server.server import MCP_TOOL_OPERATIONS

    assert "marm_concept_build" in MCP_TOOL_OPERATIONS
    assert "marm_concept_recall" in MCP_TOOL_OPERATIONS

    _server, concepts, memory_module = concepts_env
    _seed_memory(
        memory_module,
        [("m1", "sess-a", "The write queue serializes memory writes.", None)],
    )
    rows = concepts._fetch_memory_rows(session_name=None, project=None, search_all=True)
    result = concepts._run_build(rows)

    if CONCEPTS_AVAILABLE:
        assert result["entities_extracted"] > 0, (
            "concepts extra is installed in this environment, so real NER "
            f"extraction over seeded content should find entities: {result}"
        )
    else:
        assert result["entities_extracted"] == 0


def test_get_concept_db_lock_serializes_concurrent_first_calls(
    concepts_env, monkeypatch
):
    """Both tools dispatch via asyncio.to_thread, so first-use is genuinely
    concurrent-capable. Before the lock, two concurrent first calls could
    each construct (and one leak) a ConceptDB/connection pool -- mirrors
    the existing encoder-lock mutation-test pattern."""
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
