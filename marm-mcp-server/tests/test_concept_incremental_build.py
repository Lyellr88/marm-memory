import asyncio
import importlib
import sys

import pytest
from conftest import load_isolated_server


@pytest.fixture
def concepts_env(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(tmp_path / "marm_index.db"))
    concepts = importlib.import_module("marm_mcp_server.endpoints.concepts")
    monkeypatch.setattr(concepts, "CONCEPTS_AVAILABLE", True)
    memory_module = sys.modules["marm_mcp_server.core.memory"]
    return concepts, memory_module


def _seed(memory_module, rows):
    """rows: (id, content) or (id, content, compaction_role)."""
    with memory_module.memory.get_connection() as conn:
        for row in rows:
            mem_id, content = row[0], row[1]
            role = row[2] if len(row) > 2 else None
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp, "
                "compaction_role) VALUES (?, 'sess-a', ?, datetime('now'), ?)",
                (mem_id, content, role),
            )


def _extract(monkeypatch, concepts, by_content):
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    def fake(content):
        names = by_content[content]
        if names is Exception:
            raise RuntimeError("extraction blew up")
        return ExtractionResult(
            entities=[Entity(name, "concept") for name in names],
            relationship_pairs=[],
        )

    concept_build_engine = importlib.import_module(
        "marm_mcp_server.services.concept_build_engine"
    )
    monkeypatch.setattr(concept_build_engine, "extract_entities", fake)


def test_indexes_only_the_requested_ids(concepts_env, monkeypatch):
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha"), ("m2", "beta"), ("m3", "gamma")])
    _extract(
        monkeypatch,
        concepts,
        {"alpha": ["Alpha"], "beta": ["Beta"], "gamma": ["Gamma"]},
    )

    outcomes = asyncio.run(concepts.build_for_memory_ids(["m1", "m3"]))

    assert outcomes == {"m1": "indexed", "m3": "indexed"}
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM entities").fetchall()}
    assert names == {"Alpha", "Gamma"}


def test_memory_with_nothing_extractable_is_done_not_failed(concepts_env, monkeypatch):
    """no_entities completes the task. Retrying it would loop until the
    attempt cap and then park a memory that is simply uninteresting."""
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "ok"), ("m2", "empty")])
    _extract(monkeypatch, concepts, {"ok": ["Thing"], "empty": []})

    outcomes = asyncio.run(concepts.build_for_memory_ids(["m1", "m2"]))

    assert outcomes == {"m1": "indexed", "m2": "no_entities"}


def test_extraction_failure_is_reported_as_failed_not_swallowed(
    concepts_env, monkeypatch
):
    """The aggregate counters return success with zeros here. Only the
    per-memory outcome distinguishes this from a genuinely empty memory."""
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "good"), ("m2", "poison")])
    _extract(monkeypatch, concepts, {"good": ["Good"], "poison": Exception})

    outcomes = asyncio.run(concepts.build_for_memory_ids(["m1", "m2"]))

    assert outcomes == {"m1": "indexed", "m2": "failed"}


def test_entity_write_failure_marks_the_memory_failed(concepts_env, monkeypatch):
    """A partially written memory must retry. get_or_create_entity is
    idempotent, so re-extracting it is safe."""
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "two entities")])
    _extract(monkeypatch, concepts, {"two entities": ["First", "Second"]})

    concept_db = concepts._get_concept_db()
    real = concept_db.get_or_create_entity

    def flaky(conn, name, *args, **kwargs):
        if name == "Second":
            raise RuntimeError("write failed")
        return real(conn, name, *args, **kwargs)

    monkeypatch.setattr(concept_db, "get_or_create_entity", flaky)

    outcomes = asyncio.run(concepts.build_for_memory_ids(["m1"]))

    assert outcomes == {"m1": "failed"}


