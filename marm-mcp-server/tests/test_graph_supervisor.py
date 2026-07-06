"""Unit tests for graph_supervisor's lazy-start / degrade-to-error control flow.

Uses a lightweight CbmClient double (same start()/list_tools()/close() surface)
instead of the real subprocess: this is testing the supervisor's own exception
handling and lazy-start bookkeeping, not codebase-memory-mcp's IPC. Real-binary
transport behavior is already covered by marm-graph's own requires_binary suite.

Fetches the graph_supervisor module fresh inside each test (rather than a
module-level import) because other test files' load_isolated_server() helper
deletes and reimports marm_mcp_server.* between tests — a stale module-level
binding here would patch a different module object than the one a freshly
constructed GraphSupervisor actually reads from.
"""

import importlib
import threading

import pytest
import structlog


def _fresh_gs():
    """Import (or re-fetch) marm_mcp_server.core.graph_supervisor as it stands
    right now, so patches land on the exact module object in use."""
    return importlib.import_module("marm_mcp_server.core.graph_supervisor")


_ALL_UPSTREAM_TOOLS = [
    "index_repository",
    "search_graph",
    "query_graph",
    "trace_path",
    "get_code_snippet",
    "get_graph_schema",
    "get_architecture",
    "search_code",
    "list_projects",
    "delete_project",
    "index_status",
    "detect_changes",
    "manage_adr",
    "ingest_traces",
]


class _FakeClient:
    """Stands in for CbmClient: same start()/list_tools()/close() surface."""

    def __init__(self, tools=None, start_error=None):
        self._tools = (
            tools if tools is not None else [{"name": n} for n in _ALL_UPSTREAM_TOOLS]
        )
        self._start_error = start_error
        self.server_version = "0.8.1-fake"
        self.started = False
        self.closed = False

    def start(self):
        if self._start_error:
            raise self._start_error
        self.started = True

    def list_tools(self):
        return self._tools

    def close(self):
        self.closed = True


def test_graph_disabled_short_circuits_before_any_client_construction(monkeypatch):
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", False)

    def _boom(**kwargs):
        raise AssertionError(
            "CbmClient must not be constructed when GRAPH_ENABLED=false"
        )

    monkeypatch.setattr(gs, "CbmClient", _boom)

    supervisor = gs.GraphSupervisor()
    assert supervisor.is_available() is False
    assert supervisor.get_client() is None


def test_healthy_backend_becomes_available(monkeypatch):
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    fake = _FakeClient()
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()
    assert supervisor.is_available() is True
    assert fake.started is True
    assert supervisor.get_client() is fake


def test_schema_drift_degrades_to_unavailable_not_crash(monkeypatch):
    """A missing expected upstream tool must be caught, not raised through.

    Also proves the started-but-failed-verification client is closed, not
    orphaned: start() succeeds (spawning the child) before check_schema()
    raises, so the except path in _ensure_started must call client.close()
    itself -- nothing else would ever clean up that live subprocess.
    """
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    drifted = [{"name": n} for n in _ALL_UPSTREAM_TOOLS if n != "search_graph"]
    fake = _FakeClient(tools=drifted)
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()
    assert supervisor.is_available() is False
    assert supervisor.get_client() is None
    assert fake.started is True  # confirms this is the started-then-failed path
    assert fake.closed is True


def test_transport_failure_on_start_degrades_to_unavailable(monkeypatch):
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    fake = _FakeClient(start_error=OSError("no network"))
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()
    assert supervisor.is_available() is False


def test_start_is_lazy_and_idempotent(monkeypatch):
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    calls = []

    def _make(**kwargs):
        calls.append(kwargs)
        return _FakeClient()

    monkeypatch.setattr(gs, "CbmClient", _make)

    supervisor = gs.GraphSupervisor()
    assert calls == []  # nothing spawned just from constructing the supervisor

    supervisor.is_available()
    supervisor.is_available()
    supervisor.get_client()
    assert len(calls) == 1  # only one CbmClient built despite 3 calls


