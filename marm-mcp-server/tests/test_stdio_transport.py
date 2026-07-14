import json
import os
import sqlite3
import subprocess
import sys
import asyncio

import pytest
from anyio import ClosedResourceError, EndOfStream
from mcp.shared.memory import create_connected_server_and_client_session


def _isolated_stdio(monkeypatch, tmp_path):
    import marm_mcp_server.server_stdio as stdio
    import marm_mcp_server.core.stdio_tool_lifecycle as lifecycle
    import marm_mcp_server.services.notebook as notebook_service
    from marm_mcp_server.core.memory import MARMMemory

    mem = MARMMemory(str(tmp_path / "stdio-inprocess.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(stdio, "memory", mem)
    monkeypatch.setattr(notebook_service, "memory", mem)

    async def _noop(*args, **kwargs):
        return None

    # ensure_marm_started/maybe_auto_refresh/claim_pending_compaction_prompt
    # and the protocol-delivery state now live in core.stdio_tool_lifecycle
    # (server-stdio-module-split.md Task 2) -- _log_tool_call resolves these
    # from its own module's globals, not server_stdio's.
    monkeypatch.setattr(lifecycle, "ensure_marm_started", _noop)
    monkeypatch.setattr(lifecycle, "maybe_auto_refresh", _noop)
    monkeypatch.setattr(
        lifecycle, "claim_pending_compaction_prompt", lambda *args, **kwargs: None
    )
    lifecycle._protocol_delivered = True
    return stdio


@pytest.mark.slow_stdio
def test_stdio_module_import_keeps_stdout_clean_for_json_rpc(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "stdio-memory.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "stdio-analytics.db")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import marm_mcp_server.server_stdio; assert marm_mcp_server.server_stdio.mcp is not None",
        ],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.slow_stdio
def test_stdio_handles_mcp_initialize_and_exposes_tools(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "stdio-rpc.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "stdio-rpc-analytics.db")
    env["MARM_SKIP_DOC_LOAD"] = "1"

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "0.1"},
                },
            }
        )
        + message(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        + message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    )

    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server.server_stdio"],
        input=stdin_data,
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[:500]

    responses = {}
    for line in result.stdout.splitlines():
        msg = json.loads(line)
        if "id" in msg:
            responses[msg["id"]] = msg

    assert 1 in responses, (
        f"No initialize response; stderr: {result.stderr.decode('utf-8', errors='replace')[:500]}"
    )
    assert "result" in responses[1]
    assert "serverInfo" in responses[1]["result"]

    assert 2 in responses, "No tools/list response"
    tools = responses[2]["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    assert "marm_start" not in tool_names
    assert "marm_refresh" not in tool_names
    assert "marm_reload_docs" not in tool_names
    assert "marm_current_context" not in tool_names
    assert "marm_system_info" not in tool_names
    assert "marm_smart_recall" in tool_names
    assert "marm_context_log" not in tool_names
    assert "marm_delete" in tool_names
    assert "marm_notebook" in tool_names
    assert "marm_log_delete" not in tool_names
    assert "marm_notebook_delete" not in tool_names
    assert "marm_notebook_add" not in tool_names, (
        "old marm_notebook_add must be removed"
    )
    assert "marm_notebook_use" not in tool_names, (
        "old marm_notebook_use must be removed"
    )
    assert "marm_notebook_show" not in tool_names, (
        "old marm_notebook_show must be removed"
    )
    assert "marm_notebook_status" not in tool_names, (
        "old marm_notebook_status must be removed"
    )
    assert "marm_notebook_clear" not in tool_names, (
        "old marm_notebook_clear must be removed"
    )
    assert "marm_compaction" in tool_names
    assert "marm_log_session" not in tool_names
    assert "marm_get_compaction_candidates" not in tool_names
    assert "marm_stage_compaction_summaries" not in tool_names
    assert "marm_get_staged_summaries" not in tool_names
    assert "marm_apply_compaction" not in tool_names
    assert "marm_graph_index" in tool_names
    assert "marm_code_lookup" in tool_names
    assert "marm_graph_trace" in tool_names
    assert "marm_graph_architecture" in tool_names
    assert "marm_graph_impact" in tool_names
    assert "marm_concept_build" in tool_names
    assert "marm_concept_recall" in tool_names
    assert len(tools) == 14


def test_stdio_delete_notebook_removes_entry_from_active_state(monkeypatch, tmp_path):
    stdio = _isolated_stdio(monkeypatch, tmp_path)

    add_result = asyncio.run(
        stdio.marm_notebook(
            action="add",
            name="smoke_test_entry",
            data="temporary regression fixture",
        )
    )
    assert add_result["status"] == "success"

    use_result = asyncio.run(
        stdio.marm_notebook(
            action="use",
            names="smoke_test_entry",
        )
    )
    assert use_result["activated_entries"] == ["smoke_test_entry"]

    delete_result = asyncio.run(
        stdio.marm_delete(
            type="notebook",
            target="smoke_test_entry",
        )
    )
    assert delete_result["deleted"] is True

    with stdio.memory.get_connection() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM notebook_entries WHERE name = ?",
            ("smoke_test_entry",),
        ).fetchone()[0]
    assert remaining == 0

    status_result = asyncio.run(stdio.marm_notebook(action="status"))
    assert status_result["active_entries"] == [], (
        f"Deleted entry still active after marm_delete(type='notebook'): {status_result['active_entries']}"
    )