def test_a_build_where_every_memory_fails_settles_nothing_as_complete(
    concepts_env, monkeypatch
):
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "a"), ("m2", "b")])
    _extract(monkeypatch, concepts, {"a": Exception, "b": Exception})

    outcomes = asyncio.run(concepts.build_for_memory_ids(["m1", "m2"]))

    assert set(outcomes.values()) == {"failed"}


def test_deleted_memory_reports_vanished(concepts_env, monkeypatch):
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"]})

    outcomes = asyncio.run(concepts.build_for_memory_ids(["m1", "m-gone"]))

    assert outcomes == {"m1": "indexed", "m-gone": "vanished"}


def test_compaction_summary_reports_vanished_rather_than_being_indexed(
    concepts_env, monkeypatch
):
    """A memory queued before its session compacted can be a summary by the
    time the worker reaches it. The graph does not index summaries, so the
    task is finished rather than retried forever."""
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "summary text", "summary")])
    _extract(monkeypatch, concepts, {"summary text": ["Should Not Appear"]})

    outcomes = asyncio.run(concepts.build_for_memory_ids(["m1"]))

    assert outcomes == {"m1": "vanished"}
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0


def test_compaction_source_is_indexed(concepts_env, monkeypatch):
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "source text", "source")])
    _extract(monkeypatch, concepts, {"source text": ["Real Concept"]})

    outcomes = asyncio.run(concepts.build_for_memory_ids(["m1"]))

    assert outcomes == {"m1": "indexed"}


def test_refuses_to_write_into_a_graph_awaiting_rebuild(concepts_env, monkeypatch):
    """Mixing incremental writes into a graph already flagged for rebuild
    would put two extraction rules in one database, and settling those tasks
    would mean the rebuild never sees them."""
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"]})

    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        conn.execute(
            "UPDATE concept_schema_metadata SET value = '1' WHERE key = 'schema_version'"
        )

    with pytest.raises(RuntimeError, match="rebuild_required"):
        asyncio.run(concepts.build_for_memory_ids(["m1"]))


def test_refuses_when_concept_extraction_is_unavailable(concepts_env, monkeypatch):
    """Returning no_entities here would delete every task written while
    spaCy was missing, dropping those memories from the graph for good."""
    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])
    monkeypatch.setattr(concepts, "CONCEPTS_AVAILABLE", False)

    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(concepts.build_for_memory_ids(["m1"]))


def test_the_finished_signal_lands_on_every_exit_path(concepts_env, monkeypatch):
    """The worker's shutdown handshake blocks on this event. Any path that
    returns or raises without setting it stalls teardown for a full grace
    period over a build that never started."""
    import threading

    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"]})

    concept_build_engine = importlib.import_module(
        "marm_mcp_server.services.concept_build_engine"
    )

    def run(**patch):
        for name, value in patch.items():
            target = concept_build_engine if name == "_get_concept_db" else concepts
            monkeypatch.setattr(target, name, value)
        finished = threading.Event()
        try:
            asyncio.run(concepts.build_for_memory_ids(["m1"], finished=finished))
        except Exception:
            pass
        return finished.is_set()

    assert run() is True

    finished = threading.Event()
    asyncio.run(concepts.build_for_memory_ids([], finished=finished))
    assert finished.is_set() is True

    assert run(CONCEPTS_AVAILABLE=False) is True

    monkeypatch.setattr(concepts, "CONCEPTS_AVAILABLE", True)

    def explode():
        raise RuntimeError("concept database unavailable")

    assert run(_get_concept_db=explode) is True


def test_empty_id_list_is_a_no_op(concepts_env):
    concepts, _memory_module = concepts_env
    assert asyncio.run(concepts.build_for_memory_ids([])) == {}


