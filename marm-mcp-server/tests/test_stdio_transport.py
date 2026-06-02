import json
import os
import sqlite3
import subprocess
import sys
import asyncio

from anyio import ClosedResourceError, EndOfStream


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


def test_stdio_handles_mcp_initialize_and_exposes_tools(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "stdio-rpc.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "stdio-rpc-analytics.db")

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1"},
        }})
        + message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
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

    assert 1 in responses, f"No initialize response; stderr: {result.stderr.decode('utf-8', errors='replace')[:500]}"
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
    assert "marm_context_log" in tool_names
    assert "marm_delete" in tool_names
    assert "marm_notebook" in tool_names
    assert "marm_log_delete" not in tool_names
    assert "marm_notebook_delete" not in tool_names
    assert "marm_notebook_add" not in tool_names, "old marm_notebook_add must be removed"
    assert "marm_notebook_use" not in tool_names, "old marm_notebook_use must be removed"
    assert "marm_notebook_show" not in tool_names, "old marm_notebook_show must be removed"
    assert "marm_notebook_status" not in tool_names, "old marm_notebook_status must be removed"
    assert "marm_notebook_clear" not in tool_names, "old marm_notebook_clear must be removed"
    assert "marm_compaction" in tool_names
    assert "marm_get_compaction_candidates" not in tool_names
    assert "marm_stage_compaction_summaries" not in tool_names
    assert "marm_get_staged_summaries" not in tool_names
    assert "marm_apply_compaction" not in tool_names
    assert len(tools) == 9


def test_stdio_delete_notebook_removes_entry_from_active_state(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "stdio-notebook.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "stdio-notebook-analytics.db")

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1"},
        }})
        + message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        + message({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "add", "name": "smoke_test_entry", "data": "temporary regression fixture"},
        }})
        + message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "use", "names": "smoke_test_entry"},
        }})
        + message({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "marm_delete",
            "arguments": {"type": "notebook", "target": "smoke_test_entry"},
        }})
        + message({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
        # Drain calls — marm_delete races with shutdown; extra messages keep stdin
        # open until all responses including delete are written before EOF.
        + message({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
        + message({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
        + message({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
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

    add_result = json.loads(responses[2]["result"]["content"][0]["text"])
    assert add_result["status"] == "success"

    use_result = json.loads(responses[3]["result"]["content"][0]["text"])
    assert use_result["activated_entries"] == ["smoke_test_entry"]

    delete_result = json.loads(responses[4]["result"]["content"][0]["text"])
    assert delete_result["deleted"] is True

    with sqlite3.connect(env["MARM_DB_PATH"]) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM notebook_entries WHERE name = ?",
            ("smoke_test_entry",),
        ).fetchone()[0]
    assert remaining == 0

    status_response = next((responses[i] for i in (5, 6, 7, 8) if i in responses), None)
    if status_response is not None:
        status_result = json.loads(status_response["result"]["content"][0]["text"])
        assert status_result["active_entries"] == [], (
            f"Deleted entry still active after marm_delete(type='notebook'): {status_result['active_entries']}"
        )


def test_stdio_notebook_session_name_scopes_active_state(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "stdio-notebook-scope.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "stdio-notebook-scope-analytics.db")

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1"},
        }})
        + message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        + message({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "add", "name": "alpha_rule", "data": "alpha scoped instruction"},
        }})
        + message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "use", "names": "alpha_rule", "session_name": "alpha"},
        }})
        + message({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status", "session_name": "alpha"},
        }})
        + message({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status", "session_name": "main"},
        }})
        + message({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status", "session_name": "alpha"},
        }})
        + message({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status", "session_name": "alpha"},
        }})
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

    assert 4 in responses, f"Missing STDIO responses: {sorted(responses)}"

    alpha_status = json.loads(responses[4]["result"]["content"][0]["text"])

    assert alpha_status["active_entries"] == ["alpha_rule"]