def test_stdio_notebook_session_name_scopes_active_state(monkeypatch, tmp_path):
    stdio = _isolated_stdio(monkeypatch, tmp_path)

    asyncio.run(
        stdio.marm_notebook(
            action="add",
            name="alpha_rule",
            data="alpha scoped instruction",
        )
    )
    asyncio.run(
        stdio.marm_notebook(
            action="use",
            names="alpha_rule",
            session_name="alpha",
        )
    )

    alpha_status = asyncio.run(
        stdio.marm_notebook(action="status", session_name="alpha")
    )
    main_status = asyncio.run(stdio.marm_notebook(action="status", session_name="main"))

    assert alpha_status["active_entries"] == ["alpha_rule"]
    assert main_status["active_entries"] == []


def test_stdio_log_entry_without_session_uses_active_session(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    stdio = _isolated_stdio(monkeypatch, tmp_path)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    expected_session = f"myproject-{today}"

    switch_result = asyncio.run(stdio.marm_log_entry(entry="Session: myproject"))
    assert switch_result["status"] == "session_switched"
    assert switch_result["session_name"] == expected_session

    asyncio.run(
        stdio.marm_log_entry(
            entry="2026-05-20-setup-initial scaffolding done",
        )
    )

    with stdio.memory.get_connection() as conn:
        project_count = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE session_name = ?",
            (expected_session,),
        ).fetchone()[0]
        main_count = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE session_name = ?",
            ("main",),
        ).fetchone()[0]

    # 2 entries: session_start marker + the actual log entry
    assert project_count == 2, (
        f"Expected 2 entries in '{expected_session}'; got {project_count}"
    )
    assert main_count == 0, f"Entry incorrectly landed in 'main'; count={main_count}"


def test_stdio_inprocess_client_wraps_notebook_delete_and_log_results(
    monkeypatch, tmp_path
):
    stdio = _isolated_stdio(monkeypatch, tmp_path)

    async def run():
        async with create_connected_server_and_client_session(stdio.mcp) as client:
            add_result = await client.call_tool(
                "marm_notebook",
                {
                    "action": "add",
                    "name": "envelope_entry",
                    "data": "temporary envelope fixture",
                },
            )
            use_result = await client.call_tool(
                "marm_notebook",
                {"action": "use", "names": "envelope_entry"},
            )
            delete_result = await client.call_tool(
                "marm_delete",
                {"type": "notebook", "target": "envelope_entry"},
            )
            session_result = await client.call_tool(
                "marm_log_entry",
                {"entry": "Session: envelope-session"},
            )
            entry_result = await client.call_tool(
                "marm_log_entry",
                {"entry": "2026-06-03-envelope-routing verified"},
            )
        return add_result, use_result, delete_result, session_result, entry_result

    add_result, use_result, delete_result, session_result, entry_result = asyncio.run(
        run()
    )

    for result in (add_result, use_result, delete_result, session_result, entry_result):
        assert result.content
        assert result.content[0].type == "text"

    assert json.loads(add_result.content[0].text)["status"] == "success"
    assert json.loads(use_result.content[0].text)["activated_entries"] == [
        "envelope_entry"
    ]
    assert json.loads(delete_result.content[0].text)["deleted"] is True
    assert json.loads(session_result.content[0].text)["status"] == "session_switched"
    entry_body = json.loads(entry_result.content[0].text)
    assert entry_body["status"] == "success"
    assert entry_body["memory_id"], (
        f"stdio log entry did not dual-write a semantic memory: {entry_body}"
    )


