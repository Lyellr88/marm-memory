"""Session registry and PTY command types for the MARM Console terminal plugin."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from .pty_session import TerminalSession


@dataclass(frozen=True)
class Write:
    data: str


@dataclass(frozen=True)
class Resize:
    cols: int
    rows: int


@dataclass(frozen=True)
class Kill:
    pass


PtyCommand = Union[Write, Resize, Kill]


class TerminalRegistry:
    """Maps session ids to live PTY sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._detached_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, session: TerminalSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> TerminalSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> TerminalSession | None:
        with self._lock:
            self._detached_at.pop(session_id, None)
            return self._sessions.pop(session_id, None)

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._sessions)

    def mark_detached(self, session_id: str) -> None:
        """Record when a still-running session lost its last attached client."""
        with self._lock:
            if session_id in self._sessions:
                self._detached_at[session_id] = time.monotonic()

    def mark_attached(self, session_id: str) -> None:
        with self._lock:
            self._detached_at.pop(session_id, None)

    def sweep_expired(self, grace_seconds: float) -> list[TerminalSession]:
        """Pop and return every session detached longer than `grace_seconds`.

        The caller owns killing the returned sessions; this only removes them
        from the registry so nothing can attach to one mid-teardown."""
        cutoff = time.monotonic() - grace_seconds
        expired: list[TerminalSession] = []
        with self._lock:
            for session_id, detached_at in list(self._detached_at.items()):
                if detached_at > cutoff:
                    continue
                session = self._sessions.pop(session_id, None)
                self._detached_at.pop(session_id, None)
                if session is not None:
                    expired.append(session)
        return expired

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
