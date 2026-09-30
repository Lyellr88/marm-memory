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


@pytest.fixture
def trickling_headers(monkeypatch):
    """A peer that never finishes its headers, one byte at a time."""
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    stop = threading.Event()

    def serve():
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            try:
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                for _ in range(400):
                    conn.sendall(b"a")
                    time.sleep(0.05)
            except OSError:
                pass
            finally:
                conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{listener.getsockname()[1]}"
    monkeypatch.setattr(local_llm, "endpoint", lambda: base)
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "m")
    yield
    stop.set()
    listener.close()


def test_a_completion_stuck_in_its_headers_stops_at_the_deadline(trickling_headers):
    finished: dict = {}
    started = time.monotonic()
    assert (
        local_llm.complete(
            "s", "u", timeout=5.0, deadline=started + 0.4, finished=finished
        )
        is None
    )
    assert time.monotonic() - started < 1.5, "header parsing ran past the deadline"
    assert finished["reason"] == "deadline"


def test_a_stream_stuck_in_its_headers_stops_at_the_deadline(trickling_headers):
    finished: dict = {}
    started = time.monotonic()
    list(
        local_llm.stream(
            "s", "u", timeout=5.0, deadline=started + 0.4, finished=finished
        )
    )
    assert time.monotonic() - started < 1.5, "header parsing ran past the deadline"
    assert finished["reason"] == "deadline"


@pytest.fixture
def trickling_handshake(monkeypatch):
    """A TLS peer that never finishes its handshake, one byte at a time: a
    record header announcing 16 KiB, then the body a byte at a time."""
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    stop = threading.Event()

    def serve():
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            try:
                conn.recv(65536)
                conn.sendall(b"\x16\x03\x03\x40\x00")
                for _ in range(400):
                    conn.sendall(b"\x00")
                    time.sleep(0.05)
            except OSError:
                pass
            finally:
                conn.close()

    threading.Thread(target=serve, daemon=True).start()
    base = f"https://127.0.0.1:{listener.getsockname()[1]}"
    monkeypatch.setattr(local_llm, "endpoint", lambda: base)
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "m")
    yield
    stop.set()
    listener.close()


def test_a_tls_handshake_that_trickles_stops_at_the_deadline(trickling_handshake):
    finished: dict = {}
    started = time.monotonic()
    local_llm.complete("s", "u", timeout=5.0, deadline=started + 0.4, finished=finished)
    assert time.monotonic() - started < 1.5, "the TLS handshake ran past the deadline"
    assert finished["reason"] == "deadline"