def test_stdio_graph_tool_returns_unavailable_when_backend_down(monkeypatch, tmp_path):
    stdio = _isolated_stdio(monkeypatch, tmp_path)
    monkeypatch.setattr(stdio.graph_supervisor, "is_available", lambda: False)

    result = asyncio.run(stdio.marm_graph_index(repo_path="/tmp/some-repo"))

    assert result == {"status": "error", "message": "graph backend unavailable"}


def test_stdio_graph_unavailable_response_is_not_shared_mutable_state(
    monkeypatch, tmp_path
):
    """Regression: the unavailable response used to be one shared module-level
    dict returned by every call. _log_tool_call mutates its result in place
    (injecting marm_protocol on the first delivered call), so if the first
    STDIO call ever made were an unavailable graph call, that injected key
    would leak into every subsequent unavailable response forever. Force the
    real first-call path (_protocol_delivered = False, unlike the other tests
    in this module) and call twice to prove no state survives between calls.
    """
    import marm_mcp_server.core.stdio_tool_lifecycle as lifecycle

    stdio = _isolated_stdio(monkeypatch, tmp_path)
    lifecycle._protocol_delivered = False
    monkeypatch.setattr(stdio.graph_supervisor, "is_available", lambda: False)

    first = asyncio.run(stdio.marm_graph_index(repo_path="/tmp/some-repo"))
    assert "marm_protocol" in first  # confirms injection actually happened

    second = asyncio.run(stdio.marm_graph_index(repo_path="/tmp/some-repo"))

    assert second == {"status": "error", "message": "graph backend unavailable"}


def test_stdio_core_tool_unaffected_by_graph_unavailable(monkeypatch, tmp_path):
    """GRAPH_ENABLED=false (or a failed backend) must never break core STDIO tools."""
    stdio = _isolated_stdio(monkeypatch, tmp_path)
    monkeypatch.setattr(stdio.graph_supervisor, "is_available", lambda: False)

    result = asyncio.run(stdio.marm_notebook(action="status"))

    assert result["status"] == "success"


