"""Test helpers for isolated MARM server imports."""

import importlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _resolve_cbm_binary() -> str | None:
    env = os.environ.get("CBM_BINARY_PATH")
    if env and os.path.exists(env):
        return env
    try:
        from codebase_memory_mcp import _cli

        binary_path = _cli._bin_path(_cli._version())
        if binary_path.exists():
            return str(binary_path)
    except Exception:
        pass
    return None


_CBM_BINARY = _resolve_cbm_binary()
if _CBM_BINARY:
    os.environ.setdefault("CBM_BINARY_PATH", _CBM_BINARY)

requires_binary = pytest.mark.skipif(
    _CBM_BINARY is None,
    reason="codebase-memory-mcp binary not available (offline / not downloaded)",
)


def load_isolated_server(monkeypatch, tmp_path, api_key="", write_queue_enabled=False):
    """Import the server after pointing global state at a temporary database."""
    for name in list(sys.modules):
        if (
            name == "marm_mcp_server"
            or name.startswith("marm_mcp_server.")
            or name == "marm_dashboard"
            or name.startswith("marm_dashboard.")
        ):
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


def init_dashboard_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (
                session_name TEXT PRIMARY KEY,
                marm_active BOOLEAN DEFAULT FALSE,
                last_accessed TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                session_name TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB,
                timestamp TEXT NOT NULL,
                context_type TEXT DEFAULT 'general',
                metadata TEXT,
                compaction_role TEXT DEFAULT NULL,
                compacted_into TEXT DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE log_entries (
                id TEXT PRIMARY KEY,
                session_name TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                full_entry TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE notebook_entries (
                name TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                embedding BLOB,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE compaction_staging (
                id TEXT PRIMARY KEY,
                session_name TEXT NOT NULL,
                source_memory_ids TEXT NOT NULL,
                preview TEXT NOT NULL,
                suggested_summary TEXT,
                status TEXT NOT NULL DEFAULT 'pending_summary',
                candidate_hash TEXT NOT NULL,
                source_updated_at_snapshot TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reviewed_at TEXT,
                nudge_count INTEGER NOT NULL DEFAULT 0,
                last_nudged_at TEXT
            );
            """
        )


def load_dashboard(monkeypatch, tmp_path, api_key=""):
    for name in list(sys.modules):
        if name == "marm_dashboard" or name.startswith("marm_dashboard."):
            del sys.modules[name]

    db_path = tmp_path / "marm_memory.db"
    init_dashboard_db(db_path)
    monkeypatch.setenv("MARM_DB_PATH", str(db_path))
    monkeypatch.setenv("MARM_DASHBOARD_HOST", "127.0.0.1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    if api_key:
        monkeypatch.setenv("MARM_API_KEY", api_key)
    else:
        monkeypatch.delenv("MARM_API_KEY", raising=False)

    server = importlib.import_module("marm_dashboard.server")
    db_module = importlib.import_module("marm_dashboard.db")
    db_module._ENCODER_FAILED = True
    return server


def local_client(app):
    return TestClient(app, client=("127.0.0.1", 50000))


def remote_client(app):
    return TestClient(app, client=("10.0.0.25", 50000))


@pytest.fixture(scope="session")
def binary() -> str:
    if _CBM_BINARY is None:
        pytest.skip("binary unavailable")
    return _CBM_BINARY


@pytest.fixture(scope="session")
def graph_client(binary):
    from marm_graph.core.cbm_client import CbmClient
    from marm_graph.config import settings as graph_settings

    graph_settings.STORE_DIR.mkdir(parents=True, exist_ok=True)
    client = CbmClient(
        command=[binary],
        cwd=graph_settings.CBM_CWD,
        startup_timeout=90,
        call_timeout=180,
    )
    client.start()
    yield client
    client.close()


@pytest.fixture(scope="session")
def graph_project(graph_client) -> str:
    """Index the packaged marm_graph source and return the derived project name."""
    package_root = Path(__file__).resolve().parents[1] / "marm_graph"
    result = graph_client.call_tool(
        "index_repository", {"repo_path": str(package_root), "mode": "moderate"}
    )
    name = result.get("project")
    assert name, f"index_repository returned no project name: {result}"
    return name


@pytest.fixture(scope="session")
def client(graph_client):
    """Compatibility alias for tests moved from the standalone marm-graph suite."""
    return graph_client


@pytest.fixture(scope="session")
def project(graph_project):
    """Compatibility alias for tests moved from the standalone marm-graph suite."""
    return graph_project
