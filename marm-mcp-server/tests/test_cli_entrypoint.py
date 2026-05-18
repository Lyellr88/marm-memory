import os
import re
import subprocess
import sys


def test_generate_key_cli_prints_one_key_and_exits_without_starting_server(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "cli-memory.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "cli-analytics.db")
    env["SERVER_HOST"] = "0.0.0.0"
    env["USERPROFILE"] = str(tmp_path)
    env["HOME"] = str(tmp_path)
    env.pop("MARM_API_KEY", None)

    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server", "--generate-key"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert re.fullmatch(r"[A-Za-z0-9\-_\+=\.~@#%\^&*]{40}", lines[0])
    assert "Set this as your MARM_API_KEY environment variable." in result.stdout
    assert "Starting MARM MCP Server" not in result.stdout
    assert "API key auto-generated" not in result.stdout
    assert not (tmp_path / ".marm" / ".env").exists()


def test_check_deps_cli_reports_dependency_status_without_starting_server(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "cli-memory.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "cli-analytics.db")
    env["SERVER_HOST"] = "127.0.0.1"
    env["USERPROFILE"] = str(tmp_path)
    env["HOME"] = str(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server", "--check-deps"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "MARM MCP Server - Dependency Check" in result.stdout
    assert "All dependencies satisfied!" in result.stdout
    assert "Uvicorn running" not in result.stdout