def test_a_full_build_retires_the_queue_it_just_covered(concepts_env, monkeypatch):
    """After the v2.36.0 forced rebuild the queue holds the entire corpus. If
    the build that just indexed it does not clear those rows, the worker
    extracts every memory a second time."""
    from marm_mcp_server.core.models import ConceptBuildRequest

    concepts, memory_module = concepts_env
    queue = importlib.import_module("marm_mcp_server.core.concept_queue")
    _seed(memory_module, [("m1", "alpha"), ("m2", "beta")])
    with memory_module.memory.get_connection() as conn:
        queue.enqueue(conn, "m1", "h1")
        queue.enqueue(conn, "m2", "h2")
        conn.execute(
            "UPDATE concept_index_queue SET enqueued_at = '2020-01-01T00:00:00+00:00'"
        )
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"], "beta": ["Beta"]})

    asyncio.run(concepts.marm_concept_build(ConceptBuildRequest(search_all=True)))

    assert queue.counts() == {"pending": 0, "parked": 0}


def test_a_build_leaves_the_queue_row_of_a_memory_it_failed_to_extract(
    concepts_env, monkeypatch
):
    """Retirement keyed on the build succeeding overall, rather than on each
    memory's outcome, would drop the retry for exactly the memories that need
    one."""
    from marm_mcp_server.core.models import ConceptBuildRequest

    concepts, memory_module = concepts_env
    queue = importlib.import_module("marm_mcp_server.core.concept_queue")
    _seed(memory_module, [("m1", "alpha"), ("m2", "poison")])
    with memory_module.memory.get_connection() as conn:
        queue.enqueue(conn, "m1", "h1")
        queue.enqueue(conn, "m2", "h2")
        conn.execute(
            "UPDATE concept_index_queue SET enqueued_at = '2020-01-01T00:00:00+00:00'"
        )
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"], "poison": Exception})

    asyncio.run(concepts.marm_concept_build(ConceptBuildRequest(search_all=True)))

    with memory_module.memory.get_connection() as conn:
        remaining = [
            row[0]
            for row in conn.execute(
                "SELECT memory_id FROM concept_index_queue"
            ).fetchall()
        ]
    assert remaining == ["m2"]


def test_a_memory_written_during_a_build_keeps_its_queue_row(concepts_env, monkeypatch):
    """Its enqueue is newer than the build's start, so the cutoff protects it
    even though the build reported no outcome for it."""
    from marm_mcp_server.core.models import ConceptBuildRequest

    concepts, memory_module = concepts_env
    queue = importlib.import_module("marm_mcp_server.core.concept_queue")
    _seed(memory_module, [("m1", "alpha")])
    with memory_module.memory.get_connection() as conn:
        queue.enqueue(conn, "m1", "h1")
        conn.execute(
            "UPDATE concept_index_queue SET enqueued_at = '2020-01-01T00:00:00+00:00'"
        )
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"]})

    real_run_build = concepts._run_build

    def build_then_write(pages, *args, **kwargs):
        result = real_run_build(pages, *args, **kwargs)
        _seed(memory_module, [("m2", "written mid build")])
        with memory_module.memory.get_connection() as conn:
            queue.enqueue(conn, "m2", "h2")
        return result

    monkeypatch.setattr(concepts, "_run_build", build_then_write)

    asyncio.run(concepts.marm_concept_build(ConceptBuildRequest(search_all=True)))

    with memory_module.memory.get_connection() as conn:
        remaining = [
            row[0]
            for row in conn.execute(
                "SELECT memory_id FROM concept_index_queue"
            ).fetchall()
        ]
    assert remaining == ["m2"]


