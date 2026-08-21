import sqlite3

from fastapi.testclient import TestClient

from marm_mcp_server.console.app import app
from marm_mcp_server.console.endpoints import logs
from marm_mcp_server.core.memory_db import init_database


def test_console_logs_return_a_bounded_page_with_total(monkeypatch, tmp_path):
    db_path = tmp_path / "marm_memory.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as connection:
        for index in range(3):
            connection.execute(
                """
                INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"log-{index}",
                    "console-pagination",
                    f"2026-08-2{index}T00:00:00+00:00",
                    "console",
                    f"Log {index}",
                    f"Full log {index}",
                ),
            )

    monkeypatch.setattr(logs, "get_memory_db_path", lambda: db_path)
    with TestClient(app) as client:
        response = client.get(
            "/api/logs?session=console-pagination&limit=1&offset=1"
        )

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert page["limit"] == 1
    assert page["offset"] == 1
    assert [item["id"] for item in page["items"]] == ["log-1"]