def test_stdio_log_entry_without_session_uses_active_session(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "stdio-session.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "stdio-session-analytics.db")

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1"},
        }})
        + message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        + message({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "marm_log_session",
            "arguments": {"session_name": "myproject"},
        }})
        # No session_name — should route to "myproject" via active_log_session
        + message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "marm_log_entry",
            "arguments": {"entry": "2026-05-20-setup-initial scaffolding done"},
        }})
        + message({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "marm_log_show",
            "arguments": {"session_name": "myproject"},
        }})
        + message({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "marm_log_show",
            "arguments": {"session_name": "main"},
        }})
        + message({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "marm_log_show",
            "arguments": {"session_name": "myproject"},
        }})
        + message({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "marm_log_show",
            "arguments": {"session_name": "main"},
        }})
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

    switch_result = json.loads(responses[2]["result"]["content"][0]["text"])
    assert switch_result["status"] == "success"

    with sqlite3.connect(env["MARM_DB_PATH"]) as conn:
        project_count = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE session_name = ?",
            ("myproject",),
        ).fetchone()[0]
        main_count = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE session_name = ?",
            ("main",),
        ).fetchone()[0]

    assert project_count == 1, f"Entry did not land in 'myproject'; count={project_count}"
    assert main_count == 0, f"Entry incorrectly landed in 'main'; count={main_count}"


def _base_rpc_stdin():
    """Minimal JSON-RPC handshake bytes used by logging tests."""
    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    return (
        message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.1"},
        }})
        + message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    )


def test_stdio_log_file_is_created_and_contains_startup(tmp_path):
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "log-test.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "log-test-analytics.db")
    env["MARM_STDIO_LOG_DIR"] = str(log_dir)

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


def test_stdio_log_records_tool_call_and_ok_status(tmp_path):
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "log-tool.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "log-tool-analytics.db")
    env["MARM_STDIO_LOG_DIR"] = str(log_dir)

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        _base_rpc_stdin()
        + message({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "marm_log_session",
            "arguments": {"session_name": "log-test"},
        }})
        # Drain call — keeps stdin open until doc loading and the tool response are
        # both written before EOF. Single-tool-call sessions race with FastMCP shutdown.
        + message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
        + message({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
        + message({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
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
    assert "CALL marm_log_session" in log_content, f"Expected CALL entry, got: {log_content}"
    assert "OK marm_log_session" in log_content, f"Expected OK entry, got: {log_content}"


def test_stdio_debug_mode_logs_session_name_not_content(tmp_path):
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "log-debug.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "log-debug-analytics.db")
    env["MARM_STDIO_LOG_DIR"] = str(log_dir)
    env["MARM_STDIO_LOG_LEVEL"] = "DEBUG"

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        _base_rpc_stdin()
        + message({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "marm_log_session",
            "arguments": {"session_name": "debug-session"},
        }})
        # Drain call — keeps stdin open until doc loading and the tool response are
        # both written before EOF. Single-tool-call sessions race with FastMCP shutdown.
        + message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
        + message({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
        + message({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
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
    assert "session=debug-session" in log_content, f"Expected session name in DEBUG log, got: {log_content}"


def test_stdio_log_does_not_contain_stored_memory_content(tmp_path):
    log_dir = tmp_path / "logs"
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "log-privacy.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "log-privacy-analytics.db")
    env["MARM_STDIO_LOG_DIR"] = str(log_dir)

    secret_content = "PRIVATE_SENTINEL_XQ9Z3_SHOULD_NOT_APPEAR_IN_LOG"

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        _base_rpc_stdin()
        + message({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "marm_context_log",
            "arguments": {"session_name": "privacy-test", "content": secret_content},
        }})
        # Drain call — keeps stdin open until doc loading and the tool response are
        # both written before EOF. Single-tool-call sessions race with FastMCP shutdown.
        + message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "marm_notebook",
            "arguments": {"action": "status"},
        }})
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


def test_stdio_context_log_uses_write_queue_when_enabled(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "stdio-queue.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "stdio-queue-analytics.db")
    env["WRITE_QUEUE_ENABLED"] = "1"

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        _base_rpc_stdin()
        + message({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "marm_context_log",
            "arguments": {
                "session_name": "stdio-queue",
                "content": "queued stdio memory write for swarm agents",
            },
        }})
        + message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "marm_smart_recall",
            "arguments": {"session_name": "stdio-queue", "query": "swarm agents", "limit": 3},
        }})
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

    assert 2 in responses, f"Missing STDIO responses: {sorted(responses)}"
    log_result = json.loads(responses[2]["result"]["content"][0]["text"])
    assert log_result["status"] == "success"

    import sqlite3
    with sqlite3.connect(env["MARM_DB_PATH"]) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?",
            ("stdio-queue",),
        ).fetchone()[0]

    assert count == 1


