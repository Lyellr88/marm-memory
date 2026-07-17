from fastapi.testclient import TestClient

from server import app as console_app
from server import memory_store


def test_memory_mutation_routes_proxy_to_marm_runtime(monkeypatch):
    calls = []

    def fake_request(
        operation: str,
        payload: dict | None = None,
        *,
        method: str = "POST",
        timeout: float = 10.0,
    ) -> dict:
        calls.append((method, operation, payload, timeout))
        if operation == "internal/projects/list":
            return {"projects": []}
        if operation == "internal/memories" and method == "POST":
            return {"id": "mem-1", **payload}
        if operation == "internal/memories/mem-1" and method == "PUT":
            return {"id": "mem-1", **payload}
        if operation == "internal/memories/mem-1" and method == "DELETE":
            return {"deleted_ids": ["mem-1"], "missing_ids": []}
        if operation == "internal/memories/bulk-delete":
            return {"deleted_ids": payload["memory_ids"], "missing_ids": []}
        raise AssertionError(f"unexpected operation: {method} {operation}")

    monkeypatch.setattr(console_app.mcp_client, "request", fake_request)

    with TestClient(console_app.app) as client:
        create = client.post(
            "/api/memories",
            json={
                "content": "Console write",
                "session_name": "session",
                "context_type": "decision",
                "project": "marm-console",
            },
        )
        assert create.status_code == 201
        assert create.json()["id"] == "mem-1"

        update = client.put(
            "/api/memories/mem-1",
            json={
                "content": "Edited write",
                "session_name": "session",
                "context_type": None,
                "project": None,
                "platform": "cursor",
                "metadata": {"edited": True},
            },
        )
        assert update.status_code == 200
        assert update.json()["content"] == "Edited write"

        delete = client.request(
            "DELETE",
            "/api/memories/mem-1",
            json={"confirm": "DELETE"},
        )
        assert delete.status_code == 200
        assert delete.json()["deleted_ids"] == ["mem-1"]

        bulk = client.post(
            "/api/memories/bulk-delete",
            json={"memory_ids": ["mem-1", "mem-2"], "confirm": "DELETE"},
        )
        assert bulk.status_code == 200
        assert bulk.json()["deleted_ids"] == ["mem-1", "mem-2"]

    memory_calls = [call for call in calls if call[1].startswith("internal/memories")]
    assert memory_calls == [
        (
            "POST",
            "internal/memories",
            {
                "content": "Console write",
                "session_name": "session",
                "context_type": "decision",
                "project": "marm-console",
                "platform": None,
                "metadata": None,
            },
            30.0,
        ),
        (
            "PUT",
            "internal/memories/mem-1",
            {
                "content": "Edited write",
                "session_name": "session",
                "context_type": "general",
                "project": None,
                "platform": "cursor",
                "metadata": {"edited": True},
            },
            30.0,
        ),
        (
            "DELETE",
            "internal/memories/mem-1",
            {"confirm": "DELETE"},
            30.0,
        ),
        (
            "POST",
            "internal/memories/bulk-delete",
            {"memory_ids": ["mem-1", "mem-2"], "confirm": "DELETE"},
            30.0,
        ),
    ]


def test_concept_link_counts_are_best_effort(monkeypatch, tmp_path):
    concept_db_path = tmp_path / "marm_index.db"
    concept_db_path.write_text("not a sqlite database", encoding="utf-8")
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(concept_db_path))

    assert memory_store._concept_link_counts(["mem-1"]) == {}
