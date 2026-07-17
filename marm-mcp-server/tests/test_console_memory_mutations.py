import asyncio
import json
import sqlite3

from fastapi.testclient import TestClient

from conftest import load_isolated_server


def _stop_queue() -> None:
    from marm_mcp_server.core.memory import memory

    asyncio.run(memory.stop_write_queue())


def test_internal_memory_mutations_use_queue_and_keep_indexes(monkeypatch, tmp_path):
    concept_db_path = tmp_path / "marm_index.db"
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(concept_db_path))
    server = load_isolated_server(
        monkeypatch, tmp_path, api_key="test-key", write_queue_enabled=True
    )
    headers = {"Authorization": "Bearer test-key"}

    try:
        with TestClient(server.app) as client:
            create = client.post(
                "/internal/memories",
                headers=headers,
                json={
                    "content": "Original console memory",
                    "session_name": "console-session",
                    "context_type": "decision",
                    "project": "marm-console",
                    "platform": "",
                    "metadata": {"source": "console"},
                },
            )
            assert create.status_code == 201
            created = create.json()
            memory_id = created["id"]
            assert created["project"] == "marm-console"
            assert created["platform"] is None

            db_path = tmp_path / "marm_memory.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding) "
                    "VALUES (?, 0, 'stale chunk', ?)",
                    (memory_id, b"1234"),
                )
                conn.commit()

            replace = client.put(
                f"/internal/memories/{memory_id}",
                headers=headers,
                json={
                    "content": "Replacement console memory",
                    "session_name": "console-session",
                    "context_type": "note",
                    "project": "",
                    "platform": "claude-code",
                    "metadata": {"edited": True},
                },
            )
            assert replace.status_code == 200
            updated = replace.json()
            assert updated["content"] == "Replacement console memory"
            assert updated["project"] is None
            assert updated["platform"] == "claude-code"

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT content, metadata FROM memories WHERE id = ?",
                    (memory_id,),
                ).fetchone()
                assert row[0] == "Replacement console memory"
                assert "[merged]" not in row[0]
                assert json.loads(row[1]) == {"edited": True}
                chunk_count = conn.execute(
                    "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?",
                    (memory_id,),
                ).fetchone()[0]
                assert chunk_count == 0
                fts_count = conn.execute(
                    "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'Replacement'",
                ).fetchone()[0]
                assert fts_count == 1

            from marm_mcp_server.core.concept_db import ConceptDB

            concept_db = ConceptDB(str(concept_db_path))
            with concept_db.get_connection() as conn:
                entity_a, _ = concept_db.get_or_create_entity(
                    conn,
                    "Console",
                    "component",
                    "console-session",
                    "marm-console",
                    memory_id,
                )
                entity_b, _ = concept_db.get_or_create_entity(
                    conn,
                    "MARM",
                    "system",
                    "console-session",
                    "marm-console",
                    "other-memory",
                )
                conn.execute(
                    "UPDATE entities SET source_memory_ids = ? WHERE id = ?",
                    (json.dumps([memory_id, "other-memory"]), entity_a),
                )
                concept_db.store_relationship(
                    conn, entity_a, entity_b, "references", memory_id, "marm-console"
                )

            delete = client.request(
                "DELETE",
                f"/internal/memories/{memory_id}",
                headers=headers,
                json={"confirm": "DELETE"},
            )
            assert delete.status_code == 200
            deleted = delete.json()
            assert deleted["deleted_ids"] == [memory_id]
            assert deleted["concept_cleanup"]["status"] == "success"

            with sqlite3.connect(db_path) as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM memories WHERE id = ?", (memory_id,)
                    ).fetchone()[0]
                    == 0
                )
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH 'Replacement'",
                    ).fetchone()[0]
                    == 0
                )

            with sqlite3.connect(concept_db_path) as conn:
                source_ids = conn.execute(
                    "SELECT source_memory_ids FROM entities WHERE id = ?", (entity_a,)
                ).fetchone()[0]
                assert json.loads(source_ids) == ["other-memory"]
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM relationships WHERE memory_id = ?",
                        (memory_id,),
                    ).fetchone()[0]
                    == 0
                )
    finally:
        _stop_queue()


