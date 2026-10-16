import importlib
import json
import socket
import socketserver
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def modules(tmp_path, monkeypatch):
    manager = importlib.import_module("marm_mcp_server.core.runtime_manager")
    control = importlib.import_module("marm_mcp_server.console.runtime_control")
    logs = importlib.import_module("marm_mcp_server.console.runtime_logs")
    setup = importlib.import_module("marm_mcp_server.console.endpoints.setup")
    settings = importlib.import_module("marm_mcp_server.config.user_settings")
    jobs = importlib.import_module("marm_mcp_server.console.jobs")
    monkeypatch.setenv("MARM_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MARM_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("MARM_CONSOLE_HOST", "127.0.0.1")
    monkeypatch.delenv("MARM_SETTINGS_SHADOWED", raising=False)
    monkeypatch.delenv("SERVER_HOST", raising=False)
    monkeypatch.delenv("SERVER_PORT", raising=False)
    monkeypatch.setattr(
        control,
        "_registry",
        jobs.JobRegistry("test-runtime", reject_different_kind=True),
    )
    monkeypatch.setattr(control, "runtime_manager", manager)
    monkeypatch.setattr(setup, "runtime_manager", manager)
    monkeypatch.setattr(setup, "runtime_control", control)
    monkeypatch.setattr(logs, "runtime_manager", manager)
    return manager, control, logs, setup, settings


def client_for(setup, *, raise_server_exceptions=True):
    app = FastAPI()
    app.include_router(setup.router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def wait_job(control, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = control.get_job(job_id)
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.01)
    pytest.fail("Job did not finish")


@pytest.mark.parametrize("marm", [False, True])
def test_real_listener_blocks_start_and_never_authorizes_stop(modules, marm):
    manager, _, _, setup, settings = modules

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps({"service": "MARM MCP Server" if marm else "other"}).encode()
            )

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.save({"server.port": server.server_port})
    try:
        assert manager.port_owner() == ("marm" if marm else "other")
        with client_for(setup) as client:
            response = client.post("/api/connections/runtime/start")
            assert response.status_code == 409
            assert response.json()["reason"] == "port_in_use"
            assert client.post("/api/connections/runtime/stop").status_code == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_saved_port_and_removed_overlay_resolve_like_child(modules, monkeypatch):
    manager, _, _, _, settings = modules
    monkeypatch.setenv("SERVER_PORT", "8123")
    settings.save({"server.port": 9234})
    assert manager.intended_address() == ("127.0.0.1", 9234)
    settings._write_raw({})
    monkeypatch.setenv("MARM_SETTINGS_SHADOWED", json.dumps({"SERVER_PORT": None}))
    assert manager.intended_address()[1] == 8001


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError(10061, "refused"),
        TimeoutError("timeout"),
        ConnectionResetError("reset"),
    ],
)
def test_inconclusive_connect_after_bind_conflict_is_unknown(
    modules, monkeypatch, error
):
    manager, _, _, _, _ = modules

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(manager.socket, "create_connection", fail)
    import errno

    class CannotBind:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def setsockopt(self, *args):
            pass

        def bind(self, address):
            raise OSError(errno.EADDRINUSE, "in use")

    monkeypatch.setattr(manager.socket, "socket", lambda *args, **kwargs: CannotBind())
    assert manager.port_owner() == "unknown"


