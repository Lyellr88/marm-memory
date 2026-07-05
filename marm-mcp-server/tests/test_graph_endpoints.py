"""HTTP-surface tests for the embedded marm-graph tools.

Covers the pip-packaging-unification spec's core guarantee: a broken/disabled
graph backend degrades to a clean error response and never affects the 7 core
memory tools, and startup never touches the graph backend until it is used.
"""

import asyncio

from conftest import load_isolated_server, local_client


def test_tools_list_exposes_twelve_operation_ids(monkeypatch, tmp_path):
    """7 core + 5 graph tools are registered on the unified server's MCP surface."""
    server = load_isolated_server(monkeypatch, tmp_path)

    names = {t.name for t in server.mcp.tools}

    assert len(names) == 12
    assert names == {
        "marm_smart_recall",
        "marm_log_entry",
        "marm_log_show",
        "marm_delete",
        "marm_summary",
        "marm_notebook",
        "marm_compaction",
        "marm_graph_index",
        "marm_code_lookup",
        "marm_graph_trace",
        "marm_graph_architecture",
        "marm_graph_impact",
    }


def test_no_graph_network_activity_or_spawn_at_boot(monkeypatch, tmp_path):
    """Lazy-start assertion: importing/booting the server must not touch graph."""
    server = load_isolated_server(monkeypatch, tmp_path)

    assert server.graph_supervisor._start_attempted is False
    assert server.graph_supervisor._client is None


def test_graph_enabled_false_short_circuits_before_subprocess_spawn(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    server = load_isolated_server(monkeypatch, tmp_path)

    def _boom(**kwargs):
        raise AssertionError(
            "CbmClient must not be constructed when GRAPH_ENABLED=false"
        )

    monkeypatch.setattr("marm_mcp_server.core.graph_supervisor.CbmClient", _boom)

    client = local_client(server.app)
    response = client.post("/marm_graph_index", json={"action": "list"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "message": "graph backend unavailable",
    }
    assert server.graph_supervisor.is_available() is False


def test_core_memory_tools_work_when_graph_disabled(monkeypatch, tmp_path):
    """The failure-isolation guarantee the whole spec exists for."""
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    log_response = client.post(
        "/marm_log_entry",
        json={"session_name": "main", "entry": "graph-disabled smoke test"},
    )
    assert log_response.status_code == 200
    assert log_response.json()["status"] == "success"

    recall_response = client.post(
        "/marm_smart_recall", json={"query": "graph-disabled smoke test"}
    )
    assert recall_response.status_code == 200

    notebook_response = client.post(
        "/marm_notebook",
        json={"action": "add", "name": "gd-test", "data": "still works"},
    )
    assert notebook_response.status_code == 200
    assert notebook_response.json()["status"] == "success"


def test_all_five_graph_tools_return_clean_error_when_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    calls = [
        ("/marm_graph_index", {"action": "list"}),
        ("/marm_code_lookup", {"query": "anything"}),
        ("/marm_graph_trace", {"function_name": "anything"}),
        ("/marm_graph_architecture", {}),
        ("/marm_graph_impact", {}),
    ]
    for path, body in calls:
        response = client.post(path, json=body)
        assert response.status_code == 200, path
        assert response.json() == {
            "status": "error",
            "message": "graph backend unavailable",
        }, path


def test_shutdown_stops_graph_supervisor_child(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    stop_calls = []
    monkeypatch.setattr(server.graph_supervisor, "stop", lambda: stop_calls.append(1))

    async def _run_lifespan_once():
        async with server.lifespan(server.app):
            pass

    asyncio.run(_run_lifespan_once())

    assert stop_calls == [1]
