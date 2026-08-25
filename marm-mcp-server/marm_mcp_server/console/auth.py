from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path

_BOOTSTRAP_TTL_SECONDS = 60
_SESSION_TTL_SECONDS = 8 * 60 * 60
_BOOTSTRAP_FILE = "console-bootstrap.json"
_sessions: dict[str, float] = {}
_sessions_lock = threading.Lock()
_bootstrap_lock = threading.Lock()


def _bootstrap_path(runtime_directory: Path) -> Path:
    return runtime_directory / _BOOTSTRAP_FILE


def create_bootstrap_token(runtime_directory: Path) -> str:
    """Create a short-lived, single-use handoff for the local browser."""
    token = secrets.token_urlsafe(32)
    runtime_directory.mkdir(parents=True, exist_ok=True)
    path = _bootstrap_path(runtime_directory)
    path.write_text(
        json.dumps(
            {"token": token, "expires_at": time.time() + _BOOTSTRAP_TTL_SECONDS}
        ),
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def consume_bootstrap_token(runtime_directory: Path, token: str) -> bool:
    """Consume one valid token; expired and malformed handoffs are rejected."""
    path = _bootstrap_path(runtime_directory)
    with _bootstrap_lock:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        if not isinstance(payload, dict):
            return False
        expected = payload.get("token")
        expires_at = payload.get("expires_at")
        valid = (
            isinstance(expected, str)
            and isinstance(expires_at, (int, float))
            and time.time() <= expires_at
            and secrets.compare_digest(token, expected)
        )
        if not valid:
            return False
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return False
        return True


def create_browser_session() -> str:
    """Return an opaque server-held Console browser session token."""
    token = secrets.token_urlsafe(32)
    with _sessions_lock:
        now = time.time()
        _sessions.update(
            {value: expiry for value, expiry in _sessions.items() if expiry > now}
        )
        _sessions[token] = now + _SESSION_TTL_SECONDS
    return token


def valid_browser_session(token: str | None) -> bool:
    """Check a session without ever returning its credential."""
    if not token:
        return False
    with _sessions_lock:
        expires_at = _sessions.get(token)
        if expires_at is None or expires_at <= time.time():
            _sessions.pop(token, None)
            return False
    return True
