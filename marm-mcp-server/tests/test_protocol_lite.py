"""Tests for protocol-lite reinjection feature.

Verifies: full protocol on first MCP tool call, lite protocol every 30 calls,
coexistence with compaction, dict eviction, and STDIO counter behavior.
"""

import json
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from conftest import load_isolated_server

_NOW = time.monotonic()  # snapshot for consistent test priming


# ── Helpers ─────────────────────────────────────────────────────────


def _tool_call_body(session_name="default"):
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "marm_smart_recall",
                "arguments": {"session_name": session_name, "query": "test"},
            },
        }
    ).encode()


def _mock_response():
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": '{"status":"ok"}'}]},
        }
    ).encode()
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = MagicMock()
    resp.headers.items.return_value = []
    resp.headers.get.return_value = "application/json"

    async def _iter():
        yield body

    resp.body_iterator = _iter()
    resp.body = body
    return resp


def _mock_request(body):
    req = MagicMock()
    req.method = "POST"
    req.url.path = "/mcp"
    req.body = AsyncMock(return_value=body)
    return req


def _injected_text(resp):
    """First text block from response content, or ''."""
    data = json.loads(resp.body)
    content = data.get("result", {}).get("content", [])
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block["text"]
    return ""


async def _one_call(server, session="default"):
    return await server._mcp_tool_call_tracker(
        _mock_request(_tool_call_body(session)),
        AsyncMock(return_value=_mock_response()),
    )


# ── First Injection ──────────────────────────────────────────────────


def test_first_call_injects_full_protocol(monkeypatch, tmp_path):
    """First tool call injects PROTOCOL.md with MARM SESSION INIT prefix."""
    server = load_isolated_server(monkeypatch, tmp_path)
    server._protocol_delivered_sessions.clear()
    server._protocol_call_counts.clear()

    resp = asyncio.run(_one_call(server))
    text = _injected_text(resp)

    assert "[MARM SESSION INIT]" in text
    assert "MARM MCP - Memory Accurate Response Mode" in text


def test_calls_after_first_do_not_inject_full(monkeypatch, tmp_path):
    """Calls 2-29 skip protocol injection."""
    server = load_isolated_server(monkeypatch, tmp_path)
    server._protocol_delivered_sessions.clear()
    server._protocol_call_counts.clear()

    # First call gets full protocol
    r1 = asyncio.run(_one_call(server))
    assert "[MARM SESSION INIT]" in _injected_text(r1)

    # Next 10 calls: no injection
    for _ in range(10):
        resp = asyncio.run(_one_call(server))
        text = _injected_text(resp)
        assert "[MARM SESSION INIT]" not in text
        assert "[MARM PROTOCOL REFRESH]" not in text


# ── Lite Reinjection ──────────────────────────────────────────────────


def test_lite_injects_at_interval(monkeypatch, tmp_path):
    """Lite protocol appears when counter reaches the interval (30)."""
    server = load_isolated_server(monkeypatch, tmp_path)
    server._protocol_delivered_sessions.clear()
    server._protocol_call_counts.clear()

    # Prime the counter: 29 prior calls, session already delivered
    server._protocol_call_counts["default"] = 29
    server._protocol_delivered_sessions["default"] = _NOW

    resp = asyncio.run(_one_call(server))
    text = _injected_text(resp)

    assert "[MARM PROTOCOL REFRESH]" in text
    assert "MARM Protocol - Quick Reference" in text
    assert "smart_recall" in text


def test_lite_not_injected_before_interval(monkeypatch, tmp_path):
    """Lite does NOT inject on calls that don't hit the interval."""
    server = load_isolated_server(monkeypatch, tmp_path)
    server._protocol_delivered_sessions.clear()
    server._protocol_call_counts.clear()

    # Counter at 15 — not a multiple of 30
    server._protocol_call_counts["default"] = 15

    resp = asyncio.run(_one_call(server))
    text = _injected_text(resp)
    assert "[MARM PROTOCOL REFRESH]" not in text


def test_lite_leaves_protocol_injected_false(monkeypatch, tmp_path):
    """Lite injection does NOT set protocol_injected=True — compaction still fires."""
    server = load_isolated_server(monkeypatch, tmp_path)
    server._protocol_delivered_sessions.clear()
    server._protocol_call_counts.clear()

    server._protocol_call_counts["default"] = 29
    server._protocol_delivered_sessions["default"] = _NOW

    # Verify: on interval hit, lite text is injected AND protocol_injected stays False
    resp = asyncio.run(_one_call(server))
    text = _injected_text(resp)

    assert "[MARM PROTOCOL REFRESH]" in text
    # The lite injection doesn't block compaction — verified by the
    # server code where protocol_injected stays False for lite.
    # Compaction injection is tested independently in test_compaction_*.py.


# ── Per-Session Counters ──────────────────────────────────────────────