@pytest.mark.parametrize("reply", [404, 401, "plain", "banner"])
def test_other_listener_is_classified_without_breaking_routes(
    modules, monkeypatch, reply
):
    manager, _, _, setup, settings = modules
    if reply == "banner":

        class Banner(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    self.request.sendall(b"220 smtp.example ESMTP ready\r\n")
                except OSError:
                    pass

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Banner)
        server.daemon_threads = True
    else:

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload = b"This is not MARM."
                self.send_response(reply if isinstance(reply, int) else 200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.save({"server.port": server.server_address[1]})
    monkeypatch.setattr(setup.client_operations, "list_agents", lambda *_: [])
    monkeypatch.setattr(setup, "_skills_installed", lambda: 0)
    try:
        with client_for(setup, raise_server_exceptions=False) as client:
            overview = client.get("/api/connections/overview")
            assert overview.status_code == 200
            assert overview.json()["runtime"]["port_owner"] == "other"
            assert overview.json()["runtime"]["can_start"] is False
            start = client.post("/api/connections/runtime/start")
            assert start.status_code == 409
            assert start.json()["reason"] == "port_in_use"
            assert client.post("/api/connections/runtime/restart").status_code == 409
            assert client.post("/api/connections/runtime/stop").status_code == 409
        assert manager.port_owner() == "other"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_stopped_restart_starts_with_saved_settings(modules, monkeypatch):
    manager, control, _, setup, settings = modules
    settings.save({"server.port": 9234})
    monkeypatch.setattr(manager, "port_owner", lambda: "none")
    launched = []
    monkeypatch.setattr(
        manager,
        "start_background",
        lambda **kwargs: launched.append((manager.intended_address(), kwargs)),
    )
    with client_for(setup) as client:
        response = client.post("/api/connections/runtime/restart")
        assert response.status_code == 202
        assert wait_job(control, response.json()["job_id"])["status"] == "done"
    assert launched[0][0] == ("127.0.0.1", 9234)


def test_atomic_job_conflicts_and_same_kind_reuse(modules, monkeypatch):
    manager, control, _, _, _ = modules
    monkeypatch.setattr(manager, "port_owner", lambda: "none")
    release = threading.Event()
    entered = threading.Event()

    def start(**kwargs):
        entered.set()
        release.wait(5)

    monkeypatch.setattr(manager, "start_background", start)
    try:
        first = control.start_runtime()
        assert entered.wait(2)
        assert control.start_runtime() == first
        jobs = importlib.import_module("marm_mcp_server.console.jobs")
        with pytest.raises(jobs.JobConflict, match="Another action"):
            control.stop_runtime()
    finally:
        release.set()
        wait_job(control, first)


def test_worker_rechecks_ownership_before_launch(modules, monkeypatch):
    manager, control, _, _, _ = modules
    owners = iter(["none", "marm"])
    monkeypatch.setattr(manager, "port_owner", lambda: next(owners))

    def forbidden(**kwargs):
        pytest.fail("Must not launch")

    monkeypatch.setattr(manager, "start_background", forbidden)
    job = wait_job(control, control.start_runtime())
    assert job["status"] == "error"
    assert "in use" in job["detail"]


@pytest.mark.parametrize("path", ["start", "stop", "restart", "logs"])
def test_runtime_routes_are_loopback_only(modules, monkeypatch, path):
    _, _, _, setup, _ = modules
    monkeypatch.setattr(setup, "_loopback_only", lambda: False)
    with client_for(setup) as client:
        response = (
            client.get(f"/api/connections/runtime/{path}")
            if path == "logs"
            else client.post(f"/api/connections/runtime/{path}")
        )
        assert response.status_code == 403


def test_log_tail_incremental_partial_and_regrown_rotation(modules):
    manager, _, logs, _, _ = modules
    assert logs.tail()["exists"] is False
    path = manager.log_path()
    path.parent.mkdir()
    path.write_bytes(b"one\ntwo\n")
    first = logs.tail(lines=1)
    assert first["lines"] == ["two"]
    with path.open("ab") as stream:
        stream.write("three\né".encode())
    second = logs.tail(first["cursor"])
    assert second["lines"] == ["three"]
    assert not second["rotated"]
    with path.open("ab") as stream:
        stream.write(b"\n")
    third = logs.tail(second["cursor"])
    assert third["lines"] == ["é"]
    path.write_bytes(b"rotated\n" * 100)
    rotated = logs.tail(third["cursor"], lines=2)
    assert rotated["rotated"] and rotated["lines"] == ["rotated", "rotated"]


def test_log_cap_utf8_and_long_line_progress(modules):
    manager, _, logs, _, _ = modules
    path = manager.log_path()
    path.parent.mkdir()
    path.write_bytes(b"first\n" + b"x" * 256)
    first = logs.tail()
    path.write_bytes(b"first\n" + b"x" * 65279 + "é".encode() + b"\nlast\n")
    chunk = logs.tail(first["cursor"])
    assert chunk["lines"][0].endswith("[truncated]")
    assert "\ufffd" not in chunk["lines"][0]
    next_chunk = logs.tail(chunk["cursor"])
    assert next_chunk["lines"] == ["é", "last"]
    assert logs.tail(next_chunk["cursor"])["lines"] == []


def test_invalid_log_cursor_is_a_client_error(modules):
    _, _, _, setup, _ = modules
    with client_for(setup) as client:
        assert (
            client.get(
                "/api/connections/runtime/logs", params={"cursor": "bad"}
            ).status_code
            == 400
        )


def test_initial_tail_of_long_utf8_line_does_not_split_a_character(modules):
    manager, _, logs, _, _ = modules
    path = manager.log_path()
    path.parent.mkdir()
    path.write_bytes("é".encode() * 50000 + b"x")
    response = logs.tail()
    assert response["lines"][0].endswith("[truncated]")
    assert "\ufffd" not in response["lines"][0]
    assert logs.tail(response["cursor"])["lines"] == []


def test_failed_launch_clears_owned_state_and_records_error(modules, monkeypatch):
    from types import SimpleNamespace

    manager, control, _, _, settings = modules
    settings.save({"server.port": 9234})
    monkeypatch.setattr(manager, "port_owner", lambda: "none")
    spawned = []

    def spawn(command, **kwargs):
        spawned.append(command)
        return SimpleNamespace(pid=99999999, poll=lambda: 1)

    def failed_wait(**kwargs):
        state = manager.read_state()
        assert state["port"] == 9234
        assert state["runtime_id"] == kwargs["runtime_id"]
        raise RuntimeError("The runtime did not become ready.")

    monkeypatch.setattr(manager.subprocess, "Popen", spawn)
    monkeypatch.setattr(manager, "_wait_for_ready", failed_wait)
    job = wait_job(control, control.start_runtime())
    assert job["status"] == "error"
    assert "did not become ready" in job["detail"]
    assert "--foreground" in spawned[0]
    assert not manager.state_path().exists()


def test_stale_start_clears_state_before_launch(modules, monkeypatch):
    manager, control, _, _, _ = modules
    manager.write_state({"runtime_id": "stale", "port": 8001, "host": "127.0.0.1"})
    monkeypatch.setattr(
        manager,
        "inspect_runtime",
        lambda: {"state": "stale", "metadata": manager.read_state()},
    )
    monkeypatch.setattr(manager, "port_owner", lambda: "none")

    def launch(**kwargs):
        assert not manager.state_path().exists()

    monkeypatch.setattr(manager, "start_background", launch)
    assert wait_job(control, control.start_runtime())["status"] == "done"


def test_overview_skips_port_probe_when_managed_and_ready(modules, monkeypatch):
    manager, _, _, setup, _ = modules
    monkeypatch.setattr(
        manager,
        "inspect_runtime",
        lambda: {"state": "ready", "managed": True, "metadata": {"port": 8001}},
    )
    monkeypatch.setattr(manager, "intended_address", lambda: ("127.0.0.1", 8001))
    monkeypatch.setattr(setup.client_operations, "list_agents", lambda *_: [])
    monkeypatch.setattr(setup, "_skills_installed", lambda: 0)
    monkeypatch.setattr(setup, "_project_step", lambda *_: {})

    def forbidden():
        pytest.fail("Ready overview must not probe the port")

    monkeypatch.setattr(manager, "port_owner", forbidden)
    with client_for(setup) as client:
        response = client.get("/api/connections/overview")
        assert response.status_code == 200
        assert response.json()["runtime"]["port_owner"] == "marm"


def test_stale_start_rechecks_new_saved_port_after_clearing_state(modules, monkeypatch):
    manager, control, _, _, settings = modules
    settings.save({"server.port": 9234})
    manager.write_state({"runtime_id": "stale", "port": 8001, "host": "127.0.0.1"})
    monkeypatch.setattr(
        manager,
        "inspect_runtime",
        lambda: (
            {"state": "stale", "metadata": manager.read_state()}
            if manager.read_state()
            else {"state": "stopped"}
        ),
    )
    monkeypatch.setattr(manager, "port_owner", lambda: "other")

    def forbidden(**kwargs):
        pytest.fail("The newly saved port is occupied")

    monkeypatch.setattr(manager, "start_background", forbidden)
    with pytest.raises(control.PortInUse, match="9234"):
        control.start_runtime()


def test_real_closed_port_is_free_and_overview_offers_start(modules, monkeypatch):
    manager, _, _, setup, settings = modules
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    settings.save({"server.port": port})
    assert manager.port_owner() == "none"
    monkeypatch.setattr(setup.client_operations, "list_agents", lambda *_: [])
    monkeypatch.setattr(setup, "_skills_installed", lambda: 0)
    with client_for(setup) as client:
        response = client.get("/api/connections/overview")
        assert response.status_code == 200
        assert response.json()["runtime"]["can_start"] is True
        assert response.json()["runtime"]["intended_port"] == port


def test_dead_state_ignores_an_occupied_old_port(modules, monkeypatch):
    manager, control, _, _, settings = modules
    with socket.socket() as old, socket.socket() as reserved:
        old.bind(("127.0.0.1", 0))
        old.listen()
        reserved.bind(("127.0.0.1", 0))
        new_port = reserved.getsockname()[1]
        reserved.close()
        settings.save({"server.port": new_port})
        manager.write_state(
            {
                "pid": 99999999,
                "process_created_at": 1,
                "runtime_id": "dead",
                "host": "127.0.0.1",
                "port": old.getsockname()[1],
            }
        )
        monkeypatch.setattr(manager, "request_runtime", lambda *args, **kwargs: None)
        assert manager.inspect_runtime()["state"] == "stale"
        assert manager.intended_address()[1] == new_port
        assert control._guard("start")["state"] == "stale"
        assert control._guard("restart")["state"] == "stale"


@pytest.mark.parametrize("state", [False, True])
def test_bad_port_values_do_not_crash_overview(modules, monkeypatch, state):
    manager, _, _, setup, _ = modules
    if state:
        manager.write_state({"pid": 99999999, "host": "127.0.0.1", "port": "garbage"})
    else:
        monkeypatch.setenv("SERVER_PORT", "garbage")
    monkeypatch.setattr(manager, "request_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "port_owner", lambda: "unknown")
    monkeypatch.setattr(setup.client_operations, "list_agents", lambda *_: [])
    monkeypatch.setattr(setup, "_skills_installed", lambda: 0)
    with client_for(setup) as client:
        assert client.get("/api/connections/overview").status_code == 200


def test_parallel_reservations_conflict_without_blocking_status_polls():
    jobs = importlib.import_module("marm_mcp_server.console.jobs")
    registry = jobs.JobRegistry("parallel", reject_different_kind=True)
    barrier = threading.Barrier(2)
    release = threading.Event()
    entered = threading.Event()
    registry.jobs["previous"] = {
        "job_id": "previous",
        "kind": "old",
        "_group": "other",
        "status": "done",
    }

    def validate():
        entered.set()
        barrier.wait(timeout=5)

    def work():
        release.wait(5)

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(registry.start, "start", "runtime", work, validate=validate)
        assert entered.wait(2)
        assert (
            pool.submit(registry.get, "previous").result(timeout=1)["status"] == "done"
        )
        second = pool.submit(registry.start, "stop", "runtime", work, validate=validate)
        try:
            outcomes = []
            for future in (first, second):
                try:
                    outcomes.append(future.result(timeout=2))
                except jobs.JobConflict:
                    outcomes.append("conflict")
            assert outcomes.count("conflict") == 1
            assert (
                len(
                    [
                        job
                        for job in registry.jobs.values()
                        if job["_group"] == "runtime"
                    ]
                )
                == 1
            )
        finally:
            release.set()


def test_managed_console_stop_terminates_only_runtime_and_clears_state(
    modules, monkeypatch
):
    manager, control, _, setup, settings = modules
    program = """
import json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({'pid': os.getpid(), 'runtime_id': 'stop-test'}).encode())
    def do_POST(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        threading.Thread(target=server.shutdown, daemon=True).start()
    def log_message(self, *args): pass
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
print(server.server_port, flush=True)
server.serve_forever()
server.server_close()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program], stdout=subprocess.PIPE, text=True
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            port = int(pool.submit(process.stdout.readline).result(timeout=5))
        settings.save({"server.port": port})
        state = manager.make_state(
            runtime_id="stop-test",
            profile="standard",
            rate_limit_rpm=None,
            pid=process.pid,
        )
        state.update(host="127.0.0.1", port=port)
        manager.write_state(state)
        monkeypatch.setattr(manager, "_headers", lambda: {"Accept": "application/json"})

        def forbidden():
            pytest.fail("Stop must leave the Console process alone")

        monkeypatch.setattr(manager, "stop_console", forbidden)
        with client_for(setup) as client:
            response = client.post("/api/connections/runtime/stop")
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            assert wait_job(control, job_id)["status"] == "done"
            assert (
                client.get(f"/api/connections/runtime/restart/{job_id}").status_code
                == 200
            )
        process.wait(timeout=3)
        assert manager.read_state() is None
        assert manager.port_owner() == "none"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        process.stdout.close()


def test_health_timeout_is_unknown_not_other(modules):
    manager, _, _, _, settings = modules

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(0.35)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.save({"server.port": server.server_port})
    try:
        assert manager.port_owner() == "unknown"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize("cleanup", [False, True])
def test_start_timeout_policy_is_console_opt_in(modules, monkeypatch, cleanup):
    manager, _, _, _, _ = modules
    original_spawn = subprocess.Popen
    children = []

    def spawn(command, **kwargs):
        child = original_spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
        )
        children.append(child)
        return child

    def timeout(**kwargs):
        raise RuntimeError("readiness timeout")

    monkeypatch.setattr(manager.subprocess, "Popen", spawn)
    monkeypatch.setattr(manager, "_wait_for_ready", timeout)
    try:
        with pytest.raises(RuntimeError, match="readiness timeout"):
            manager.start_background(cleanup_on_failure=cleanup)
        assert (children[0].poll() is not None) is cleanup
        assert (manager.read_state() is None) is cleanup
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
        manager.clear_state()