def test_stdio_inprocess_client_wraps_graph_index_happy_path(monkeypatch, tmp_path):
    stdio = _isolated_stdio(monkeypatch, tmp_path)
    monkeypatch.setattr(stdio.graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(stdio.graph_supervisor, "get_client", lambda: "fake-client")

    captured = {}

    def _fake_do_index(client, req):
        captured["client"] = client
        captured["req"] = req
        return {"status": "success", "project": "marm-memory"}

    monkeypatch.setattr(stdio.graph_router, "do_index", _fake_do_index)

    async def run():
        async with create_connected_server_and_client_session(stdio.mcp) as client:
            return await client.call_tool(
                "marm_graph_index", {"repo_path": "/tmp/some-repo"}
            )

    result = asyncio.run(run())

    assert result.content
    assert result.content[0].type == "text"
    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["project"] == "marm-memory"

    # Proves the wrapper reused graph_supervisor's client and built the same
    # Pydantic request model the HTTP endpoint uses, rather than duplicating
    # HTTP endpoint logic by hand.
    assert captured["client"] == "fake-client"
    assert captured["req"].repo_path == "/tmp/some-repo"


def test_stdio_concept_recall_passes_through_to_run_recall(monkeypatch, tmp_path):
    """marm_concept_recall's STDIO wrapper has its own try/except and
    duration_ms-free passthrough, distinct code from the HTTP endpoint --
    test_concept_endpoints.py covers _run_recall itself thoroughly but never
    through this wrapper. Guards against wrong argument order/names in the
    passthrough (e.g. project silently dropped or swapped with direction)."""
    stdio = _isolated_stdio(monkeypatch, tmp_path)

    captured = {}

    def _fake_run_recall(query, session_name, limit, depth, direction, project):
        captured.update(
            query=query,
            session_name=session_name,
            limit=limit,
            depth=depth,
            direction=direction,
            project=project,
        )
        return {"entities": [], "related_entities": [], "linked_code": []}

    monkeypatch.setattr(stdio, "_run_recall", _fake_run_recall)

    result = asyncio.run(
        stdio.marm_concept_recall(
            query="auth",
            session_name="sess-a",
            limit=5,
            depth=2,
            direction="outgoing",
            project="proj-a",
        )
    )

    assert result == {"entities": [], "related_entities": [], "linked_code": []}
    assert captured == {
        "query": "auth",
        "session_name": "sess-a",
        "limit": 5,
        "depth": 2,
        "direction": "outgoing",
        "project": "proj-a",
    }


def test_stdio_concept_recall_rejects_out_of_range_limit(monkeypatch, tmp_path):
    """The STDIO wrapper's limit/depth are plain ints, not a bounded pydantic
    field like the HTTP endpoint's ConceptRecallRequest -- without explicit
    validation, limit=-1 would reach SQLite as a raw `LIMIT -1` (no limit at
    all, returning every matching entity/relationship/code link)."""
    stdio = _isolated_stdio(monkeypatch, tmp_path)

    def _unreachable(*args, **kwargs):
        raise AssertionError("_run_recall must not be reached for invalid input")

    monkeypatch.setattr(stdio, "_run_recall", _unreachable)

    result = asyncio.run(stdio.marm_concept_recall(query="auth", limit=-1))

    assert result["status"] == "error"
    assert "Concept recall failed" in result["message"]


def test_stdio_concept_build_uses_same_endpoint_logic(monkeypatch, tmp_path):
    stdio = _isolated_stdio(monkeypatch, tmp_path)
    captured = {}

    async def _fake_endpoint(request):
        captured.update(request.model_dump())
        return {"status": "success", "build_run_id": request.run_id}

    monkeypatch.setattr(stdio, "_marm_concept_build_endpoint", _fake_endpoint)

    result = asyncio.run(
        stdio.marm_concept_build(
            session_name="sess-a", project="proj-a", run_id="console-run-1"
        )
    )

    assert captured == {
        "session_name": "sess-a",
        "project": "proj-a",
        "search_all": False,
        "run_id": "console-run-1",
    }
    assert result == {"status": "success", "build_run_id": "console-run-1"}


def test_stdio_concept_build_distinguishes_validation_and_runtime_failures(
    monkeypatch, tmp_path
):
    stdio = _isolated_stdio(monkeypatch, tmp_path)

    invalid = asyncio.run(stdio.marm_concept_build())
    assert invalid == {
        "status": "error",
        "message": "Concept build requires session_name, project, or search_all=True.",
    }

    async def _boom(_request):
        raise RuntimeError("concept database unavailable")

    monkeypatch.setattr(stdio, "_marm_concept_build_endpoint", _boom)
    failed = asyncio.run(stdio.marm_concept_build(session_name="sess-a"))
    assert failed == {"status": "error", "message": "Concept build failed."}


def test_stop_graph_supervisor_safely_swallows_errors(monkeypatch):
    import marm_mcp_server.server_stdio as stdio

    def _boom():
        raise RuntimeError("child process gone")

    monkeypatch.setattr(stdio.graph_supervisor, "stop", _boom)

    stdio._stop_graph_supervisor_safely()  # must not raise


def _base_rpc_stdin():
    """Minimal JSON-RPC handshake bytes used by logging tests."""

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    return message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0.1"},
            },
        }
    ) + message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})


@pytest.mark.slow_stdio
def test_stdio_log_file_is_created_and_contains_startup(tmp_path):
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "log-test.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "log-test-analytics.db")
    env["MARM_STDIO_LOG_DIR"] = str(log_dir)
    env["MARM_SKIP_DOC_LOAD"] = "1"

    stdin_data = _base_rpc_stdin()
    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server.server_stdio"],
        input=stdin_data,
        env=env,
        cwd=os.getcwd(),
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[:500]

    log_file = log_dir / "marm-stdio.log"
    assert log_file.exists(), "marm-stdio.log was not created"
    content = log_file.read_text(encoding="utf-8")
    assert "startup" in content, f"Expected 'startup' in log, got: {content[:500]}"


@pytest.mark.slow_stdio
def test_stdio_log_records_tool_call_and_ok_status(tmp_path):
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "log-tool.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "log-tool-analytics.db")
    env["MARM_STDIO_LOG_DIR"] = str(log_dir)
    env["MARM_SKIP_DOC_LOAD"] = "1"

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        _base_rpc_stdin()
        + message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "marm_log_entry",
                    "arguments": {"entry": "Session: log-test"},
                },
            }
        )
        # Drain call — keeps stdin open until doc loading and the tool response are
        # both written before EOF. Single-tool-call sessions race with STDIO shutdown.
        + message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "marm_notebook",
                    "arguments": {"action": "status"},
                },
            }
        )
        + message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "marm_notebook",
                    "arguments": {"action": "status"},
                },
            }
        )
        + message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "marm_notebook",
                    "arguments": {"action": "status"},
                },
            }
        )
    )

    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server.server_stdio"],
        input=stdin_data,
        env=env,
        cwd=os.getcwd(),
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[:500]
    log_content = (log_dir / "marm-stdio.log").read_text(encoding="utf-8")
    assert "CALL marm_log_entry" in log_content, (
        f"Expected CALL entry, got: {log_content}"
    )
    assert "OK marm_log_entry" in log_content, f"Expected OK entry, got: {log_content}"


