"""Per-session MCP protocol-delivery tracking (TTL + max-sessions eviction)."""

import asyncio
import time
from collections import OrderedDict


_PROTOCOL_DELIVERY_MAX_SESSIONS = 4096
_PROTOCOL_DELIVERY_TTL_SECONDS = 24 * 60 * 60
_protocol_delivered_sessions: OrderedDict[str, float] = OrderedDict()
_protocol_delivery_lock = asyncio.Lock()
_PROTOCOL_LITE_INTERVAL = 30
_protocol_call_counts: dict[str, int] = {}
_PROTOCOL_CALL_COUNTS_MAX_SESSIONS = 4096


def _prune_call_counts() -> None:
    """Prune call counts to match delivered sessions.

    Removes entries for sessions that are no longer in
    _protocol_delivered_sessions (aged out by TTL or max-sessions cap).
    Also enforces hard cap when count grows too large.
    """
    # Prune sessions not in delivered set
    delivered = set(_protocol_delivered_sessions)
    stale = [k for k in _protocol_call_counts if k not in delivered]
    for k in stale:
        _protocol_call_counts.pop(k, None)
    # Hard cap as safety net
    if len(_protocol_call_counts) > _PROTOCOL_CALL_COUNTS_MAX_SESSIONS:
        excess = list(_protocol_call_counts.keys())[
            :-_PROTOCOL_CALL_COUNTS_MAX_SESSIONS
        ]
        for k in excess:
            _protocol_call_counts.pop(k, None)


def _protocol_session_delivered(session_name: str, now: float | None = None) -> bool:
    if not isinstance(_protocol_delivered_sessions, OrderedDict):
        return session_name in _protocol_delivered_sessions
    now = now or time.monotonic()
    _prune_protocol_delivered_sessions(now)
    return session_name in _protocol_delivered_sessions


def _mark_protocol_session_delivered(
    session_name: str, now: float | None = None
) -> None:
    if not isinstance(_protocol_delivered_sessions, OrderedDict):
        _protocol_delivered_sessions.add(session_name)
        return
    now = now or time.monotonic()
    _protocol_delivered_sessions[session_name] = now
    _protocol_delivered_sessions.move_to_end(session_name)
    _prune_protocol_delivered_sessions(now)


def _prune_protocol_delivered_sessions(now: float | None = None) -> None:
    if not isinstance(_protocol_delivered_sessions, OrderedDict):
        return
    now = now or time.monotonic()
    while _protocol_delivered_sessions:
        _, delivered_at = next(iter(_protocol_delivered_sessions.items()))
        if now - delivered_at <= _PROTOCOL_DELIVERY_TTL_SECONDS:
            break
        _protocol_delivered_sessions.popitem(last=False)
    while len(_protocol_delivered_sessions) > _PROTOCOL_DELIVERY_MAX_SESSIONS:
        _protocol_delivered_sessions.popitem(last=False)
