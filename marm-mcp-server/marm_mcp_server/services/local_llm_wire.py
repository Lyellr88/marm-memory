from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Optional


def _host(url: str) -> Optional[str]:
    """The URL's host, or None when it has none or cannot be parsed.

    `urlparse` raises on some malformed input (`http://[::1`); every caller
    here must degrade to "no endpoint" rather than raise.
    """
    try:
        return urllib.parse.urlparse(url).hostname or None
    except ValueError:
        return None


def _is_loopback(url: str) -> bool:
    host = _host(url) or ""
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _Deadline:
    """Cut a request's socket at a monotonic instant, headers included.

    A socket timeout fires only on silence, so a server that keeps sending
    bytes, even one header byte at a time, would otherwise hold the call past
    the caller's limit. The timer is armed before connecting, and the
    connection hands over its socket as soon as it has one.
    """

    def __init__(self, deadline: Optional[float]) -> None:
        self.deadline = deadline
        self.fired = False
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    def __enter__(self) -> "_Deadline":
        if self.deadline is not None:
            delay = max(0.0, self.deadline - time.monotonic())
            self._timer = threading.Timer(delay, self._cut)
            self._timer.daemon = True
            self._timer.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._timer is not None:
            self._timer.cancel()

    def _shut(self, sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _cut(self) -> None:
        with self._lock:
            self.fired = True
            sock = self._sock
        if sock is not None:
            self._shut(sock)

    def _attach(self, sock: socket.socket) -> None:
        with self._lock:
            self._sock = sock
            fired = self.fired
        if fired:
            self._shut(sock)

    def open(self, request: urllib.request.Request, timeout: float) -> Any:
        if self.deadline is None:
            return urllib.request.urlopen(request, timeout=timeout)
        watch = self

        class _Conn(http.client.HTTPConnection):
            def connect(self) -> None:
                super().connect()
                watch._attach(self.sock)

        class _TlsConn(http.client.HTTPSConnection):
            def connect(self) -> None:
                super().connect()
                watch._attach(self.sock)

        class _Http(urllib.request.HTTPHandler):
            def http_open(self, req: Any) -> Any:
                return self.do_open(_Conn, req)

        class _Https(urllib.request.HTTPSHandler):
            def https_open(self, req: Any) -> Any:
                return self.do_open(_TlsConn, req)

        opener = urllib.request.build_opener(_Http, _Https)
        return opener.open(request, timeout=timeout)


def _within(timeout: float, deadline: Optional[float]) -> float:
    if deadline is None:
        return timeout
    return max(0.001, min(timeout, deadline - time.monotonic()))


def _first_json_value(text: str) -> Optional[Any]:
    """Recover the first JSON object or array embedded in `text`."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1] if "```" in stripped[3:] else stripped[3:]
        if stripped.lstrip().lower().startswith("json"):
            stripped = stripped.lstrip()[4:]
    try:
        return json.loads(stripped)
    except ValueError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char in "[{":
            try:
                value, _ = decoder.raw_decode(stripped[index:])
                return value
            except ValueError:
                continue
    return None