@pytest.mark.slow_stdio
def test_stdio_debug_mode_logs_session_name_not_content(tmp_path):
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "log-debug.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "log-debug-analytics.db")
    env["MARM_STDIO_LOG_DIR"] = str(log_dir)
    env["MARM_STDIO_LOG_LEVEL"] = "DEBUG"
    env["MARM_SKIP_DOC_LOAD"] = "1"

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        _base_rpc_stdin()
        + message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "marm_log_entry",
                    "arguments": {
                        "entry": "2026-06-16-debug-session routing test",
                        "session_name": "debug-session",
                    },
                },
            }
        )
        # Drain call — keeps stdin open until doc loading and the tool response are
        # both written before EOF. Single-tool-call sessions race with STDIO shutdown.
        + message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "marm_notebook",
                    "arguments": {"action": "status"},
                },
            }
        )
        + message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "marm_notebook",
                    "arguments": {"action": "status"},
                },
            }
        )
        + message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "marm_notebook",
                    "arguments": {"action": "status"},
                },
            }
        )
    )

    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server.server_stdio"],
        input=stdin_data,
        env=env,
        cwd=os.getcwd(),
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[:500]
    log_content = (log_dir / "marm-stdio.log").read_text(encoding="utf-8")
    assert "session=debug-session" in log_content, (
        f"Expected session name in DEBUG log, got: {log_content}"
    )


@pytest.mark.slow_stdio
def test_stdio_log_does_not_contain_stored_memory_content(tmp_path):
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "log-privacy.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "log-privacy-analytics.db")
    env["MARM_STDIO_LOG_DIR"] = str(log_dir)
    env["MARM_SKIP_DOC_LOAD"] = "1"

    secret_content = "PRIVATE_SENTINEL_XQ9Z3_SHOULD_NOT_APPEAR_IN_LOG"

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        _base_rpc_stdin()
        + message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "marm_smart_recall",
                    "arguments": {
                        "session_name": "privacy-test",
                        "query": secret_content,
                    },
                },
            }
        )
        # Drain call — keeps stdin open until doc loading and the tool response are
        # both written before EOF. Single-tool-call sessions race with STDIO shutdown.
        + message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "marm_notebook",
                    "arguments": {"action": "status"},
                },
            }
        )
    )

    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server.server_stdio"],
        input=stdin_data,
        env=env,
        cwd=os.getcwd(),
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[:500]
    log_content = (log_dir / "marm-stdio.log").read_text(encoding="utf-8")
    assert secret_content not in log_content, (
        f"Memory content leaked into log file: {log_content[:500]}"
    )


@pytest.mark.slow_stdio
def test_stdio_log_entry_persists(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "stdio-queue.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "stdio-queue-analytics.db")
    env["MARM_SKIP_DOC_LOAD"] = "1"

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        _base_rpc_stdin()
        + message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "marm_log_entry",
                    "arguments": {
                        "entry": "2026-01-01-queued-stdio write queue test entry",
                    },
                },
            }
        )
        + message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "marm_smart_recall",
                    "arguments": {
                        "session_name": "stdio-queue",
                        "query": "swarm agents",
                        "limit": 3,
                    },
                },
            }
        )
        + message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "marm_smart_recall",
                    "arguments": {
                        "session_name": "stdio-queue",
                        "query": "swarm agents",
                        "limit": 3,
                    },
                },
            }
        )
        + message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "marm_smart_recall",
                    "arguments": {
                        "session_name": "stdio-queue",
                        "query": "swarm agents",
                        "limit": 3,
                    },
                },
            }
        )
        + message(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "marm_smart_recall",
                    "arguments": {
                        "session_name": "stdio-queue",
                        "query": "swarm agents",
                        "limit": 3,
                    },
                },
            }
        )
        + message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "marm_smart_recall",
                    "arguments": {
                        "session_name": "stdio-queue",
                        "query": "swarm agents",
                        "limit": 3,
                    },
                },
            }
        )
    )

    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server.server_stdio"],
        input=stdin_data,
        env=env,
        cwd=os.getcwd(),
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[:500]

    responses = {}
    for line in result.stdout.splitlines():
        msg = json.loads(line)
        if "id" in msg:
            responses[msg["id"]] = msg

    # log_entry (id=2) may arrive after drain calls; always verify via DB.
    if 2 in responses:
        log_result = json.loads(responses[2]["result"]["content"][0]["text"])
        assert log_result["status"] == "success"

    with sqlite3.connect(env["MARM_DB_PATH"]) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE session_name LIKE ?",
            ("session-%",),
        ).fetchone()[0]

    assert count >= 1, f"Log entry not persisted; STDIO responses: {sorted(responses)}"


