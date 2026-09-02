"""Self-contained WebSocket terminal plugin for MARM Console."""

from .pty_session import BackendStatus, TerminalSession, backend_status
from .router import Availability, registry, router, terminal_availability
from .state import Kill, Resize, TerminalRegistry, Write

__all__ = [
    "Availability",
    "BackendStatus",
    "Kill",
    "Resize",
    "TerminalRegistry",
    "TerminalSession",
    "Write",
    "backend_status",
    "registry",
    "router",
    "terminal_availability",
]
