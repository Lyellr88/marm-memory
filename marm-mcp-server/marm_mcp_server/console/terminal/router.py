"""WebSocket terminal router for MARM Console."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import auth
from .pty_session import (
    DEFAULT_COLS,
    DEFAULT_ROWS,
    TerminalSession,
    backend_status,
    default_cwd,
    default_shell,
)
from .state import TerminalRegistry

TERMINAL_ENV = "MARM_CONSOLE_TERMINAL"
HOST_ENV = "MARM_CONSOLE_HOST"
PORT_ENV = "MARM_CONSOLE_PORT"
ORIGINS_ENV = "MARM_CONSOLE_ALLOWED_ORIGINS"
SESSION_COOKIE = "marm_console_session"
_TRUTHY = {"1", "true", "yes", "on"}
_CLOSE_POLICY = 1008

# A refresh should not kill the shell underneath it, but a browser tab left
# open and forgotten should not pin a process forever either.
DETACHED_SESSION_GRACE_SECONDS = 600.0
_SWEEP_INTERVAL_SECONDS = 60.0

router = APIRouter()
registry = TerminalRegistry()


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str
    backend: str
    shell: str | None

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "backend": self.backend,
            "shell": self.shell,
        }


def _enabled() -> bool:
    return os.environ.get(TERMINAL_ENV, "").strip().lower() in _TRUTHY


def _bind_host() -> str:
    return os.environ.get(HOST_ENV, "127.0.0.1").strip().strip("[]")


def _loopback_only() -> bool:
    """A browser terminal on a reachable interface is remote code execution for the network."""
    host = _bind_host()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def allowed_origins() -> set[str]:
    configured = os.environ.get(ORIGINS_ENV, "")
    origins = {value.strip() for value in configured.split(",") if value.strip()}
    if not origins:
        origins = {"http://127.0.0.1:5173", "http://localhost:5173"}
    port = os.environ.get(PORT_ENV, "8002").strip() or "8002"
    origins.update({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})
    return origins


def origin_allowed(origin: str | None) -> bool:
    """CORS never covers WebSockets, so the handshake checks Origin itself."""
    return origin is None or origin in allowed_origins()


def _configured_api_key() -> str:
    api_key = os.environ.get("MARM_API_KEY", "")
    if api_key:
        return api_key
    from ...config.settings import MARM_API_KEY

    return MARM_API_KEY


def _authorized(websocket: WebSocket) -> bool:
    """Mirror console_api_auth's policy for the WebSocket handshake, which
    Starlette's BaseHTTPMiddleware never sees. A session cookie always works;
    otherwise fall back to the same keyless-loopback and bearer-key rules the
    rest of the console's /api/ routes already apply."""
    if auth.valid_browser_session(websocket.cookies.get(SESSION_COOKIE)):
        return True
    api_key = _configured_api_key()
    if not api_key:
        client = websocket.client.host if websocket.client else ""
        return client in {"127.0.0.1", "::1", "localhost", "testclient"}
    auth_header = websocket.headers.get("authorization", "")
    return auth_header.startswith("Bearer ") and secrets.compare_digest(
        auth_header[7:], api_key
    )


def terminal_availability() -> Availability:
    if not _enabled():
        return Availability(
            False,
            f"Terminal is disabled. Set {TERMINAL_ENV}=1 to enable it.",
            "none",
            None,
        )
    if not _loopback_only():
        return Availability(
            False,
            f"Terminal refuses to run while {HOST_ENV} is {_bind_host() or '(unset)'}; loopback binding is required.",
            "none",
            None,
        )
    status = backend_status()
    return Availability(status.available, status.reason, status.backend, status.shell)


@router.get("/api/terminal/status")
def terminal_status() -> dict:
    return terminal_availability().as_dict()


class DependencyCheckRequest(BaseModel):
    command: str


_CHECK_TIMEOUT_SECONDS = 15


def _check_command_args(shell: str, command: str) -> list[str]:
    name = Path(shell).name.lower()
    if os.name == "nt":
        if name in {"pwsh", "pwsh.exe", "powershell", "powershell.exe"}:
            return [shell, "-NoLogo", "-NoProfile", "-Command", command]
        return [shell, "/c", command]
    return [shell, "-c", command]


@router.post("/api/terminal/check")
def check_dependency(req: DependencyCheckRequest) -> dict:
    """Run a command outside the interactive PTY stream and report its result.

    Used by the onboarding guide to check whether a tool (node, git, an agent
    CLI) is installed without needing to parse it out of live terminal output.
    """
    availability = terminal_availability()
    if not availability.available:
        return {"success": False, "output": availability.reason}

    shell = default_shell()
    if shell is None:
        return {"success": False, "output": "No shell available on this machine."}

    try:
        result = subprocess.run(
            _check_command_args(shell, req.command),
            capture_output=True,
            text=True,
            timeout=_CHECK_TIMEOUT_SECONDS,
            cwd=default_cwd(),
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": f"Command timed out after {_CHECK_TIMEOUT_SECONDS}s.",
        }
    except OSError as exc:
        return {"success": False, "output": str(exc)}

    output = (result.stdout + result.stderr).strip()
    return {"success": result.returncode == 0, "output": output}