def test_stdio_protocol_injected_on_first_tool_call_not_on_second(monkeypatch):
    import marm_mcp_server.server_stdio as stdio

    async def _noop(*args, **kwargs):
        return None

    async def _protocol():
        return "protocol text"

    def _claim(memory):
        return None

    monkeypatch.setattr(stdio, "ensure_marm_started", _noop)
    monkeypatch.setattr(stdio, "maybe_auto_refresh", _noop)
    monkeypatch.setattr(stdio, "read_protocol_file", _protocol)
    monkeypatch.setattr(stdio, "claim_pending_compaction_prompt", _claim)
    stdio._protocol_delivered = False

    @stdio._log_tool_call
    async def fake_tool():
        return {"status": "success"}

    first = asyncio.run(fake_tool())
    second = asyncio.run(fake_tool())

    assert first["marm_protocol"] == "protocol text"
    assert "marm_protocol" not in second


def test_stdio_compaction_injection_wraps_tool_result(monkeypatch, tmp_path):
    import marm_mcp_server.server_stdio as stdio

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(stdio, "ensure_marm_started", _noop)
    monkeypatch.setattr(stdio, "maybe_auto_refresh", _noop)
    monkeypatch.setattr(
        stdio,
        "claim_pending_compaction_prompt",
        lambda memory: {"type": "text", "text": "[MARM COMPACTION REQUEST]\nabc"},
    )
    stdio._protocol_delivered = True

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

    calls = {"claim": 0}

    async def _noop(*args, **kwargs):
        return None

    async def _protocol():
        return "protocol text"

    def _claim(memory):
        calls["claim"] += 1
        return {"type": "text", "text": "[MARM COMPACTION REQUEST]\nabc"}

    monkeypatch.setattr(stdio, "ensure_marm_started", _noop)
    monkeypatch.setattr(stdio, "maybe_auto_refresh", _noop)
    monkeypatch.setattr(stdio, "read_protocol_file", _protocol)
    monkeypatch.setattr(stdio, "claim_pending_compaction_prompt", _claim)
    stdio._protocol_delivered = False

    @stdio._log_tool_call
    async def fake_tool():
        return {"status": "success"}

    result = asyncio.run(fake_tool())

    assert result["marm_protocol"] == "protocol text"
    assert "content" not in result
    assert calls["claim"] == 0


def test_is_graceful_teardown_rejects_mixed_exception_group():
    """Regression: a mixed ExceptionGroup must not be swallowed as normal teardown."""
    from marm_mcp_server.server_stdio import _is_graceful_teardown

    class RealBug(ValueError):
        pass

    pure_group = ExceptionGroup("teardown", [ClosedResourceError()])
    mixed_group = ExceptionGroup("mixed", [ClosedResourceError(), RealBug("actual bug")])
    direct = EndOfStream()
    unrelated = RuntimeError("crash")

    assert _is_graceful_teardown(pure_group) is True
    assert _is_graceful_teardown(mixed_group) is False
    assert _is_graceful_teardown(direct) is True
    assert _is_graceful_teardown(unrelated) is False
