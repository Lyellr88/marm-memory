import importlib
import sqlite3
import sys

from fastapi.testclient import TestClient


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
