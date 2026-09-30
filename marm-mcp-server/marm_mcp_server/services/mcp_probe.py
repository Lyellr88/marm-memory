"""Real MCP handshakes for the Console's Test connection button.

MARM speaks the legacy `initialize` handshake, so the probe does too. A probe
never raises: every failure comes back as a result with a plain error kind.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from typing import Any

import httpx

from ..config.settings import SERVER_VERSION
from ..utils.subprocess_flags import no_window_flags

PROTOCOL_VERSION = "2025-06-18"
HTTP_TIMEOUT = 5.0
STDIO_TIMEOUT = 30.0


class _ProbeError(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def _result(
    transport: str, started: float, tools: int = 0, error: _ProbeError | None = None
) -> dict[str, Any]:
    return {
        "ok": error is None,
        "transport": transport,
        "tools": tools,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "error": {"kind": error.kind, "detail": error.detail} if error else None,
    }


def _initialize_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "marm-console", "version": SERVER_VERSION},
        },
    }


def _rpc_result(message: Any, method: str) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise _ProbeError("protocol", f"{method} returned an unexpected message.")
    if "error" in message:
        error = message["error"]
        text = error.get("message") if isinstance(error, dict) else None
        raise _ProbeError("protocol", f"{method} failed: {text or 'server error'}")
    result = message.get("result")
    if not isinstance(result, dict):
        raise _ProbeError("protocol", f"{method} returned no result.")
    return result


def _tool_count(result: dict[str, Any]) -> int:
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise _ProbeError("protocol", "tools/list returned no tools array.")
    return len(tools)


def _sse_message(text: str, request_id: int) -> Any:
    """Pick the JSON-RPC message with the matching id out of an SSE body."""
    events: list[list[str]] = [[]]
    for line in text.splitlines():
        if not line.strip():
            events.append([])
        elif line.startswith("data:"):
            events[-1].append(line[5:].lstrip())
    for data in events:
        if not data:
            continue
        try:
            message = json.loads("\n".join(data))
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
    return None


def _http_message(response: httpx.Response, request_id: int, method: str) -> Any:
    if "text/event-stream" in response.headers.get("content-type", ""):
        message = _sse_message(response.text, request_id)
        if message is None:
            raise _ProbeError("protocol", f"{method} sent no matching event.")
        return message
    try:
        message = response.json()
    except ValueError as exc:
        raise _ProbeError("protocol", f"{method} did not return JSON.") from exc
    if isinstance(message, list):
        message = next(
            (m for m in message if isinstance(m, dict) and m.get("id") == request_id),
            None,
        )
    return message


def _check_status(response: httpx.Response, method: str) -> None:
    if response.status_code in (401, 403):
        raise _ProbeError(
            "unauthorized", f"The server rejected the key ({response.status_code})."
        )
    if response.status_code >= 400:
        raise _ProbeError("protocol", f"{method} returned HTTP {response.status_code}.")


def _redact(text: str, headers: dict[str, str]) -> str:
    for value in headers.values():
        for token in value.split():
            if len(token) > 6:
                text = text.replace(token, "***")
    return text


def probe_http(
    url: str, headers: dict[str, str] | None = None, timeout: float = HTTP_TIMEOUT
) -> dict[str, Any]:
    started = time.monotonic()
    base = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **(headers or {}),
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.post(url, headers=base, json=_initialize_request())
            _check_status(response, "initialize")
            init = _rpc_result(_http_message(response, 1, "initialize"), "initialize")
            follow = {
                **base,
                "MCP-Protocol-Version": str(
                    init.get("protocolVersion") or PROTOCOL_VERSION
                ),
            }
            session_id = response.headers.get("mcp-session-id")
            if session_id:
                follow["Mcp-Session-Id"] = session_id
            sent = client.post(
                url,
                headers=follow,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            _check_status(sent, "notifications/initialized")
            listed = client.post(
                url,
                headers=follow,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            )
            _check_status(listed, "tools/list")
            count = _tool_count(
                _rpc_result(_http_message(listed, 2, "tools/list"), "tools/list")
            )
    except _ProbeError as exc:
        exc.detail = _redact(exc.detail, base)
        return _result("http", started, error=exc)
    except httpx.TimeoutException:
        return _result(
            "http",
            started,
            error=_ProbeError("timeout", f"No answer within {timeout:g}s."),
        )
    except httpx.ConnectError:
        return _result(
            "http",
            started,
            error=_ProbeError("refused", "Could not connect to the server."),
        )
    except httpx.HTTPError as exc:
        return _result(
            "http",
            started,
            error=_ProbeError(
                "protocol", _redact(str(exc) or type(exc).__name__, base)
            ),
        )
    return _result("http", started, tools=count)


def _reader(pipe: Any, lines: queue.Queue[bytes]) -> None:
    for line in iter(pipe.readline, b""):
        lines.put(line)
    lines.put(b"")


def _await_response(
    lines: queue.Queue[bytes], request_id: int, deadline: float, method: str
) -> dict[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _ProbeError("timeout", f"No answer to {method} in time.")
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            continue
        if not line:
            raise _ProbeError(
                "protocol", f"The server exited before answering {method}."
            )
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return _rpc_result(message, method)


def _stop(proc: subprocess.Popen[bytes], reader: threading.Thread) -> None:
    """Stop the child for certain; a blocked reader is never closed from under itself."""
    if proc.stdin is not None:
        try:
            proc.stdin.close()
        except OSError:
            pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    reader.join(timeout=2)
    if not reader.is_alive() and proc.stdout is not None:
        proc.stdout.close()


def probe_stdio(
    argv: list[str],
    env: dict[str, str] | None = None,
    timeout: float = STDIO_TIMEOUT,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            shell=False,
            creationflags=no_window_flags(),
        )
    except (OSError, ValueError) as exc:
        detail = getattr(exc, "strerror", None) or str(exc)
        return _result("stdio", started, error=_ProbeError("spawn_failed", detail))
    lines: queue.Queue[bytes] = queue.Queue()
    assert proc.stdin is not None and proc.stdout is not None
    reader = threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True)
    reader.start()
    deadline = started + timeout

    def send(message: dict[str, Any]) -> None:
        assert proc.stdin is not None
        try:
            proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            proc.stdin.flush()
        except OSError as exc:
            raise _ProbeError(
                "protocol", "The server closed its input before the handshake finished."
            ) from exc

    try:
        send(_initialize_request())
        _await_response(lines, 1, deadline, "initialize")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        count = _tool_count(_await_response(lines, 2, deadline, "tools/list"))
    except _ProbeError as exc:
        return _result("stdio", started, error=exc)
    finally:
        _stop(proc, reader)
    return _result("stdio", started, tools=count)
