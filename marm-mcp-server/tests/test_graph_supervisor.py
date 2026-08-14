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

    def __init__(self, tools=None, start_error=None, close_error=None):
        self._tools = (
            tools if tools is not None else [{"name": n} for n in _ALL_UPSTREAM_TOOLS]
        )
        self._start_error = start_error
        self._close_error = close_error
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
        if self._close_error:
            raise self._close_error


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


def test_stop_resets_state_even_if_close_raises(monkeypatch):
    """Regression: stop() used to mutate _client/_available/_ready only after
    close() returned. A raising close() (e.g. the child already died) would
    then skip that cleanup entirely, leaving is_available() claim True with
    a dead/closing client still cached -- get_client() would hand callers a
    client that's no longer usable. The reset must happen in a finally, so a
    close() failure still leaves the supervisor in a clean not-started state.
    """
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    fake = _FakeClient(close_error=RuntimeError("child already dead"))
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()
    supervisor.is_available()
    assert fake.started is True

    with pytest.raises(RuntimeError, match="child already dead"):
        supervisor.stop()

    assert fake.closed is True  # close() was attempted
    assert supervisor._client is None
    assert supervisor._available is False
    assert not supervisor._ready.is_set()


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


def test_snapshot_reports_explicit_lifecycle_states(monkeypatch):
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    supervisor = gs.GraphSupervisor()

    assert supervisor.snapshot() == {
        "state": "not_started",
        "enabled": True,
        "started": False,
        "available": False,
    }

    with supervisor._state_lock:
        supervisor._state = "stopping"
        supervisor._client = _FakeClient()
        supervisor._available = True

    assert supervisor.snapshot() == {
        "state": "stopping",
        "enabled": True,
        "started": True,
        "available": True,
    }


def test_get_client_returns_none_once_stopped(monkeypatch):
    """Defect 1: is_available() and get_client() were separate reads.

    A caller that passed the availability check could have stop() complete
    before its get_client(), and then dereference None. get_client() now reads
    _available and _client together, so the answer cannot change mid-sequence.
    """
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    fake = _FakeClient()
    monkeypatch.setattr(gs, "CbmClient", lambda **kwargs: fake)

    supervisor = gs.GraphSupervisor()
    assert supervisor.get_client() is fake

    supervisor.stop()
    assert supervisor.get_client() is None
    assert supervisor.is_available() is False


def test_get_client_after_stop_does_not_spawn_a_replacement(monkeypatch):
    """Defect 3: stop() clears _ready, so _ensure_started() ran again.

    Both get_client() and is_available() begin with _ensure_started(), so a call
    arriving after teardown built a second client and returned it live. The
    supervisor had already disowned the first, so nothing would ever close the
    replacement.
    """
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    built = []

    def _build(**kwargs):
        client = _FakeClient()
        built.append(client)
        return client

    monkeypatch.setattr(gs, "CbmClient", _build)

    supervisor = gs.GraphSupervisor()
    supervisor.is_available()
    assert len(built) == 1

    supervisor.stop()
    supervisor.get_client()
    supervisor.is_available()
    supervisor.get_client()

    assert len(built) == 1, f"stop() was not terminal: {len(built)} clients built"
    assert supervisor.snapshot()["started"] is False


def test_stop_during_the_lock_wait_does_not_start_a_replacement(monkeypatch):
    """The double-checked lock has to recheck _stopped, not only _ready.

    _ensure_started() tests _stopped before taking _lock. A caller can pass that
    test, block on the lock while stop() runs to completion, and then acquire it
    and find only _ready cleared. Rechecking _ready alone lets that caller build
    a client after teardown, which nothing will ever close.

    The wrapper below makes that interleaving deterministic instead of relying on
    thread timing: it applies exactly the state stop() leaves behind, at the
    moment the lock is acquired. Calling stop() itself here would deadlock, since
    stop() takes the same lock.
    """
    gs = _fresh_gs()
    monkeypatch.setattr(gs.mcp_settings, "GRAPH_ENABLED", True)
    built = []

    def _build(**kwargs):
        client = _FakeClient()
        built.append(client)
        return client

    monkeypatch.setattr(gs, "CbmClient", _build)
    supervisor = gs.GraphSupervisor()

    class _LockThatStopsOnEntry:
        def __init__(self, real, target):
            self._real = real
            self._target = target
            self.fired = False

        def __enter__(self):
            self._real.acquire()
            if not self.fired:
                self.fired = True
                with self._target._state_lock:
                    self._target._client = None
                    self._target._available = False
                    self._target._state = "not_started"
                self._target._stopped = True
                self._target._ready.clear()
            return self._real

        def __exit__(self, *exc_info):
            self._real.release()
            return False

    supervisor._lock = _LockThatStopsOnEntry(supervisor._lock, supervisor)

    supervisor._ensure_started()

    assert built == [], f"a client was built after stop(): {len(built)}"
    assert supervisor.get_client() is None
    assert supervisor.is_available() is False
