"""HTTP-surface tests for the embedded marm-graph tools.

Covers the pip-packaging-unification spec's core guarantee: a broken/disabled
graph backend degrades to a clean error response and never affects the 7 core
memory tools, and startup never touches the graph backend until it is used.
"""

import asyncio
import threading

import httpx

from conftest import load_isolated_server, local_client


def test_tools_list_exposes_fourteen_operation_ids(monkeypatch, tmp_path):
    """7 core + 5 graph + 2 concept-graph tools are registered on the unified
    server's MCP surface."""
    server = load_isolated_server(monkeypatch, tmp_path)

    names = {t.name for t in server.mcp.tools}

    assert len(names) == 14
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
        "marm_concept_build",
        "marm_concept_recall",
    }


def test_no_graph_network_activity_or_spawn_at_boot(monkeypatch, tmp_path):
    """Lazy-start assertion: importing/booting the server must not touch graph."""
    server = load_isolated_server(monkeypatch, tmp_path)

    assert server.graph_supervisor._ready.is_set() is False
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


def test_cold_graph_startup_does_not_block_concurrent_core_requests(
    monkeypatch, tmp_path
):
    """graph_supervisor's startup (subprocess spawn, handshake, schema check)
    is synchronous, blocking I/O. If a route awaited it directly instead of
    via asyncio.to_thread, one slow/cold first graph call would stall the
    whole event loop -- including the 7 core tools this spec exists to keep
    unaffected. Proves it doesn't: a concurrent /health request must complete
    while a slow graph verification call is still blocked in its own thread.
    """
    release = threading.Event()
    entered = threading.Event()

    class _SlowFakeClient:
        server_version = "0.8.1-fake"

        def start(self):
            pass

        def list_tools(self):
            entered.set()
            assert release.wait(timeout=5), "test deadlocked waiting for release"
            raise ConnectionError("simulated slow-then-failed handshake")

        def close(self):
            pass

    server = load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setenv("GRAPH_ENABLED", "true")
    monkeypatch.setattr(
        "marm_mcp_server.core.graph_supervisor.CbmClient",
        lambda **kwargs: _SlowFakeClient(),
    )

    async def go():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            graph_task = asyncio.create_task(
                ac.post("/marm_graph_index", json={"action": "list"})
            )
            # Wait for the fake client to actually reach the blocking call
            # (not a fixed sleep) -- deterministic, no flakiness under load.
            assert await asyncio.to_thread(entered.wait, 5), (
                "graph task never reached the blocking call"
            )
            assert not graph_task.done(), "fake client should still be blocked"

            health_response = await ac.get("/health")
            assert health_response.status_code == 200

            release.set()
            return await graph_task

    graph_response = asyncio.run(go())
    assert graph_response.status_code == 200
    assert graph_response.json() == {
        "status": "error",
        "message": "graph backend unavailable",
    }


def test_shutdown_stops_graph_supervisor_child(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    stop_calls = []
    monkeypatch.setattr(server.graph_supervisor, "stop", lambda: stop_calls.append(1))

    async def _run_lifespan_once():
        async with server.lifespan(server.app):
            pass

    asyncio.run(_run_lifespan_once())

    assert stop_calls == [1]