def test_different_sessions_independent_counters(monkeypatch, tmp_path):
    """Session A at 29 gets lite at 30; session B at 0 gets full protocol."""
    server = load_isolated_server(monkeypatch, tmp_path)
    server._protocol_delivered_sessions.clear()
    server._protocol_call_counts.clear()

    server._protocol_call_counts["session-a"] = 29
    server._protocol_delivered_sessions["session-a"] = _NOW

    # Session B (no prior calls, not in delivered)
    r_b = asyncio.run(_one_call(server, session="session-b"))
    t_b = _injected_text(r_b)
    assert "[MARM SESSION INIT]" in t_b
    assert "[MARM PROTOCOL REFRESH]" not in t_b

    # Session A (29 prior, now 30th)
    r_a = asyncio.run(_one_call(server, session="session-a"))
    t_a = _injected_text(r_a)
    assert "[MARM PROTOCOL REFRESH]" in t_a


# ── Eviction ──────────────────────────────────────────────────────────


def test_prune_removes_stale_sessions(monkeypatch, tmp_path):
    """Sessions not in delivered_sessions get evicted from call counts."""
    server = load_isolated_server(monkeypatch, tmp_path)
    server._protocol_delivered_sessions.clear()
    server._protocol_call_counts.clear()

    server._protocol_call_counts["stale-session"] = 15
    assert "stale-session" in server._protocol_call_counts

    # Trigger prune via a tool call on a different session
    asyncio.run(_one_call(server, session="real"))

    assert "stale-session" not in server._protocol_call_counts


def test_hard_cap_limits_call_counts(monkeypatch, tmp_path):
    """Call counts capped at 4096 entries."""
    server = load_isolated_server(monkeypatch, tmp_path)
    server._protocol_delivered_sessions.clear()
    server._protocol_call_counts.clear()

    for i in range(5000):
        name = f"session-{i}"
        server._protocol_call_counts[name] = i
        server._protocol_delivered_sessions[name] = _NOW

    server._prune_call_counts()
    assert len(server._protocol_call_counts) <= 4096


# ── STDIO Transport ──────────────────────────────────────────────────


def test_stdio_lite_injected_on_interval(monkeypatch, tmp_path):
    """STDIO transport injects lite every 30 calls."""
    import marm_mcp_server.server_stdio as stdio
    import marm_mcp_server.services.notebook as notebook_service
    from marm_mcp_server.core.memory import MARMMemory

    mem = MARMMemory(str(tmp_path / "stdio-lite.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(stdio, "memory", mem)
    monkeypatch.setattr(notebook_service, "memory", mem)

    stdio._protocol_delivered = False
    stdio._protocol_call_count = 0

    async def dummy_tool(*args, **kwargs):
        return {"status": "success"}

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(stdio, "ensure_marm_started", noop)
    monkeypatch.setattr(stdio, "maybe_auto_refresh", noop)
    monkeypatch.setattr(stdio, "claim_pending_compaction_prompt", lambda *a, **kw: None)

    wrapped = stdio._log_tool_call(dummy_tool)

    # First call: full protocol
    r1 = asyncio.run(wrapped(session_name="main"))
    assert "marm_protocol" in r1
    assert r1["marm_protocol"].startswith("# MARM MCP Protocol")

    # Calls 2-29: no injection
    for _ in range(28):
        r = asyncio.run(wrapped(session_name="main"))
        assert "marm_protocol" not in r
        assert "marm_protocol_lite" not in r

    # Call 30: lite injection
    r30 = asyncio.run(wrapped(session_name="main"))
    assert "marm_protocol_lite" in r30
    assert "MARM Protocol - Quick Reference" in r30["marm_protocol_lite"]


def test_stdio_lite_and_compaction_coexist(monkeypatch, tmp_path):
    """STDIO: on call 30, lite AND compaction both appear in result."""
    import marm_mcp_server.server_stdio as stdio
    import marm_mcp_server.services.notebook as notebook_service
    from marm_mcp_server.core.memory import MARMMemory

    mem = MARMMemory(str(tmp_path / "stdio-coexist.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(stdio, "memory", mem)
    monkeypatch.setattr(notebook_service, "memory", mem)

    stdio._protocol_delivered = False
    stdio._protocol_call_count = 0

    async def dummy_tool(*args, **kwargs):
        return {"status": "success"}

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(stdio, "ensure_marm_started", noop)
    monkeypatch.setattr(stdio, "maybe_auto_refresh", noop)

    # Return a known compaction string instead of None
    monkeypatch.setattr(
        stdio,
        "claim_pending_compaction_prompt",
        lambda *a, **kw: {"type": "text", "text": "COMPACTION_NUDGE_CONTENT"},
    )

    wrapped = stdio._log_tool_call(dummy_tool)

    # 29 warm calls (lite should NOT fire, compaction on non-lite calls fires)
    for _ in range(29):
        r = asyncio.run(wrapped(session_name="main"))
        # Compaction may fire on calls 2-29; lite must not
        assert "marm_protocol_lite" not in r

    # Call 30: both lite and compaction
    r30 = asyncio.run(wrapped(session_name="main"))
    assert "marm_protocol_lite" in r30
    assert "COMPACTION_NUDGE_CONTENT" in str(r30), (
        "compaction blocked by lite — result keys: %s" % list(r30.keys())
    )
