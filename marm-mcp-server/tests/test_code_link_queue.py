import sys
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def isolated_memory(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    load_isolated_server(monkeypatch, tmp_path)
    return sys.modules["marm_mcp_server.core.memory"].memory


def _scope(memory, project: str) -> None:
    with memory.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, project) "
            "VALUES (?, 'session', 'content', datetime('now'), ?)",
            (f"memory-{project}", project),
        )


def test_auto_binding_uses_normalized_root_directory(isolated_memory):
    from marm_mcp_server.core import code_project_bindings

    _scope(isolated_memory, "MARM Systems")

    state, binding = code_project_bindings.auto_bind(
        "C-Users-lyell-Desktop-MARM-Systems", r"C:\Users\lyell\Desktop\MARM-Systems"
    )

    assert state == "bound"
    assert binding is not None
    assert binding.memory_project == "MARM Systems"
    assert binding.source == "auto"


def test_auto_binding_refuses_multiple_matching_memory_scopes(isolated_memory):
    from marm_mcp_server.core import code_project_bindings

    _scope(isolated_memory, "MARM Systems")
    _scope(isolated_memory, "marm-systems")

    state, binding = code_project_bindings.auto_bind(
        "marm-systems", "/work/MARM-Systems"
    )

    assert state == "ambiguous"
    assert binding is None


def test_user_binding_refuses_to_retarget_an_existing_graph_project(isolated_memory):
    from marm_mcp_server.core import code_project_bindings

    _scope(isolated_memory, "memory-a")
    _scope(isolated_memory, "memory-b")
    code_project_bindings.set_user_binding("graph", "memory-a", "/work/a")

    with pytest.raises(ValueError, match="graph_project_already_bound"):
        code_project_bindings.set_user_binding("graph", "memory-b", "/work/b")

    binding = code_project_bindings.get_by_graph_project("graph")
    assert binding is not None
    assert binding.memory_project == "memory-a"


def test_reenqueue_preserves_claimed_work_and_rejects_stale_completion(isolated_memory):
    from marm_mcp_server.core import code_link_queue

    code_link_queue.enqueue_refresh("graph", "memory", "/work/memory")
    task = code_link_queue.claim()[0]
    code_link_queue.enqueue_refresh("graph", "memory", "/work/memory")

    assert code_link_queue.complete(task) is False
    with isolated_memory.get_connection() as conn:
        conn.execute(
            "UPDATE code_link_refresh_queue SET leased_until = ? WHERE graph_project = 'graph'",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
        )
    reclaimed = code_link_queue.claim()[0]
    assert reclaimed.graph_project == "graph"
    assert reclaimed.enqueued_at != task.enqueued_at


def test_reenqueue_after_failure_clears_the_retry_lease(isolated_memory):
    from marm_mcp_server.core import code_link_queue

    code_link_queue.enqueue_refresh("graph", "memory", "/work/memory")
    task = code_link_queue.claim()[0]
    assert code_link_queue.fail(task, "unavailable") is True

    code_link_queue.enqueue_refresh("graph", "memory", "/work/memory")
    retried = code_link_queue.claim()

    assert len(retried) == 1
    assert retried[0].graph_project == "graph"


def test_refresh_queue_drop_removes_pending_work(isolated_memory):
    from marm_mcp_server.core import code_link_queue

    code_link_queue.enqueue_refresh("graph", "memory", "/work/memory")

    assert code_link_queue.drop_project("graph") is True
    assert code_link_queue.status("graph") is None
