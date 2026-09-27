"""A deadline is wall-clock time, not socket silence.

A socket timeout fires only when nothing arrives, so a server that keeps
sending bytes can hold a call open indefinitely. These run a real loopback
server that trickles and never finishes.
"""

import http.server
import threading
import time

import pytest

from marm_mcp_server.services import local_llm


class _Trickle(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        chunk = (
            b'data: {"choices":[{"delta":{"content":"x "},"finish_reason":null}]}\n\n'
        )
        try:
            for _ in range(400):
                self.wfile.write(chunk)
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass


@pytest.fixture
def trickling(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Trickle)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setattr(local_llm, "endpoint", lambda: base)
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "m")
    yield
    server.shutdown()


def test_a_trickling_stream_stops_at_the_deadline(trickling):
    finished: dict = {}
    started = time.monotonic()
    pieces = list(
        local_llm.stream(
            "s", "u", timeout=5.0, deadline=started + 0.4, finished=finished
        )
    )
    assert time.monotonic() - started < 1.5, "ran past its deadline"
    assert pieces, "it did receive text before the deadline"
    assert finished["reason"] == "deadline"


def test_a_trickling_completion_stops_at_the_deadline(trickling):
    finished: dict = {}
    started = time.monotonic()
    text = local_llm.complete(
        "s", "u", timeout=5.0, deadline=started + 0.4, finished=finished
    )
    assert time.monotonic() - started < 1.5, "ran past its deadline"
    assert text is None
    assert finished["reason"] == "deadline"


def test_a_stream_that_fails_says_so(monkeypatch):
    """A dropped connection is not a finished answer."""
    monkeypatch.setattr(local_llm, "endpoint", lambda: "http://127.0.0.1:9")
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "m")
    finished: dict = {}
    assert list(local_llm.stream("s", "u", timeout=1.0, finished=finished)) == []
    assert finished["reason"] == "error"
