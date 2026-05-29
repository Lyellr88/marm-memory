"""Test helpers for isolated MARM server imports."""

import importlib
import sys

from fastapi.testclient import TestClient


def load_isolated_server(monkeypatch, tmp_path, api_key="", write_queue_enabled=False):
    """Import the server after pointing global state at a temporary database."""
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            del sys.modules[name]

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "marm_memory.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("WRITE_QUEUE_ENABLED", "1" if write_queue_enabled else "0")
    if api_key:
        monkeypatch.setenv("MARM_API_KEY", api_key)
    else:
        monkeypatch.delenv("MARM_API_KEY", raising=False)

    server = importlib.import_module("marm_mcp_server.server")

    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    monkeypatch.setattr(memory_module.memory, "_encoder_failed", True)
    monkeypatch.setattr(memory_module.memory, "active_notebook_entries_by_session", {})
    monkeypatch.setattr(memory_module.memory, "active_log_session", "main")

    rate_limiter_module = importlib.import_module("marm_mcp_server.core.rate_limiter")
    rate_limiter_module.rate_limiter.request_buckets.clear()
    rate_limiter_module.rate_limiter.blocked_ips.clear()

    return server


def local_client(app):
    return TestClient(app, client=("127.0.0.1", 50000))


def remote_client(app):
    return TestClient(app, client=("10.0.0.25", 50000))
