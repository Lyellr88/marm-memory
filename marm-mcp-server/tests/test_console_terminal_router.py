"""Security gates and WebSocket protocol tests for the terminal plugin."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_console_terminal_pty_session import IS_WINDOWS, echo_command

from marm_mcp_server.console import auth
from marm_mcp_server.console.terminal.pty_session import backend_status
from marm_mcp_server.console.terminal.router import (
    HOST_ENV,
    SESSION_COOKIE,
    TERMINAL_ENV,
    registry,
    router,
    terminal_availability,
)

BACKEND = backend_status()
requires_backend = pytest.mark.skipif(
    not BACKEND.available, reason=f"No PTY backend available: {BACKEND.reason}"
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def authed(client: TestClient) -> TestClient:
    client.cookies.set(SESSION_COOKIE, auth.create_browser_session())
    return client


@pytest.fixture
def enabled_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TERMINAL_ENV, "1")
    monkeypatch.setenv(HOST_ENV, "127.0.0.1")
    monkeypatch.delenv("MARM_IN_DOCKER", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)


def test_terminal_is_unavailable_unless_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TERMINAL_ENV, raising=False)
    availability = terminal_availability()
    assert availability.available is False
    assert TERMINAL_ENV in availability.reason
    for value in ("0", "", "false", "no", "off", "maybe"):
        monkeypatch.setenv(TERMINAL_ENV, value)
        assert terminal_availability().available is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_recognized_opt_in_values_pass_the_enable_gate(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(TERMINAL_ENV, value)
    monkeypatch.setenv(HOST_ENV, "127.0.0.1")
    assert terminal_availability().reason != (
        f"Terminal is disabled. Set {TERMINAL_ENV}=1 to enable it."
    )


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "::", "[::]", "192.168.1.50", "10.0.0.4", "example.local", ""]
)
def test_non_loopback_bind_refuses_even_when_enabled(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setenv(TERMINAL_ENV, "1")
    monkeypatch.setenv(HOST_ENV, host)
    availability = terminal_availability()
    assert availability.available is False
    assert "loopback" in availability.reason


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "localhost", "::1", "[::1]", "127.0.0.5"]
)
def test_loopback_binds_pass_the_host_gate(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setenv(TERMINAL_ENV, "1")
    monkeypatch.setenv(HOST_ENV, host)
    assert "loopback" not in terminal_availability().reason


def test_container_execution_reports_unavailable(
    monkeypatch: pytest.MonkeyPatch, enabled_loopback: None
) -> None:
    monkeypatch.setenv("MARM_IN_DOCKER", "1")
    availability = terminal_availability()
    assert availability.available is False
    assert "container" in availability.reason.lower()


def test_status_endpoint_mirrors_the_availability_gates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(TERMINAL_ENV, raising=False)
    payload = client.get("/api/terminal/status").json()
    assert payload["available"] is False
    assert payload["backend"] == "none"
    assert TERMINAL_ENV in payload["reason"]

    monkeypatch.setenv(TERMINAL_ENV, "1")
    monkeypatch.setenv(HOST_ENV, "127.0.0.1")
    payload = client.get("/api/terminal/status").json()
    assert payload["available"] is BACKEND.available
    assert payload["backend"] == ("conpty" if IS_WINDOWS else "posix-pty")


def test_websocket_admits_keyless_loopback_without_a_session(
    client: TestClient, enabled_loopback: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No MARM_API_KEY configured mirrors console_api_auth's own loopback
    exception -- the common local dev setup, where nothing ever calls
    /api/auth/bootstrap, must still be able to open a terminal."""
    monkeypatch.delenv("MARM_API_KEY", raising=False)
    with client.websocket_connect("/api/terminal/ws") as ws:
        ws.close()


def test_websocket_requires_a_browser_session_when_a_key_is_configured(
    client: TestClient, enabled_loopback: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MARM_API_KEY", "test-key")
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/terminal/ws"),
    ):
        pass