async def _pump(websocket: WebSocket, events: asyncio.Queue[dict]) -> None:
    while True:
        event = await events.get()
        if event.get("type") == "exit":
            registry.remove(str(event.get("sessionId")))
        await websocket.send_json(event)


@router.websocket("/api/terminal/ws")
async def terminal_socket(websocket: WebSocket) -> None:
    if not origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=_CLOSE_POLICY, reason="Origin is not allowed.")
        return
    if not _authorized(websocket):
        await websocket.close(code=_CLOSE_POLICY, reason="Authentication required.")
        return
    availability = terminal_availability()
    if not availability.available:
        await websocket.close(code=_CLOSE_POLICY, reason=availability.reason[:120])
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()
    events: asyncio.Queue[dict] = asyncio.Queue()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(events.put_nowait, event)

    session: TerminalSession | None = None
    pump = asyncio.create_task(_pump(websocket, events))
    try:
        while True:
            try:
                message = await websocket.receive_json()
            except (ValueError, TypeError):
                await websocket.send_json(_error(None, "Malformed message."))
                continue
            if not isinstance(message, dict):
                await websocket.send_json(_error(None, "Malformed message."))
                continue
            kind = message.get("type")
            if kind == "spawn":
                if session is not None and not session.finished():
                    await websocket.send_json(
                        _error(session.session_id, "A session is already running.")
                    )
                    continue
                try:
                    session = await asyncio.to_thread(
                        TerminalSession.spawn,
                        emit=emit,
                        shell=message.get("shell"),
                        cwd=message.get("cwd"),
                        cols=int(message.get("cols", DEFAULT_COLS)),
                        rows=int(message.get("rows", DEFAULT_ROWS)),
                        use_profile=bool(message.get("useProfile", True)),
                        on_start=registry.add,
                    )
                except (RuntimeError, OSError, ValueError) as exc:
                    session = None
                    await websocket.send_json(_error(None, str(exc)))
                    continue
            elif kind == "attach":
                if session is not None and not session.finished():
                    await websocket.send_json(
                        _error(session.session_id, "A session is already running.")
                    )
                    continue
                requested_id = str(message.get("sessionId", ""))
                candidate = await asyncio.to_thread(registry.get, requested_id)
                if candidate is None or candidate.finished():
                    await websocket.send_json(_error(None, "Session not found."))
                    continue
                session = candidate
                await asyncio.to_thread(session.attach, emit)
                registry.mark_attached(session.session_id)
                # Routed through the same queue as the buffer replay `attach`
                # just triggered, rather than sent directly, so this confirmation
                # can't race ahead of the scrollback it's confirming.
                events.put_nowait(
                    {
                        "type": "status",
                        "sessionId": session.session_id,
                        "state": "running",
                    }
                )
            elif session is None:
                await websocket.send_json(_error(None, "No session has been spawned."))
            elif kind == "input":
                session.write(str(message.get("data", "")))
            elif kind == "resize":
                session.resize(
                    int(message.get("cols", DEFAULT_COLS)),
                    int(message.get("rows", DEFAULT_ROWS)),
                )
            elif kind == "kill":
                session.kill()
            else:
                await websocket.send_json(
                    _error(session.session_id, f"Unknown message type: {kind!r}")
                )
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        if session is not None:
            if session.finished():
                registry.remove(session.session_id)
            else:
                # The connection dropped -- maybe a refresh -- but the shell
                # is still running. Leave it attachable until the sweep's
                # grace period expires rather than killing it outright.
                session.detach()
                registry.mark_detached(session.session_id)


async def _sweep_loop(interval_seconds: float, grace_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        if not _enabled():
            continue
        expired = await asyncio.to_thread(registry.sweep_expired, grace_seconds)
        for session in expired:
            session.kill()


def start_sweep(
    interval_seconds: float = _SWEEP_INTERVAL_SECONDS,
    grace_seconds: float = DETACHED_SESSION_GRACE_SECONDS,
) -> asyncio.Task:
    """A detached-but-still-running session outlives its WebSocket so a page
    refresh can reattach to it; this is what eventually kills one nobody
    reattached to. A no-op tick while the terminal is disabled."""
    return asyncio.get_running_loop().create_task(
        _sweep_loop(interval_seconds, grace_seconds)
    )


def _error(session_id: str | None, message: str) -> dict:
    return {
        "type": "status",
        "sessionId": session_id,
        "state": "error",
        "message": message,
    }