def test_stdio_protocol_injected_on_first_tool_call_not_on_second(monkeypatch):
    import marm_mcp_server.server_stdio as stdio
    import marm_mcp_server.core.stdio_tool_lifecycle as lifecycle

    async def _noop(*args, **kwargs):
        return None

    async def _protocol():
        return "protocol text"

    def _claim(memory):
        return None

    monkeypatch.setattr(lifecycle, "ensure_marm_started", _noop)
    monkeypatch.setattr(lifecycle, "maybe_auto_refresh", _noop)
    monkeypatch.setattr(lifecycle, "read_protocol_file", _protocol)
    monkeypatch.setattr(lifecycle, "claim_pending_compaction_prompt", _claim)
    lifecycle._protocol_delivered = False

    @stdio._log_tool_call
    async def fake_tool():
        return {"status": "success"}

    first = asyncio.run(fake_tool())
    second = asyncio.run(fake_tool())

    assert first["marm_protocol"] == "protocol text"
    assert "marm_protocol" not in second


def test_stdio_compaction_injection_wraps_tool_result(monkeypatch, tmp_path):
    import marm_mcp_server.server_stdio as stdio
    import marm_mcp_server.core.stdio_tool_lifecycle as lifecycle

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(lifecycle, "ensure_marm_started", _noop)
    monkeypatch.setattr(lifecycle, "maybe_auto_refresh", _noop)
    monkeypatch.setattr(
        lifecycle,
        "claim_pending_compaction_prompt",
        lambda memory, session_name: {
            "type": "text",
            "text": "[MARM COMPACTION REQUEST]\nabc",
        },
    )
    lifecycle._protocol_delivered = True

    @stdio._log_tool_call
    async def fake_tool():
        return {"status": "success", "value": 1}

    result = asyncio.run(fake_tool())

    assert result["content"][0]["text"].startswith("[MARM COMPACTION REQUEST]")
    original = json.loads(result["content"][1]["text"])
    assert original["status"] == "success"
    assert original["value"] == 1


def test_stdio_protocol_call_suppresses_same_call_compaction(monkeypatch, tmp_path):
    import marm_mcp_server.server_stdio as stdio
    import marm_mcp_server.core.stdio_tool_lifecycle as lifecycle

    calls = {"claim": 0}

    async def _noop(*args, **kwargs):
        return None

    async def _protocol():
        return "protocol text"

    def _claim(memory):
        calls["claim"] += 1
        return {"type": "text", "text": "[MARM COMPACTION REQUEST]\nabc"}

    monkeypatch.setattr(lifecycle, "ensure_marm_started", _noop)
    monkeypatch.setattr(lifecycle, "maybe_auto_refresh", _noop)
    monkeypatch.setattr(lifecycle, "read_protocol_file", _protocol)
    monkeypatch.setattr(lifecycle, "claim_pending_compaction_prompt", _claim)
    lifecycle._protocol_delivered = False

    @stdio._log_tool_call
    async def fake_tool():
        return {"status": "success"}

    result = asyncio.run(fake_tool())

    assert result["marm_protocol"] == "protocol text"
    assert "content" not in result
    assert calls["claim"] == 0


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="ExceptionGroup is a Python 3.11+ builtin"
)
def test_is_graceful_teardown_rejects_mixed_exception_group():
    """Regression: a mixed ExceptionGroup must not be swallowed as normal teardown."""
    from marm_mcp_server.server_stdio import _is_graceful_teardown

    class RealBug(ValueError):
        pass

    pure_group = ExceptionGroup("teardown", [ClosedResourceError()])  # noqa: F821
    mixed_group = ExceptionGroup(  # noqa: F821
        "mixed", [ClosedResourceError(), RealBug("actual bug")]
    )
    direct = EndOfStream()
    unrelated = RuntimeError("crash")

    assert _is_graceful_teardown(pure_group) is True
    assert _is_graceful_teardown(mixed_group) is False
    assert _is_graceful_teardown(direct) is True
    assert _is_graceful_teardown(unrelated) is False