def test_concurrent_calls_during_inflight_startup_all_wait_for_the_result(
    monkeypatch,
):
    """A caller during an in-flight (slow) startup must not observe a
    premature False -- it must block on the lock until the first caller's
    attempt actually resolves, then see the real result. Before the fix,
    a plain "start attempted" flag was set before verify_and_start()
    completed, so a second caller could skip the lock entirely and read
    _available while it was still False but startup was genuinely ongoing.
    """
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)

    entered = threading.Event()
    release = threading.Event()

    class _SlowFakeClient(_FakeClient):
        def start(self):
            entered.set()
            assert release.wait(timeout=5), "test deadlocked waiting for release"
            super().start()

    fake = _SlowFakeClient()
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()
    results = []

    def _caller():
        results.append(supervisor.is_available())

    first = threading.Thread(target=_caller)
    first.start()
    assert entered.wait(timeout=5), "first caller never reached the blocking call"

    # A second caller starts while the first is still blocked inside start().
    second = threading.Thread(target=_caller)
    second.start()

    # It must still be blocked (on the lock), not already returned with a
    # premature False -- this is the actual regression check.
    second.join(timeout=0.2)
    assert second.is_alive(), "second caller returned before startup resolved"

    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert results == [True, True]


def test_first_run_download_logs_before_start(monkeypatch, tmp_path):
    """The supervisor's own INFO line must appear when the binary isn't cached
    yet, independent of the child's own stderr (routed to DEBUG by CbmClient)."""
    _cli = pytest.importorskip("codebase_memory_mcp._cli")

    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    monkeypatch.setattr(_cli, "_bin_path", lambda version: tmp_path / "not-cached-yet")
    fake = _FakeClient()
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()
    with structlog.testing.capture_logs() as logs:
        supervisor.is_available()

    messages = [entry.get("event") for entry in logs]
    assert any("downloading graph engine" in (m or "") for m in messages)


def test_cached_binary_skips_download_log(monkeypatch, tmp_path):
    _cli = pytest.importorskip("codebase_memory_mcp._cli")

    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    cached = tmp_path / "already-cached"
    cached.touch()
    monkeypatch.setattr(_cli, "_bin_path", lambda version: cached)
    fake = _FakeClient()
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()
    with structlog.testing.capture_logs() as logs:
        supervisor.is_available()

    messages = [entry.get("event") for entry in logs]
    assert not any("downloading graph engine" in (m or "") for m in messages)


def test_stop_closes_client_and_resets_state(monkeypatch):
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    fake = _FakeClient()
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()
    supervisor.is_available()
    assert fake.started is True

    supervisor.stop()
    assert fake.closed is True
    assert supervisor._client is None
    assert supervisor._available is False


def test_stop_during_inflight_startup_waits_and_leaves_consistent_state(
    monkeypatch,
):
    """Regression: stop() used to mutate _client/_available/_ready without
    the lock _ensure_started() uses. A stop() racing an in-flight startup
    could interleave with that critical section and leave _available True
    with _client None -- a caller's get_client() would then return None
    while is_available() just said the backend was up. stop() must block on
    the same lock until the in-flight startup resolves, then tear down
    whatever it produced.
    """
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)

    entered = threading.Event()
    release = threading.Event()

    class _SlowFakeClient(_FakeClient):
        def start(self):
            entered.set()
            assert release.wait(timeout=5), "test deadlocked waiting for release"
            super().start()

    fake = _SlowFakeClient()
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()

    starter = threading.Thread(target=supervisor.is_available)
    starter.start()
    assert entered.wait(timeout=5), "startup never reached the blocking call"

    stopper = threading.Thread(target=supervisor.stop)
    stopper.start()

    # stop() must block on the same lock as _ensure_started(), not interleave
    stopper.join(timeout=0.2)
    assert stopper.is_alive(), "stop() proceeded before startup resolved"

    release.set()
    starter.join(timeout=5)
    stopper.join(timeout=5)

    assert fake.started is True  # the in-flight startup actually completed
    assert fake.closed is True  # ...then stop() tore it down
    assert supervisor._client is None
    assert supervisor._available is False


def test_stop_on_never_started_supervisor_is_a_no_op(monkeypatch):
    """Shutdown must be safe even if no graph tool was ever called."""
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", False)
    supervisor = gs.GraphSupervisor()
    supervisor.stop()  # must not raise
    assert supervisor.is_available() is False