def test_websocket_refuses_when_the_terminal_is_disabled(
    authed: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(TERMINAL_ENV, raising=False)
    with (
        pytest.raises(WebSocketDisconnect),
        authed.websocket_connect("/api/terminal/ws"),
    ):
        pass


def test_websocket_refuses_a_non_loopback_bind(
    authed: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(TERMINAL_ENV, "1")
    monkeypatch.setenv(HOST_ENV, "0.0.0.0")
    with (
        pytest.raises(WebSocketDisconnect),
        authed.websocket_connect("/api/terminal/ws"),
    ):
        pass


def _drain(socket, predicate, timeout: float = 30.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    seen: list[dict] = []
    while time.monotonic() < deadline:
        event = socket.receive_json()
        seen.append(event)
        if predicate(seen):
            return seen
    raise AssertionError(f"condition never met. Saw: {[e['type'] for e in seen]}")


@requires_backend
def test_websocket_spawn_write_resize_and_kill_round_trip(
    authed: TestClient, enabled_loopback: None
) -> None:
    before = len(registry)
    with authed.websocket_connect("/api/terminal/ws") as socket:
        socket.send_json({"type": "spawn", "cols": 80, "rows": 24, "useProfile": False})
        first = socket.receive_json()
        assert first["type"] == "status"
        assert first["state"] == "running"
        session_id = first["sessionId"]
        assert registry.get(session_id) is not None

        socket.send_json({"type": "resize", "cols": 120, "rows": 40})
        socket.send_json({"type": "input", "data": echo_command("MARM", "_WS_OK")})

        def saw_marker(events: list[dict]) -> bool:
            body = "".join(e.get("data", "") for e in events if e["type"] == "data")
            return "MARM_WS_OK" in body

        _drain(socket, saw_marker)

        socket.send_json({"type": "kill"})
        events = _drain(socket, lambda seen: seen[-1]["type"] == "exit")
        assert events[-1]["sessionId"] == session_id
        assert "code" in events[-1]
    time.sleep(0.2)
    assert len(registry) == before


@requires_backend
def test_websocket_rejects_input_before_a_session_exists(
    authed: TestClient, enabled_loopback: None
) -> None:
    with authed.websocket_connect("/api/terminal/ws") as socket:
        socket.send_json({"type": "input", "data": "whoami\r\n"})
        event = socket.receive_json()
        assert event["type"] == "status"
        assert event["state"] == "error"
        assert "No session" in event["message"]


@requires_backend
def test_websocket_reports_a_bad_shell_without_closing(
    authed: TestClient, enabled_loopback: None
) -> None:
    with authed.websocket_connect("/api/terminal/ws") as socket:
        socket.send_json({"type": "spawn", "shell": "definitely-not-a-shell-xyz"})
        event = socket.receive_json()
        assert event["state"] == "error"
        assert "Shell not found" in event["message"]
        socket.send_json({"type": "spawn", "useProfile": False})
        running = socket.receive_json()
        assert running["state"] == "running"
        socket.send_json({"type": "kill"})
        _drain(socket, lambda seen: seen[-1]["type"] == "exit")


@requires_backend
def test_websocket_disconnect_detaches_instead_of_killing(
    authed: TestClient, enabled_loopback: None
) -> None:
    """A page refresh drops the socket but must not kill a running shell --
    that's the whole point of reattach."""
    with authed.websocket_connect("/api/terminal/ws") as socket:
        socket.send_json({"type": "spawn", "useProfile": False})
        running = socket.receive_json()
        session_id = running["sessionId"]
        session = registry.get(session_id)
        assert session is not None
    assert not session.wait_closed(2), "disconnect killed the session"
    assert registry.get(session_id) is session
    session.kill()
    assert session.wait_closed(20)


def test_cross_origin_handshake_is_refused(
    authed: TestClient, enabled_loopback: None
) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        authed.websocket_connect(
            "/api/terminal/ws", headers={"origin": "http://evil.example"}
        ),
    ):
        pass


@requires_backend
def test_console_own_origin_is_accepted(
    authed: TestClient, enabled_loopback: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MARM_CONSOLE_PORT", "8002")
    with authed.websocket_connect(
        "/api/terminal/ws", headers={"origin": "http://127.0.0.1:8002"}
    ) as socket:
        socket.send_json({"type": "spawn", "useProfile": False})
        assert socket.receive_json()["state"] == "running"
        socket.send_json({"type": "kill"})
        _drain(socket, lambda seen: seen[-1]["type"] == "exit")


@requires_backend
def test_check_dependency_reports_a_real_command(
    client: TestClient, enabled_loopback: None
) -> None:
    response = client.post("/api/terminal/check", json={"command": "echo hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "hello" in body["output"]


@requires_backend
def test_check_dependency_reports_a_missing_command(
    client: TestClient, enabled_loopback: None
) -> None:
    response = client.post(
        "/api/terminal/check", json={"command": "definitely-not-a-real-command-xyz"}
    )
    assert response.status_code == 200
    assert response.json()["success"] is False


def test_check_dependency_respects_the_enable_gate(client: TestClient) -> None:
    response = client.post("/api/terminal/check", json={"command": "echo hi"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert TERMINAL_ENV in body["output"]


@requires_backend
def test_reattach_replays_buffered_output_after_a_reconnect(
    authed: TestClient, enabled_loopback: None
) -> None:
    marker_head, marker_tail = "reattach", "42"

    with authed.websocket_connect("/api/terminal/ws") as socket:
        socket.send_json({"type": "spawn", "useProfile": False})
        session_id = socket.receive_json()["sessionId"]
        socket.send_json(
            {"type": "input", "data": echo_command(marker_head, marker_tail)}
        )
        _drain(
            socket,
            lambda seen: (
                marker_head + marker_tail
                in "".join(e.get("data", "") for e in seen if e["type"] == "data")
            ),
        )

    with authed.websocket_connect("/api/terminal/ws") as socket:
        socket.send_json({"type": "attach", "sessionId": session_id})
        events = _drain(
            socket,
            lambda seen: (
                marker_head + marker_tail
                in "".join(e.get("data", "") for e in seen if e["type"] == "data")
            ),
        )
        replayed = "".join(e.get("data", "") for e in events if e["type"] == "data")
        assert marker_head + marker_tail in replayed

        session = registry.get(session_id)
        assert session is not None
        socket.send_json({"type": "kill"})
        _drain(socket, lambda seen: seen[-1]["type"] == "exit")
    assert session.wait_closed(20)


@requires_backend
def test_attach_to_an_unknown_session_errors_cleanly(
    authed: TestClient, enabled_loopback: None
) -> None:
    with authed.websocket_connect("/api/terminal/ws") as socket:
        socket.send_json({"type": "attach", "sessionId": "not-a-real-session-id"})
        response = socket.receive_json()
        assert response["type"] == "status"
        assert response["state"] == "error"

        # The connection stays usable afterward -- the frontend's documented
        # fallback is a normal spawn on the same socket.
        socket.send_json({"type": "spawn", "useProfile": False})
        assert socket.receive_json()["state"] == "running"
        socket.send_json({"type": "kill"})
        _drain(socket, lambda seen: seen[-1]["type"] == "exit")


@requires_backend
def test_sweep_expired_kills_a_detached_session_past_the_grace_period(
    authed: TestClient, enabled_loopback: None
) -> None:
    with authed.websocket_connect("/api/terminal/ws") as socket:
        socket.send_json({"type": "spawn", "useProfile": False})
        session_id = socket.receive_json()["sessionId"]

    session = registry.get(session_id)
    assert session is not None

    not_yet_expired = registry.sweep_expired(1000.0)
    assert session not in not_yet_expired
    assert registry.get(session_id) is session

    time.sleep(0.05)
    expired = registry.sweep_expired(0.01)
    assert session in expired
    assert registry.get(session_id) is None

    for leftover in expired:
        leftover.kill()
    assert session.wait_closed(20)
