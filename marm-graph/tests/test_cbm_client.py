"""Tests for the codebase-memory-mcp subprocess client.

Pure envelope-decoding tests run everywhere; transport tests use the real binary.
"""

import pytest

from marm_graph.core.cbm_client import CbmClient, CbmError, CbmTimeoutError, CbmToolError
from conftest import requires_binary

EXPECTED_TOOLS = {
    "index_repository", "search_graph", "query_graph", "trace_path",
    "get_code_snippet", "get_graph_schema", "get_architecture", "search_code",
    "list_projects", "delete_project", "index_status", "detect_changes",
    "manage_adr", "ingest_traces",
}


# ── pure: envelope decoding (no subprocess) ─────────────────────────


def test_unwrap_json_payload():
    result = {"content": [{"type": "text", "text": '{"projects": [], "hint": "x"}'}]}
    payload = CbmClient._unwrap("list_projects", result)
    assert payload == {"projects": [], "hint": "x"}


def test_unwrap_plain_string_payload():
    result = {"content": [{"type": "text", "text": "just text"}], "isError": True}
    with pytest.raises(CbmToolError) as ei:
        CbmClient._unwrap("no_such_tool", result)
    assert "just text" in str(ei.value)


def test_unwrap_error_with_hint():
    result = {
        "content": [{"type": "text", "text": '{"error": "bad", "hint": "do this"}'}],
        "isError": True,
    }
    with pytest.raises(CbmToolError) as ei:
        CbmClient._unwrap("index_status", result)
    assert ei.value.hint == "do this"
    assert ei.value.payload["error"] == "bad"


def test_unwrap_success_has_no_iserror():
    result = {"content": [{"type": "text", "text": '{"ok": 1}'}]}
    assert CbmClient._unwrap("t", result) == {"ok": 1}


def test_unwrap_skips_prepended_update_notice():
    """Upstream prepends a plain-text update notice ahead of the real JSON
    payload (mcp.c:5298-5302) once per startup when a newer release exists.
    _unwrap must find the real payload, not treat the notice as the answer.
    """
    result = {
        "content": [
            {"type": "text", "text": "Update available: 0.10.0 -> 0.11.0 -- run: codebase-memory-mcp update"},
            {"type": "text", "text": '{"projects": ["demo"]}'},
        ]
    }
    payload = CbmClient._unwrap("list_projects", result)
    assert payload == {"projects": ["demo"]}


def test_unwrap_falls_back_to_last_text_when_nothing_is_json():
    result = {
        "content": [
            {"type": "text", "text": "Update available: 0.10.0 -> 0.11.0"},
            {"type": "text", "text": "unknown tool: no_such_tool"},
        ],
        "isError": True,
    }
    with pytest.raises(CbmToolError) as ei:
        CbmClient._unwrap("no_such_tool", result)
    assert "unknown tool: no_such_tool" in str(ei.value)


# ── transport: real binary ──────────────────────────────────────────


@requires_binary
def test_handshake_captures_binary_version(client):
    assert client.server_name == "codebase-memory-mcp"
    # The binary self-reports its own version (distinct from the pinned pip one).
    assert client.server_version and client.server_version[0].isdigit()


@requires_binary
def test_tools_list_matches_expected_schema(client):
    names = {t["name"] for t in client.list_tools()}
    assert names == EXPECTED_TOOLS


@requires_binary
def test_call_tool_success(client):
    payload = client.call_tool("list_projects", {})
    assert isinstance(payload, dict) and "projects" in payload


@requires_binary
def test_call_tool_unknown_raises(client):
    with pytest.raises(CbmToolError):
        client.call_tool("definitely_not_a_tool", {})


@requires_binary
def test_call_tool_missing_arg_raises_with_hint(client):
    with pytest.raises(CbmToolError) as ei:
        client.call_tool("index_status", {})
    assert ei.value.hint  # binary supplies a remediation hint


@requires_binary
def test_timeout_does_not_kill_child(binary):
    """A slow-but-alive child must not be killed on timeout (finding 3):
    killing it mid-call would destroy in-flight work (e.g. a long index run)
    and force a blind retry from zero. Force a timeout with an unreasonably
    short call_timeout, then confirm the same process is still running and
    still answers correctly once given a normal timeout.
    """
    c = CbmClient(command=[binary], startup_timeout=90, call_timeout=300)
    c.start()
    try:
        pid_before = c._proc.pid
        with pytest.raises(CbmTimeoutError):
            c.call_tool("list_projects", {}, timeout=0.001)
        assert c._proc is not None and c._proc.pid == pid_before
        assert c._proc.poll() is None  # still alive, not killed
        payload = c.call_tool("list_projects", {})
        assert isinstance(payload, dict) and "projects" in payload
    finally:
        c.close()


@requires_binary
def test_crash_recovery_respawns(binary):
    c = CbmClient(command=[binary], startup_timeout=90, call_timeout=60)
    c.start()
    try:
        old_pid = c._proc.pid
        c._proc.kill()
        c._proc.wait()
        payload = c.call_tool("list_projects", {})  # must transparently respawn
        assert c._proc.pid != old_pid
        assert isinstance(payload, dict) and "projects" in payload
    finally:
        c.close()
