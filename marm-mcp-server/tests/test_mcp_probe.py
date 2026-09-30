"""MCP probe against a real MARM HTTP app, a real STDIO server, and a protocol-speaking fake."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import uvicorn
from conftest import load_isolated_server

from marm_mcp_server.services import mcp_probe

SECRET = "sk-marm-probe-secret-value"
TOOL_COUNT = 16


def stdio_env(tmp_path) -> dict[str, str]:
    """Every path the server writes points into tmp so the real ~/.marm is never touched."""
    env = os.environ.copy()
    env.update(
        HOME=str(tmp_path),
        USERPROFILE=str(tmp_path),
        MARM_DB_PATH=str(tmp_path / "probe-memory.db"),
        MARM_ANALYTICS_DB_PATH=str(tmp_path / "probe-analytics.db"),
        MARM_SETTINGS_PATH=str(tmp_path / "settings.json"),
        MARM_SKIP_DOC_LOAD="1",
    )
    env.pop("MARM_API_KEY", None)
    return env


# --- Real MARM STDIO server -----------------------------------------------------------


@pytest.mark.slow_stdio
def test_probe_stdio_against_the_real_marm_stdio_server(tmp_path):
    result = mcp_probe.probe_stdio(
        [sys.executable, "-m", "marm_mcp_server.server_stdio"], stdio_env(tmp_path)
    )

    assert result["error"] is None
    assert result["ok"] is True
    assert result["transport"] == "stdio"
    assert result["tools"] == TOOL_COUNT
    assert result["latency_ms"] > 0


# --- Real MARM HTTP app served by uvicorn ------------------------------------------------


@pytest.fixture
def serve_marm(monkeypatch, tmp_path):
    """Serve a real, isolated MARM app on a free port; yields a start(api_key) factory."""
    running: list[tuple[uvicorn.Server, threading.Thread]] = []

    def start(api_key: str = "") -> str:
        monkeypatch.setenv("MARM_SETTINGS_PATH", str(tmp_path / "settings.json"))
        server = load_isolated_server(monkeypatch, tmp_path, api_key=api_key)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        config = uvicorn.Config(server.app, log_level="warning", lifespan="off")
        uvicorn_server = uvicorn.Server(config)
        uvicorn_server.install_signal_handlers = lambda: None
        thread = threading.Thread(
            target=uvicorn_server.run, kwargs={"sockets": [sock]}, daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 15
        while not uvicorn_server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert uvicorn_server.started, "uvicorn never started"
        running.append((uvicorn_server, thread))
        return f"http://127.0.0.1:{port}/mcp"

    yield start
    for uvicorn_server, thread in running:
        uvicorn_server.should_exit = True
        thread.join(timeout=15)


def test_probe_http_against_a_real_marm_app_without_a_key(serve_marm):
    url = serve_marm()

    result = mcp_probe.probe_http(url, {})

    assert result["error"] is None
    assert result["ok"] is True
    assert result["transport"] == "http"
    assert result["tools"] == TOOL_COUNT


def test_probe_http_against_a_real_marm_app_with_a_key(serve_marm):
    url = serve_marm(api_key=SECRET)

    good = mcp_probe.probe_http(url, {"Authorization": f"Bearer {SECRET}"})
    missing = mcp_probe.probe_http(url, {})
    wrong = mcp_probe.probe_http(url, {"Authorization": "Bearer sk-wrong-key-value"})

    assert good["ok"] is True
    assert good["tools"] == TOOL_COUNT
    for rejected in (missing, wrong):
        assert rejected["ok"] is False
        assert rejected["tools"] == 0
        assert rejected["error"]["kind"] == "unauthorized"
    assert SECRET not in json.dumps([good, missing, wrong])


# --- Protocol-speaking fake HTTP server ------------------------------------------------------


class FakeMcp:
    """A real HTTP server speaking the legacy handshake with JSON or SSE bodies."""

    def __init__(
        self,
        *,
        sse: bool = False,
        key: str | None = None,
        delay: float = 0.0,
        tools: int = 3,
        fail_method: str | None = None,
        session: bool = True,
    ) -> None:
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"headers": dict(self.headers), "body": body})
                if delay:
                    time.sleep(delay)
                if key and self.headers.get("Authorization") != f"Bearer {key}":
                    return self.reply(401, {"error": "Unauthorized"})
                method = body.get("method")
                if "id" not in body:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if method == fail_method:
                    return self.reply(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "id": body["id"],
                            "error": {"code": -32000, "message": "kaput"},
                        },
                    )
                if method == "initialize":
                    result = {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "serverInfo": {"name": "fake", "version": "0"},
                    }
                else:
                    result = {"tools": [{"name": f"t{i}"} for i in range(tools)]}
                self.reply(
                    200,
                    {"jsonrpc": "2.0", "id": body["id"], "result": result},
                    session=session and method == "initialize",
                )

            def reply(self, status: int, message: dict, session: bool = False) -> None:
                if sse and status == 200:
                    noise = {"jsonrpc": "2.0", "method": "notifications/message"}
                    text = (
                        f"event: message\ndata: {json.dumps(noise)}\n\n"
                        f"event: message\nid: 1\ndata: {json.dumps(message)}\n\n"
                    )
                    kind = "text/event-stream"
                else:
                    text, kind = json.dumps(message), "application/json"
                payload = text.encode()
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(payload)))
                if session:
                    self.send_header("Mcp-Session-Id", "session-123")
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> FakeMcp:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.mark.parametrize("sse", [False, True])
def test_probe_http_handshake_headers_and_body_formats(sse):
    with FakeMcp(sse=sse, key=SECRET, tools=5) as fake:
        result = mcp_probe.probe_http(fake.url, {"Authorization": f"Bearer {SECRET}"})

    assert result["ok"] is True
    assert result["tools"] == 5
    assert [r["body"].get("method") for r in fake.requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]
    first, second, third = (r["headers"] for r in fake.requests)
    init_params = fake.requests[0]["body"]["params"]
    assert init_params["protocolVersion"] == "2025-06-18"
    assert init_params["clientInfo"]["name"] == "marm-console"
    assert first["Accept"] == "application/json, text/event-stream"
    assert first["Content-Type"] == "application/json"
    assert "Mcp-Session-Id" not in first
    for later in (second, third):
        assert later["Mcp-Session-Id"] == "session-123"
        assert later["MCP-Protocol-Version"] == "2025-06-18"
        assert later["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in json.dumps(result)


def test_probe_http_works_without_a_session_id():
    with FakeMcp(session=False) as fake:
        result = mcp_probe.probe_http(fake.url, {})

    assert result["ok"] is True
    assert all("Mcp-Session-Id" not in r["headers"] for r in fake.requests)


def test_probe_http_401_is_unauthorized_and_never_echoes_the_key():
    with FakeMcp(key="sk-the-real-key-value") as fake:
        result = mcp_probe.probe_http(fake.url, {"Authorization": f"Bearer {SECRET}"})

    assert result["ok"] is False
    assert result["error"]["kind"] == "unauthorized"
    assert SECRET not in json.dumps(result)
    assert [r["body"].get("method") for r in fake.requests] == ["initialize"]


def test_probe_http_refused_when_nothing_listens():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    result = mcp_probe.probe_http(f"http://127.0.0.1:{port}/mcp", {})

    assert result["ok"] is False
    assert result["error"]["kind"] == "refused"


def test_probe_http_times_out_on_a_slow_server():
    with FakeMcp(delay=1.5) as fake:
        started = time.monotonic()
        result = mcp_probe.probe_http(fake.url, {}, timeout=0.3)

    assert result["error"]["kind"] == "timeout"
    assert time.monotonic() - started < 1.4


@pytest.mark.parametrize("method", ["initialize", "tools/list"])
def test_probe_http_json_rpc_error_is_a_protocol_error(method):
    with FakeMcp(fail_method=method) as fake:
        result = mcp_probe.probe_http(fake.url, {})

    assert result["ok"] is False
    assert result["error"]["kind"] == "protocol"
    assert "kaput" in result["error"]["detail"]


def test_probe_http_non_mcp_server_is_a_protocol_error():
    class Html(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            payload = b"<html>not mcp</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Html)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = mcp_probe.probe_http(
            f"http://127.0.0.1:{server.server_address[1]}/mcp", {}
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result["error"]["kind"] == "protocol"


# --- STDIO failure paths with real child processes ---------------------------------------------

ECHO_SERVER = (
    "import sys, json\n"
    "for line in sys.stdin:\n"
    "    msg = json.loads(line)\n"
    "    if 'id' not in msg: continue\n"
    "    if msg['method'] == 'initialize':\n"
    "        result = {'protocolVersion': '2025-06-18', 'capabilities': {}}\n"
    "    else:\n"
    "        result = {'tools': [{'name': 'a'}, {'name': 'b'}]}\n"
    "    print('not json noise', flush=True)\n"
    "    print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result}), flush=True)\n"
)


def test_probe_stdio_speaks_newline_delimited_json_rpc():
    result = mcp_probe.probe_stdio([sys.executable, "-c", ECHO_SERVER])

    assert result["ok"] is True
    assert result["tools"] == 2
    assert result["transport"] == "stdio"


def test_probe_stdio_spawn_failure(tmp_path):
    result = mcp_probe.probe_stdio([str(tmp_path / "no-such-binary")])

    assert result["ok"] is False
    assert result["error"]["kind"] == "spawn_failed"


def test_probe_stdio_child_that_exits_is_a_protocol_error():
    result = mcp_probe.probe_stdio([sys.executable, "-c", "pass"])

    assert result["ok"] is False
    assert result["error"]["kind"] == "protocol"


def test_probe_stdio_timeout_kills_the_child(monkeypatch):
    spawned: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    class Recording(real_popen):  # type: ignore[type-arg,misc]
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            spawned.append(self)

    monkeypatch.setattr(mcp_probe.subprocess, "Popen", Recording)
    started = time.monotonic()

    result = mcp_probe.probe_stdio(
        [sys.executable, "-c", "import time; time.sleep(60)"], timeout=1.0
    )

    assert result["ok"] is False
    assert result["error"]["kind"] == "timeout"
    assert time.monotonic() - started < 15
    assert len(spawned) == 1
    assert spawned[0].poll() is not None


def test_probe_stdio_success_also_leaves_no_child(monkeypatch):
    spawned: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    class Recording(real_popen):  # type: ignore[type-arg,misc]
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            spawned.append(self)

    monkeypatch.setattr(mcp_probe.subprocess, "Popen", Recording)

    result = mcp_probe.probe_stdio([sys.executable, "-c", ECHO_SERVER])

    assert result["ok"] is True
    assert spawned[0].poll() is not None