def test_a_rebuild_that_dies_partway_still_asks_to_be_rebuilt(
    concepts_env, monkeypatch
):
    """The reset drops the old graph before the corpus is extracted. Stamping
    the new schema version there would make an interrupted rebuild report
    `current`, so nothing prompts for it again and the corpus is silently
    missing from the graph, with no queue rows to recover it either."""
    from marm_mcp_server.core.concept_db import inspect_concept_schema
    from marm_mcp_server.core.models import ConceptBuildRequest

    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"]})

    concept_db = concepts._get_concept_db()
    db_path = concept_db.db_path
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn, "legacy", "concept", "sess-a", None, "old", platform="cli"
        )
        conn.execute(
            "UPDATE concept_schema_metadata SET value = '1' WHERE key = 'schema_version'"
        )
    assert inspect_concept_schema(db_path) == "rebuild_required"

    def explode(*_args, **_kwargs):
        raise RuntimeError("rebuild died partway")

    monkeypatch.setattr(concepts, "_run_build", explode)
    asyncio.run(concepts.marm_concept_build(ConceptBuildRequest(search_all=True)))

    assert inspect_concept_schema(db_path) == "rebuild_required"


def test_a_completed_rebuild_marks_the_schema_current(concepts_env, monkeypatch):
    from marm_mcp_server.core.concept_db import inspect_concept_schema
    from marm_mcp_server.core.models import ConceptBuildRequest

    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"]})

    concept_db = concepts._get_concept_db()
    db_path = concept_db.db_path
    with concept_db.get_connection() as conn:
        concept_db.get_or_create_entity(
            conn, "legacy", "concept", "sess-a", None, "old", platform="cli"
        )
        conn.execute(
            "UPDATE concept_schema_metadata SET value = '1' WHERE key = 'schema_version'"
        )

    result = asyncio.run(
        concepts.marm_concept_build(ConceptBuildRequest(search_all=True))
    )

    assert result["graph_rebuilt"] is True
    assert inspect_concept_schema(db_path) == "current"


def test_a_manual_build_refuses_while_another_process_holds_the_graph(
    concepts_env, monkeypatch
):
    """The rebuild path backs up and drops the graph tables. It must not run
    while the other transport's worker is writing into them, and the
    in-process asyncio lock cannot see that worker at all."""
    from marm_mcp_server.core import concept_build_lock
    from marm_mcp_server.core.models import ConceptBuildRequest

    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"]})
    assert concept_build_lock.try_acquire("other-process", "auto_index", 300) is True

    result = asyncio.run(
        concepts.marm_concept_build(ConceptBuildRequest(search_all=True))
    )

    assert result["error_code"] == "build_in_progress"
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0


def test_a_manual_build_runs_once_the_graph_is_free(concepts_env, monkeypatch):
    from marm_mcp_server.core import concept_build_lock
    from marm_mcp_server.core.models import ConceptBuildRequest

    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"]})
    concept_build_lock.try_acquire("other-process", "auto_index", 300)
    concept_build_lock.release("other-process")

    result = asyncio.run(
        concepts.marm_concept_build(ConceptBuildRequest(search_all=True))
    )

    assert result.get("error_code") is None
    assert result["entities_extracted"] == 1


def test_a_manual_build_releases_the_lock_even_when_it_fails(concepts_env, monkeypatch):
    """A build that raises must not leave the graph locked for an hour."""
    from marm_mcp_server.core import concept_build_lock
    from marm_mcp_server.core.models import ConceptBuildRequest

    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])

    def explode(*_args, **_kwargs):
        raise RuntimeError("build blew up")

    monkeypatch.setattr(concepts, "_run_build", explode)

    asyncio.run(concepts.marm_concept_build(ConceptBuildRequest(search_all=True)))

    assert concept_build_lock.current_holder() is None


def test_route_response_never_carries_the_per_memory_outcome_map(
    concepts_env, monkeypatch
):
    """A full build over a large corpus would otherwise attach one entry per
    memory to an MCP response bounded at 1MB."""
    from marm_mcp_server.core.models import ConceptBuildRequest

    concepts, memory_module = concepts_env
    _seed(memory_module, [("m1", "alpha")])
    _extract(monkeypatch, concepts, {"alpha": ["Alpha"]})

    result = asyncio.run(
        concepts.marm_concept_build(ConceptBuildRequest(search_all=True))
    )

    assert "outcomes" not in result
    assert result["memories_processed"] == 1