def test_internal_bulk_delete_is_bounded_and_reports_missing(monkeypatch, tmp_path):
    server = load_isolated_server(
        monkeypatch, tmp_path, api_key="test-key", write_queue_enabled=True
    )
    headers = {"Authorization": "Bearer test-key"}

    try:
        with TestClient(server.app) as client:
            first = client.post(
                "/internal/memories",
                headers=headers,
                json={"content": "First", "session_name": "bulk"},
            ).json()["id"]
            second = client.post(
                "/internal/memories",
                headers=headers,
                json={"content": "Second", "session_name": "bulk"},
            ).json()["id"]

            bad_confirm = client.post(
                "/internal/memories/bulk-delete",
                headers=headers,
                json={"memory_ids": [first], "confirm": "yes"},
            )
            assert bad_confirm.status_code == 422
            empty = client.post(
                "/internal/memories/bulk-delete",
                headers=headers,
                json={"memory_ids": [], "confirm": "DELETE"},
            )
            assert empty.status_code == 422
            unbounded = client.post(
                "/internal/memories/bulk-delete",
                headers=headers,
                json={
                    "memory_ids": [f"mem-{index}" for index in range(101)],
                    "confirm": "DELETE",
                },
            )
            assert unbounded.status_code == 422

            result = client.post(
                "/internal/memories/bulk-delete",
                headers=headers,
                json={
                    "memory_ids": [first, second, "missing-memory"],
                    "confirm": "DELETE",
                },
            )
            assert result.status_code == 200
            payload = result.json()
            assert payload["deleted_ids"] == sorted([first, second])
            assert payload["missing_ids"] == ["missing-memory"]
    finally:
        _stop_queue()


def test_console_create_dedupes_only_within_explicit_scope(monkeypatch, tmp_path):
    server = load_isolated_server(
        monkeypatch, tmp_path, api_key="test-key", write_queue_enabled=True
    )
    from marm_mcp_server.core import memory_ops as memory_ops_module

    monkeypatch.setattr(memory_ops_module, "CONSOLIDATION_ENABLED", True)
    headers = {"Authorization": "Bearer test-key"}

    try:
        with TestClient(server.app) as client:
            first = client.post(
                "/internal/memories",
                headers=headers,
                json={
                    "content": "Scoped duplicate memory",
                    "session_name": "console-scope",
                    "project": "alpha",
                },
            )
            assert first.status_code == 201
            first_id = first.json()["id"]

            second = client.post(
                "/internal/memories",
                headers=headers,
                json={
                    "content": "Scoped duplicate memory",
                    "session_name": "console-scope",
                    "project": "beta",
                },
            )
            assert second.status_code == 201
            second_id = second.json()["id"]

            third = client.post(
                "/internal/memories",
                headers=headers,
                json={
                    "content": "Scoped duplicate memory",
                    "session_name": "console-scope",
                    "project": "alpha",
                },
            )
            assert third.status_code == 201
            third_id = third.json()["id"]

        assert first_id != second_id
        assert third_id == first_id

        with sqlite3.connect(tmp_path / "marm_memory.db") as conn:
            rows = conn.execute(
                "SELECT project, COUNT(*) FROM memories GROUP BY project ORDER BY project"
            ).fetchall()
        assert rows == [("alpha", 1), ("beta", 1)]
    finally:
        _stop_queue()


def test_internal_memory_mutation_rejects_disabled_write_queue(monkeypatch, tmp_path):
    server = load_isolated_server(
        monkeypatch, tmp_path, api_key="test-key", write_queue_enabled=False
    )

    with TestClient(server.app) as client:
        response = client.post(
            "/internal/memories",
            headers={"Authorization": "Bearer test-key"},
            json={"content": "No direct writes", "session_name": "console"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "memory write queue is unavailable"
