"""Console Memory tab gap route tests with the MCP adapter stubbed."""

import sqlite3

from fastapi.testclient import TestClient

from server import app as console_app
from server import memory_store


def _memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "marm_memory.db"
    monkeypatch.setenv("MARM_DB_PATH", str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (
                session_name TEXT PRIMARY KEY,
                marm_active INTEGER DEFAULT 0,
                created_at TEXT,
                last_accessed TEXT
            );

            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                session_name TEXT NOT NULL,
                content TEXT NOT NULL,
                project TEXT,
                platform TEXT
            );

            CREATE TABLE log_entries (
                id TEXT PRIMARY KEY,
                session_name TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                full_entry TEXT NOT NULL,
                project TEXT,
                platform TEXT
            );

            CREATE TABLE compaction_staging (
                id TEXT PRIMARY KEY,
                session_name TEXT NOT NULL
            );

            CREATE TABLE notebook_entries (
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                project TEXT,
                platform TEXT,
                created_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (name, project, platform)
            );
            """
        )
    return db_path


def test_session_log_notebook_and_compaction_mutations_proxy_to_marm(monkeypatch):
    calls = []

    def fake_post(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
        calls.append((operation, payload, timeout))
        responses = {
            "internal/projects/list": {"projects": []},
            "marm_start": {
                "status": "success",
                "session_name": payload.get("session_name"),
                "marm_active": True,
            },
            "marm_delete": {
                "status": "success",
                "deleted_count": 1,
                "memories_deleted": 1,
                "deleted": True,
            },
            "marm_notebook": {
                "status": "success",
                "name": payload.get("name"),
            },
            "marm_compaction": {
                "status": "success",
                "candidate_id": payload.get("candidate_id"),
            },
        }
        return responses[operation]

    monkeypatch.setattr(console_app.mcp_client, "post", fake_post)
    monkeypatch.setattr(
        memory_store,
        "list_sessions",
        lambda db_path: [
            {
                "name": "main",
                "active": True,
                "created_at": "2026-07-17T00:00:00+00:00",
                "last_accessed_at": "2026-07-17T00:00:00+00:00",
                "memory_count": 1,
                "log_count": 1,
                "compaction_count": 0,
                "projects": [],
                "platforms": [],
            }
        ],
    )
    monkeypatch.setattr(
        memory_store,
        "list_log_refs",
        lambda db_path: [{"id": "123", "session_name": "main"}],
    )
    monkeypatch.setattr(
        memory_store,
        "list_notebook",
        lambda db_path: [
            {
                "name": "deploy-note",
                "content": "Ship carefully.",
                "project": None,
                "platform": None,
                "created_at": "2026-07-17T00:00:00+00:00",
                "updated_at": "2026-07-17T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(
        memory_store,
        "list_compaction",
        lambda db_path: [
            {
                "id": "cand-1",
                "status": "pending",
                "session_name": "main",
                "source_memory_ids": ["m1", "m2"],
                "proposed_summary": "Summary text",
                "expected_reduction": 42,
                "expiry": None,
                "created_at": "2026-07-17T00:00:00+00:00",
            }
        ],
    )

    with TestClient(console_app.app) as client:
        created_session = client.post("/api/sessions", json={"name": "main"})
        assert created_session.status_code == 201
        assert created_session.json()["name"] == "main"

        deleted_session = client.request(
            "DELETE", "/api/sessions/main", json={"confirm": "DELETE"}
        )
        assert deleted_session.status_code == 200
        assert deleted_session.json()["deleted_count"] == 1

        deleted_log = client.request(
            "DELETE",
            "/api/logs/123",
            json={"session_name": "main", "confirm": "DELETE"},
        )
        assert deleted_log.status_code == 200
        assert deleted_log.json()["log_id"] == "123"

        deleted_all_logs = client.request(
            "DELETE", "/api/logs", json={"confirm": "DELETE_ALL"}
        )
        assert deleted_all_logs.status_code == 200
        assert deleted_all_logs.json()["deleted_count"] == 1

        deleted_all_sessions = client.request(
            "DELETE", "/api/sessions", json={"confirm": "DELETE_ALL"}
        )
        assert deleted_all_sessions.status_code == 200
        assert deleted_all_sessions.json()["deleted_sessions"] == 1

        notebook = client.post(
            "/api/notebook",
            json={
                "name": "deploy-note",
                "content": "Ship carefully.",
                "project": "console",
                "platform": "codex",
            },
        )
        assert notebook.status_code == 200
        assert notebook.json()["name"] == "deploy-note"

        deleted_note = client.request(
            "DELETE",
            "/api/notebook/deploy-note",
            json={
                "confirm": "DELETE",
                "project": "console",
                "platform": "codex",
            },
        )
        assert deleted_note.status_code == 200
        assert deleted_note.json()["deleted"] is True

        staged = client.post("/api/compaction/cand-1/stage")
        assert staged.status_code == 200
        assert staged.json()["status"] == "staged"

        applied = client.post("/api/compaction/cand-1/apply")
        assert applied.status_code == 200
        assert applied.json()["status"] == "applied"

    memory_calls = [
        call for call in calls if not call[0].startswith("internal/projects")
    ]
    assert memory_calls == [
        ("marm_start", {"session_name": "main"}, 30.0),
        ("marm_delete", {"type": "log", "target": "main"}, 30.0),
        (
            "marm_delete",
            {"type": "log", "target": "123", "session_name": "main"},
            30.0,
        ),
        (
            "marm_delete",
            {"type": "log", "target": "123", "session_name": "main"},
            30.0,
        ),
        ("marm_delete", {"type": "log", "target": "main"}, 30.0),
        (
            "marm_notebook",
            {
                "action": "add",
                "name": "deploy-note",
                "data": "Ship carefully.",
                "project": "console",
                "platform": "codex",
            },
            30.0,
        ),
        (
            "marm_delete",
            {
                "type": "notebook",
                "target": "deploy-note",
                "project": "console",
                "platform": "codex",
            },
            30.0,
        ),
        (
            "marm_compaction",
            {
                "action": "stage",
                "summaries": [
                    {
                        "candidate_id": "cand-1",
                        "source_memory_ids": ["m1", "m2"],
                        "suggested_summary": "Summary text",
                    }
                ],
            },
            60.0,
        ),
        ("marm_compaction", {"action": "apply", "candidate_id": "cand-1"}, 60.0),
    ]


def test_log_delete_returns_404_when_marm_deletes_nothing(monkeypatch):
    monkeypatch.setattr(
        console_app.mcp_client,
        "post",
        lambda operation, payload, *, timeout=10.0: {
            "status": "success",
            "deleted_count": 0,
            "memories_deleted": 0,
        },
    )

    with TestClient(console_app.app) as client:
        response = client.request(
            "DELETE",
            "/api/logs/123",
            json={"session_name": "main", "confirm": "DELETE"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Log entry not found."


def test_bulk_session_delete_continues_after_per_session_failure(monkeypatch, tmp_path):
    calls = []
    db_path = _memory_db(tmp_path, monkeypatch)
    now = "2026-07-17T00:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO sessions (session_name, marm_active, created_at, last_accessed)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("alpha", 0, now, "2026-07-17T00:00:03+00:00"),
                ("broken", 0, now, "2026-07-17T00:00:02+00:00"),
                ("omega", 0, now, "2026-07-17T00:00:01+00:00"),
            ],
        )

    def fake_post(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
        calls.append((operation, payload, timeout))
        if payload["target"] == "broken":
            raise console_app.mcp_client.McpRequestError(503, "delete failed")
        return {
            "status": "success",
            "deleted_count": 1,
            "memories_deleted": 2,
        }

    monkeypatch.setattr(console_app.mcp_client, "post", fake_post)

    with TestClient(console_app.app) as client:
        response = client.request(
            "DELETE", "/api/sessions", json={"confirm": "DELETE_ALL"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial_success"
    assert body["deleted_sessions"] == 2
    assert body["deleted_count"] == 2
    assert body["memories_deleted"] == 4
    assert body["failed_sessions"] == [
        {"session_name": "broken", "status_code": 503, "message": "delete failed"}
    ]
    assert [call[1]["target"] for call in calls] == ["alpha", "broken", "omega"]


def test_notebook_mutations_preserve_project_platform_scope(monkeypatch, tmp_path):
    calls = []
    db_path = _memory_db(tmp_path, monkeypatch)
    now = "2026-07-17T00:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO notebook_entries
                (name, data, project, platform, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("shared", "Global rule.", None, None, now, now),
                ("shared", "Scoped rule.", "marm-console", "codex", now, now),
            ],
        )

    def fake_post(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
        calls.append((operation, payload, timeout))
        return {
            "status": "success",
            "name": payload.get("name"),
            "deleted": True,
        }

    monkeypatch.setattr(console_app.mcp_client, "post", fake_post)

    with TestClient(console_app.app) as client:
        saved = client.post(
            "/api/notebook",
            json={
                "name": "shared",
                "content": "Scoped rule.",
                "project": "marm-console",
                "platform": "codex",
            },
        )
        deleted = client.request(
            "DELETE",
            "/api/notebook/shared",
            json={
                "confirm": "DELETE",
                "project": "marm-console",
                "platform": "codex",
            },
        )

    assert saved.status_code == 200
    assert saved.json()["content"] == "Scoped rule."
    assert saved.json()["project"] == "marm-console"
    assert deleted.status_code == 200
    assert calls == [
        (
            "marm_notebook",
            {
                "action": "add",
                "name": "shared",
                "data": "Scoped rule.",
                "project": "marm-console",
                "platform": "codex",
            },
            30.0,
        ),
        (
            "marm_delete",
            {
                "type": "notebook",
                "target": "shared",
                "project": "marm-console",
                "platform": "codex",
            },
            30.0,
        ),
    ]
