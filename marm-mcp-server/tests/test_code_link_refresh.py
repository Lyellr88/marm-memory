import asyncio
import importlib
import sys
import threading

import pytest
from conftest import load_isolated_server


@pytest.fixture
def refresh_env(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(tmp_path / "marm_index.db"))
    concepts = importlib.import_module("marm_mcp_server.endpoints.concepts")
    engine = importlib.import_module("marm_mcp_server.services.concept_build_engine")
    worker_module = importlib.import_module("marm_mcp_server.core.concept_worker")
    return {
        "concepts": concepts,
        "concept_db": engine._get_concept_db(),
        "memory": sys.modules["marm_mcp_server.core.memory"].memory,
        "worker": worker_module.ConceptIndexWorker(),
        "worker_module": worker_module,
    }


def _scope(memory, project: str) -> None:
    with memory.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, project) "
            "VALUES (?, 'session', 'content', datetime('now'), ?)",
            (f"memory-{project}", project),
        )


def _entity(concept_db, name: str, project: str) -> int:
    with concept_db.get_connection() as conn:
        entity_id, _ = concept_db.get_or_create_entity(
            conn, name, "concept", None, project, f"source-{name}"
        )
    return entity_id


def _enqueue_task(graph_project: str, memory_project: str):
    from marm_mcp_server.core import code_link_queue

    code_link_queue.enqueue_refresh(graph_project, memory_project, "/repo")
    return code_link_queue.claim()[0]


def _bind(memory, graph_project: str, memory_project: str) -> None:
    from marm_mcp_server.core import code_project_bindings

    _scope(memory, memory_project)
    code_project_bindings.set_user_binding(graph_project, memory_project, "/repo")


def test_refresh_reconciles_exact_links_without_extracting_entities(
    refresh_env, monkeypatch
):
    from marm_mcp_server.core import code_link_queue, graph_client

    concept_db = refresh_env["concept_db"]
    _bind(refresh_env["memory"], "graph-project", "memory-project")
    entity_id = _entity(concept_db, "Alpha", "memory-project")
    task = _enqueue_task("graph-project", "memory-project")
    monkeypatch.setattr(
        graph_client,
        "find_code_match",
        lambda name, project: {
            "status": "matched",
            "qualified_name": f"module.{name}",
            "label": name,
            "file_path": "module.py",
        },
    )
    engine = importlib.import_module("marm_mcp_server.services.concept_build_engine")
    monkeypatch.setattr(
        engine,
        "extract_entities",
        lambda _content: (_ for _ in ()).throw(AssertionError("refresh extracted")),
    )

    asyncio.run(refresh_env["worker"]._refresh_code_links(task, threading.Event()))

    with concept_db.get_connection() as conn:
        row = conn.execute(
            "SELECT graph_qualified_name, link_method, file_path FROM entity_code_links "
            "WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
    assert row == ("module.Alpha", "exact_symbol", "module.py")
    assert code_link_queue.status("graph-project") is None


def test_refresh_preserves_existing_links_when_the_graph_is_unavailable(
    refresh_env, monkeypatch
):
    from marm_mcp_server.core import code_link_queue, graph_client

    concept_db = refresh_env["concept_db"]
    _bind(refresh_env["memory"], "graph-project", "memory-project")
    entity_id = _entity(concept_db, "Alpha", "memory-project")
    with concept_db.get_connection() as conn:
        concept_db.store_code_link(
            conn, entity_id, "module.Alpha", "graph-project", label="Alpha"
        )
    task = _enqueue_task("graph-project", "memory-project")
    monkeypatch.setattr(
        graph_client,
        "find_code_match",
        lambda _name, _project: {"status": "unavailable"},
    )

    asyncio.run(refresh_env["worker"]._refresh_code_links(task, threading.Event()))

    with concept_db.get_connection() as conn:
        link_count = conn.execute(
            "SELECT COUNT(*) FROM entity_code_links WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()[0]
    assert link_count == 1
    status = code_link_queue.status("graph-project")
    assert status is not None
    assert status["state"] == "pending"
    assert status["attempts"] == 1
    assert status["last_error"] == "unavailable"


def test_refresh_continues_after_an_ambiguous_entity(refresh_env, monkeypatch):
    from marm_mcp_server.core import code_link_queue, graph_client

    concept_db = refresh_env["concept_db"]
    _bind(refresh_env["memory"], "graph-project", "memory-project")
    ambiguous_id = _entity(concept_db, "Config", "memory-project")
    unique_id = _entity(concept_db, "Alpha", "memory-project")
    task = _enqueue_task("graph-project", "memory-project")
    monkeypatch.setattr(
        graph_client,
        "find_code_match",
        lambda name, _project: (
            {"status": "ambiguous", "candidates": ["one.Config", "two.Config"]}
            if name == "Config"
            else {
                "status": "matched",
                "qualified_name": "module.Alpha",
                "file_path": "module.py",
            }
        ),
    )

    asyncio.run(refresh_env["worker"]._refresh_code_links(task, threading.Event()))

    with concept_db.get_connection() as conn:
        linked_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entity_code_links")
        }
    assert linked_ids == {unique_id}
    assert ambiguous_id not in linked_ids
    assert code_link_queue.status("graph-project") is None


def test_refresh_cannot_alter_entities_outside_its_bound_memory_scope(
    refresh_env, monkeypatch
):
    from marm_mcp_server.core import graph_client

    concept_db = refresh_env["concept_db"]
    _bind(refresh_env["memory"], "graph-a", "memory-a")
    _scope(refresh_env["memory"], "memory-b")
    entity_a = _entity(concept_db, "Alpha", "memory-a")
    entity_b = _entity(concept_db, "Beta", "memory-b")
    task = _enqueue_task("graph-a", "memory-a")
    monkeypatch.setattr(
        graph_client,
        "find_code_match",
        lambda name, _project: {
            "status": "matched",
            "qualified_name": f"module.{name}",
        },
    )

    asyncio.run(refresh_env["worker"]._refresh_code_links(task, threading.Event()))

    with concept_db.get_connection() as conn:
        linked_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entity_code_links")
        }
    assert linked_ids == {entity_a}
    assert entity_b not in linked_ids


def test_memory_tasks_drain_before_a_queued_code_link_refresh(refresh_env, monkeypatch):
    from marm_mcp_server.core import code_link_queue, memory_ops

    memory = refresh_env["memory"]
    _bind(memory, "graph-project", "memory-project")
    monkeypatch.setattr(memory_ops, "MARM_PROJECT", "memory-project")
    events: list[str] = []
    original_refresh = refresh_env["worker"]._refresh_code_links

    async def build(memory_ids, **_kwargs):
        events.append(f"memory:{memory_ids[0]}")
        return dict.fromkeys(memory_ids, "no_entities")

    async def refresh(task, abort):
        events.append(f"refresh:{task.graph_project}")
        await original_refresh(task, abort)

    monkeypatch.setattr(refresh_env["concepts"], "build_for_memory_ids", build)
    monkeypatch.setattr(refresh_env["worker"], "_refresh_code_links", refresh)

    async def scenario():
        await memory.store_memory("new memory", "session")
        code_link_queue.enqueue_refresh("graph-project", "memory-project", "/repo")
        await refresh_env["worker"]._drain()

    asyncio.run(scenario())

    assert events[0].startswith("memory:")
    assert events[1:] == ["refresh:graph-project"]
