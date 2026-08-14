"""HTTP-surface tests for the embedded marm-graph tools.

Covers the pip-packaging-unification spec's core guarantee: a broken/disabled
graph backend degrades to a clean error response and never affects the 7 core
memory tools, and startup never touches the graph backend until it is used.
"""

import asyncio
import threading
import time

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


def test_console_project_routes_are_internal_and_degrade_cleanly(monkeypatch, tmp_path):
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.post("/internal/projects/list", json={})

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "message": "graph backend unavailable",
    }
    assert "internal/projects/list" not in {tool.name for tool in server.mcp.tools}


def test_console_index_rejects_invalid_path_before_graph_start(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.post(
        "/internal/projects/index",
        json={"repo_path": "relative/project", "mode": "fast"},
    )

    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "Repository path must be an existing absolute directory."
    )
    assert server.graph_supervisor._client is None


def test_console_index_releases_single_flight_lock_when_thread_cannot_start(
    monkeypatch, tmp_path
):
    server = load_isolated_server(monkeypatch, tmp_path)
    graph = __import__("marm_mcp_server.endpoints.graph", fromlist=["router"])
    client = local_client(server.app)
    original_thread = graph.threading.Thread

    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread startup failed")

    monkeypatch.setattr(graph.threading, "Thread", FailingThread)
    failed = client.post(
        "/internal/projects/index", json={"repo_path": str(tmp_path), "mode": "fast"}
    )
    assert failed.status_code == 500

    monkeypatch.setattr(graph.threading, "Thread", original_thread)
    retry = client.post(
        "/internal/projects/index", json={"repo_path": str(tmp_path), "mode": "fast"}
    )
    assert retry.status_code == 202

    # The 202 above proves the start-failure path released the lock. Draining the
    # job then proves the worker's own finally released it too, and keeps the
    # daemon thread from outliving this test: tmp_path is deleted at teardown, so
    # an abandoned index fails against a missing directory and surfaces as a
    # child-process error under whichever unrelated test happens to be running.
    job = _drain_index_job(client, retry.json()["job_id"])
    assert job["status"] in {"success", "error"}
    assert graph._project_job_lock.acquire(blocking=False)
    graph._project_job_lock.release()


def _drain_index_job(client, job_id: str, timeout: float = 60.0) -> dict:
    """Poll a console index job until it reaches a terminal state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/internal/projects/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"success", "error"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"index job {job_id} did not finish within {timeout}s")


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


def test_delete_project_with_graph_disabled_returns_unavailable_not_500(
    monkeypatch, tmp_path
):
    """Contract guard, not a regression test: this passed before the None guard.

    The spec listed it as evidence for the fix, which was wrong. With the engine
    disabled the route's own gate short-circuits ahead of _resolve_and_delete, so
    the unguarded dereference was never reachable this way. Reaching it needs the
    supervisor to go away *after* the gate, which the stop-race test below covers.
    Kept because it pins the payload every graph route is supposed to return.
    """
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    server = load_isolated_server(monkeypatch, tmp_path)

    client = local_client(server.app)
    response = client.post(
        "/internal/projects/delete",
        json={"project": "marm-memory", "name": "marm-memory", "confirm": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "message": "graph backend unavailable",
    }


def test_delete_project_after_supervisor_stop_does_not_respawn_the_engine(
    monkeypatch, tmp_path
):
    """A request arriving after teardown, driven through the real route.

    Named for what it does: stop() completes before the request starts, so this
    covers the post-stop path, not the lock-order window. That window is covered
    deterministically in test_graph_supervisor.py, where the interleaving can be
    forced instead of raced.

    The no-new-child assertion is the point. A re-acquired client used to spawn a
    replacement engine nobody owned, and the call succeeded, so neither the
    response nor the logs showed anything wrong.
    """
    server = load_isolated_server(monkeypatch, tmp_path)
    graph = server.graph_supervisor
    built = []

    class _Client:
        def __init__(self):
            built.append(self)
            self.closed = False

        def start(self):
            pass

        def list_tools(self):
            return []

        def close(self):
            self.closed = True

        def call_tool(self, name, arguments, timeout=None):
            raise AssertionError("no call may reach a disowned client")

    monkeypatch.setattr(
        "marm_mcp_server.core.graph_supervisor.CbmClient", lambda **kwargs: _Client()
    )
    with graph._state_lock:
        graph._client = _Client()
        graph._available = True
    graph._ready.set()

    graph.stop()

    client = local_client(server.app)
    response = client.post(
        "/internal/projects/delete",
        json={"project": "marm-memory", "name": "marm-memory", "confirm": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert len(built) == 1, f"a replacement engine was spawned: {len(built)} clients"
    assert built[0].closed is True
