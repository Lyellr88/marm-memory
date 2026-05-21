import json
import os
import subprocess
import sys


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
    assert "marm_contextual_log" in tool_names
    assert "marm_delete" in tool_names
    assert "marm_log_delete" not in tool_names
    assert "marm_notebook_delete" not in tool_names
    assert len(tools) == 12


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
            "name": "marm_notebook_add",
            "arguments": {"name": "smoke_test_entry", "data": "temporary regression fixture"},
        }})
        + message({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "marm_notebook_use",
            "arguments": {"names": "smoke_test_entry"},
        }})
        + message({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "marm_delete",
            "arguments": {"type": "notebook", "target": "smoke_test_entry"},
        }})
        + message({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "marm_notebook_status",
            "arguments": {},
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

    status_result = json.loads(responses[5]["result"]["content"][0]["text"])
    assert status_result["active_entries"] == [], (
        f"Deleted entry still active after marm_delete(type='notebook'): {status_result['active_entries']}"
    )


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

    project_result = json.loads(responses[4]["result"]["content"][0]["text"])
    assert project_result["total_entries"] == 1, (
        f"Entry did not land in 'myproject' — got {project_result}"
    )

    main_result = json.loads(responses[5]["result"]["content"][0]["text"])
    assert main_result.get("total_entries", 0) == 0, (
        f"Entry incorrectly landed in 'main' — got {main_result}"
    )


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
            "name": "marm_contextual_log",
            "arguments": {"session_name": "privacy-test", "content": secret_content},
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
