"""Tests for the codebase-memory-mcp subprocess client.

Pure envelope-decoding tests run everywhere; transport tests use the real binary.
"""

import json

import pytest
from conftest import requires_binary

from marm_graph.core.cbm_client import (
    CbmClient,
    CbmError,
    CbmTimeoutError,
    CbmToolError,
)

EXPECTED_TOOLS = {
    "index_repository",
    "search_graph",
    "query_graph",
    "trace_path",
    "get_code_snippet",
    "get_graph_schema",
    "get_architecture",
    "search_code",
    "list_projects",
    "delete_project",
    "index_status",
    "detect_changes",
    "manage_adr",
    "ingest_traces",
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


def test_unwrap_recovers_hint_from_truncated_error_payload():
    """The child caps its error payload and can cut the trailing project list
    mid-token, so json.loads fails on a document whose error/hint are intact.
    Observed for real against 0.8.1: index_status with 45 projects indexed
    returned 4258 chars ending '..._releases_],"count":45}' -- an unterminated
    string. Before this fallback, .hint went None purely because the store had
    grown, and the 4 KB blob became the exception message.
    """
    text = (
        '{"error":"project not found or not indexed",'
        '"hint":"Use list_projects to see all indexed projects",'
        '"projects":["C-Users-lyell-Desktop-MARM-Systems",'
        '"C-Users-lyell-Desktop],"count":45}'
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)  # the payload really is unparseable

    result = {"content": [{"type": "text", "text": text}], "isError": True}
    with pytest.raises(CbmToolError) as ei:
        CbmClient._unwrap("index_status", result)

    assert ei.value.hint == "Use list_projects to see all indexed projects"
    assert str(ei.value) == "index_status: project not found or not indexed"
    assert ei.value.payload == text


def test_unwrap_reports_no_hint_when_text_has_none():
    result = {
        "content": [{"type": "text", "text": "unknown tool: no_such_tool"}],
        "isError": True,
    }
    with pytest.raises(CbmToolError) as ei:
        CbmClient._unwrap("no_such_tool", result)
    assert ei.value.hint is None


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
            {
                "type": "text",
                "text": "Update available: 0.10.0 -> 0.11.0 -- run: codebase-memory-mcp update",
            },
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


# ── pure: tools/list pagination (scripted wire, no subprocess) ──────


def _paginating_client(pages, monkeypatch):
    """A client whose tools/list answers from `pages`, recording sent params.

    Fakes only the wire: real list_tools drives the loop. _alive is stubbed so
    no child is spawned. Page shapes mirror what 0.9.0 actually returns,
    captured from the binary: 8 tools plus nextCursor as the string "8", then a
    final page with the remaining 6 and no cursor.
    """
    client = CbmClient(command=["unused"])
    sent = []

    def fake_send_recv(method, params, timeout):
        assert method == "tools/list"
        sent.append(params)
        return pages[len(sent) - 1]

    monkeypatch.setattr(client, "_alive", lambda: True)
    monkeypatch.setattr(client, "_send_recv", fake_send_recv)
    return client, sent


def _tool_pages():
    names = sorted(EXPECTED_TOOLS)
    return [
        {"tools": [{"name": n} for n in names[:8]], "nextCursor": "8"},
        {"tools": [{"name": n} for n in names[8:]]},
    ]


def test_list_tools_follows_cursor_to_the_end(monkeypatch):
    """0.9.0 pages tools/list 8-at-a-time. Reading one page saw 8 of 14 and
    check_schema reported the other 6 as removed, refusing to start.
    """
    client, sent = _paginating_client(_tool_pages(), monkeypatch)

    names = {t["name"] for t in client.list_tools()}

    assert names == EXPECTED_TOOLS
    assert sent == [{}, {"cursor": "8"}]


def test_list_tools_single_page_sends_no_cursor(monkeypatch):
    """0.8.1 returns every tool with no nextCursor: exactly one request."""
    one_page = [{"tools": [{"name": n} for n in sorted(EXPECTED_TOOLS)]}]
    client, sent = _paginating_client(one_page, monkeypatch)

    assert {t["name"] for t in client.list_tools()} == EXPECTED_TOOLS
    assert sent == [{}]


def test_list_tools_treats_falsy_cursor_as_a_real_page(monkeypatch):
    """A cursor is opaque, so 0 and "" are valid values. Terminating on
    truthiness would silently drop every page after one of them.
    """
    pages = [
        {"tools": [{"name": "index_repository"}], "nextCursor": 0},
        {"tools": [{"name": "search_graph"}], "nextCursor": ""},
        {"tools": [{"name": "query_graph"}]},
    ]
    client, sent = _paginating_client(pages, monkeypatch)

    names = [t["name"] for t in client.list_tools()]

    assert names == ["index_repository", "search_graph", "query_graph"]
    assert sent == [{}, {"cursor": 0}, {"cursor": ""}]


def test_list_tools_refuses_a_repeating_cursor(monkeypatch):
    """A child that echoes the same cursor forever must raise, not hang."""
    stuck = {"tools": [{"name": "index_repository"}], "nextCursor": "8"}
    client, _ = _paginating_client([stuck] * 50, monkeypatch)

    with pytest.raises(CbmError, match="repeated cursor"):
        client.list_tools()


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
def test_timeout_does_not_kill_child(binary, monkeypatch):
    """A slow-but-alive child must not be killed on timeout (finding 3):
    killing it mid-call would destroy in-flight work (e.g. a long index run)
    and force a blind retry from zero. Force a deterministic timeout by
    monkeypatching _send_recv (not a real short call_timeout racing against
    actual IPC latency, which would make this test flaky), then confirm the
    same process is still running and still answers correctly once given a
    normal timeout.
    """
    c = CbmClient(command=[binary], startup_timeout=90, call_timeout=300)
    c.start()
    try:
        pid_before = c._proc.pid

        original_send_recv = c._send_recv

        def timeout_once(method, params, timeout):
            raise CbmTimeoutError("forced timeout")

        monkeypatch.setattr(c, "_send_recv", timeout_once)
        with pytest.raises(CbmTimeoutError):
            c.call_tool("list_projects", {})
        assert c._proc is not None and c._proc.pid == pid_before
        assert c._proc.poll() is None  # still alive, not killed

        monkeypatch.setattr(c, "_send_recv", original_send_recv)
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


# ── close() is terminal (no subprocess) ─────────────────────────────


def _popen_recorder(monkeypatch):
    """Records every real process creation attempt.

    Patched at subprocess.Popen rather than at _spawn: the guard lives inside
    _spawn, so stubbing _spawn would remove the very thing under test and the
    assertion would pass no matter what. This asserts at the process boundary,
    which is the thing that must not happen.
    """
    spawned = []

    def _fake_popen(*args, **kwargs):
        spawned.append(args[0] if args else kwargs.get("args"))
        raise AssertionError("a closed client created a process")

    monkeypatch.setattr("marm_graph.core.cbm_client.subprocess.Popen", _fake_popen)
    return spawned


def test_call_after_close_raises_instead_of_spawning_a_child(monkeypatch):
    """close() used to leave the instance reusable, which orphaned a process.

    It clears _proc, and _alive() reads _proc, so a closed client looked exactly
    like a never-started one. The "transparently respawns a dead child once" path
    then started a replacement whose owner had already dropped its reference, and
    the call *succeeded*, so nothing surfaced.
    """
    client = CbmClient(command=["unused"])
    spawned = _popen_recorder(monkeypatch)
    client.close()

    with pytest.raises(CbmError, match="closed"):
        client.call_tool("list_projects", {})
    assert spawned == []


def test_start_after_close_does_not_spawn(monkeypatch):
    """start() reaches _spawn() through the same _alive() check as call_tool.

    Guarding only the call path would leave close() reversible through a public
    method, so a stale holder could restart an engine nobody owns.
    """
    client = CbmClient(command=["unused"])
    spawned = _popen_recorder(monkeypatch)
    client.close()

    with pytest.raises(CbmError, match="closed"):
        client.start()
    assert spawned == []


def test_list_tools_after_close_does_not_spawn(monkeypatch):
    """The third public path into _spawn(), and the one no review flagged."""
    client = CbmClient(command=["unused"])
    spawned = _popen_recorder(monkeypatch)
    client.close()

    with pytest.raises(CbmError, match="closed"):
        client.list_tools()
    assert spawned == []


def test_close_is_idempotent_and_stays_closed(monkeypatch):
    """Teardown can call close() more than once; it must not reopen anything."""
    client = CbmClient(command=["unused"])
    spawned = _popen_recorder(monkeypatch)

    client.close()
    client.close()

    with pytest.raises(CbmError):
        client.call_tool("list_projects", {})
    assert spawned == []
