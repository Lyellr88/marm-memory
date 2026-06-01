import os
import re
import socket
import subprocess
import sys
import time
import importlib

import requests


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


def test_import_marm_mcp_server_succeeds_with_clean_stdout(tmp_path):
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "import-memory.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "import-analytics.db")
    env["USERPROFILE"] = str(tmp_path)
    env["HOME"] = str(tmp_path)

    result = subprocess.run(
        [sys.executable, "-c", "import marm_mcp_server; assert marm_mcp_server.__name__ == 'marm_mcp_server'"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_runtime_presets_configure_rate_limit_and_write_queue(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    server = load_isolated_server(monkeypatch, tmp_path, write_queue_enabled=True)
    settings = importlib.import_module("marm_mcp_server.config.settings")
    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    rate_limiter_module = importlib.import_module("marm_mcp_server.core.rate_limiter")

    custom_only = server.apply_runtime_preset(rate_limit_rpm=150)
    assert custom_only == {"mode": "custom", "rate_limit_rpm": 150, "write_queue_enabled": True}
    assert settings.MARM_RATE_LIMIT_RPM == 150
    assert settings.COMPACTION_TRIGGER_COUNT == 20
    assert memory_module.COMPACTION_TRIGGER_COUNT == 20
    assert memory_module.WRITE_QUEUE_ENABLED is True
    assert rate_limiter_module.rate_limiter.limits["default"]["requests"] == 150

    swarm = server.apply_runtime_preset(swarm=True)
    assert swarm == {"mode": "swarm", "rate_limit_rpm": 200, "write_queue_enabled": True}
    assert settings.MARM_RATE_LIMIT_RPM == 200
    assert settings.COMPACTION_TRIGGER_COUNT == 20
    assert memory_module.COMPACTION_TRIGGER_COUNT == 20
    assert memory_module.WRITE_QUEUE_ENABLED is True
    assert rate_limiter_module.rate_limiter.limits["default"]["requests"] == 200

    swarm_max = server.apply_runtime_preset(swarm_max=True)
    assert swarm_max == {"mode": "swarm-max", "rate_limit_rpm": 600, "write_queue_enabled": True}
    assert settings.COMPACTION_TRIGGER_COUNT == 20
    assert memory_module.COMPACTION_TRIGGER_COUNT == 20
    assert rate_limiter_module.rate_limiter.limits["default"]["requests"] == 600

    custom = server.apply_runtime_preset(swarm=True, rate_limit_rpm=150)
    assert custom == {"mode": "custom", "rate_limit_rpm": 150, "write_queue_enabled": True}
    assert settings.COMPACTION_TRIGGER_COUNT == 20
    assert memory_module.COMPACTION_TRIGGER_COUNT == 20
    assert rate_limiter_module.rate_limiter.limits["default"]["requests"] == 150

    trusted = server.apply_runtime_preset(swarm_max=True, trusted=True, rate_limit_rpm=150)
    assert trusted == {"mode": "trusted", "rate_limit_rpm": 0, "write_queue_enabled": True}
    assert settings.COMPACTION_TRIGGER_COUNT == 20
    assert memory_module.COMPACTION_TRIGGER_COUNT == 20
    assert rate_limiter_module.rate_limiter.limits["default"]["requests"] == 0


def test_default_runtime_preset_uses_low_compaction_trigger(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    server = load_isolated_server(monkeypatch, tmp_path)
    settings = importlib.import_module("marm_mcp_server.config.settings")
    memory_module = importlib.import_module("marm_mcp_server.core.memory")

    result = server.apply_runtime_preset()

    assert result["mode"] == "default"
    assert settings.COMPACTION_TRIGGER_COUNT == 5
    assert memory_module.COMPACTION_TRIGGER_COUNT == 5


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(base_url, timeout=30):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/health", timeout=3)
            if response.status_code == 200 and response.json()["status"] == "healthy":
                return
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise AssertionError(f"Server did not become healthy within {timeout}s: {last_error}")


def test_server_starts_and_health_returns_healthy(tmp_path):
    port = _free_port()
    env = os.environ.copy()
    env["MARM_DB_PATH"] = str(tmp_path / "server-memory.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "server-analytics.db")
    env["SERVER_HOST"] = "127.0.0.1"
    env["SERVER_PORT"] = str(port)
    env["USERPROFILE"] = str(tmp_path)
    env["HOME"] = str(tmp_path)
    env.pop("MARM_API_KEY", None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "marm_mcp_server"],
        cwd=os.getcwd(),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_for_health(f"http://127.0.0.1:{port}")
        response = requests.get(f"http://127.0.0.1:{port}/health", timeout=5)
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
