import sqlite3
from datetime import datetime, timedelta, timezone

from conftest import load_dashboard, local_client


def _future_iso(days=30):
    return (
        (datetime.now(timezone.utc) + timedelta(days=days))
        .isoformat()
        .replace("+00:00", "Z")
    )


def test_compaction_memories_list_excludes_compacted_sources(monkeypatch, tmp_path):
    """Eligible memories exclude those already marked as compacted sources."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO memories (id, session_name, content, timestamp, context_type, compaction_role, compacted_into) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "m1",
                    "main",
                    "eligible memory 1",
                    "2026-01-01T10:00:00Z",
                    "general",
                    None,
                    None,
                ),
                (
                    "m2",
                    "main",
                    "eligible memory 2",
                    "2026-01-01T11:00:00Z",
                    "general",
                    None,
                    None,
                ),
                (
                    "m3",
                    "main",
                    "compacted source",
                    "2026-01-01T09:00:00Z",
                    "general",
                    "source",
                    "summary-1",
                ),
                (
                    "summary-1",
                    "main",
                    "this is summary",
                    "2026-01-01T12:00:00Z",
                    "general",
                    "summary",
                    None,
                ),
            ],
        )
        conn.commit()

    result = client.get("/api/compaction/memories", params={"session": "main"}).json()

    assert result["total"] == 2
    ids = {item["id"] for item in result["items"]}
    assert ids == {"m1", "m2"}
    assert "m3" not in ids
    assert "summary-1" not in ids


def test_compaction_preview_generates_summary_with_savings(monkeypatch, tmp_path):
    """Preview endpoint returns summary, source count, and token savings estimate."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO memories (id, session_name, content, timestamp, context_type) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "00000000-0000-4000-8000-000000000001",
                    "preview-test",
                    "Memory about Docker deployment process with detailed steps",
                    "2026-01-01T10:00:00Z",
                    "general",
                ),
                (
                    "00000000-0000-4000-8000-000000000002",
                    "preview-test",
                    "Another memory discussing Docker configuration settings",
                    "2026-01-01T11:00:00Z",
                    "general",
                ),
                (
                    "00000000-0000-4000-8000-000000000003",
                    "preview-test",
                    "Final memory covering Docker troubleshooting techniques",
                    "2026-01-01T12:00:00Z",
                    "general",
                ),
            ],
        )
        conn.commit()

    preview = client.post(
        "/api/compaction/preview",
        json={
            "memory_ids": [
                "00000000-0000-4000-8000-000000000001",
                "00000000-0000-4000-8000-000000000002",
                "00000000-0000-4000-8000-000000000003",
            ]
        },
    ).json()

    assert preview["source_count"] == 3
    assert "summary" in preview
    assert len(preview["summary"]) > 0
    assert "token_savings_estimate" in preview
    assert "%" in preview["token_savings_estimate"]
    assert "sources_preview" in preview
    assert len(preview["sources_preview"]) == 3


def test_compaction_preview_rejects_invalid_uuids(monkeypatch, tmp_path):
    """Preview endpoint validates memory IDs to prevent SQL injection."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    # Invalid UUID formats should return 400
    response = client.post(
        "/api/compaction/preview",
        json={
            "memory_ids": [
                "123e4567-e89b-12d3-a456-426614174000",
                "'; DROP TABLE memories; --",
            ]
        },
    )

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


def test_compaction_apply_creates_summary_and_marks_sources(monkeypatch, tmp_path):
    """Apply endpoint creates summary memory and marks sources as compacted."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO memories (id, session_name, content, timestamp, context_type) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "00000000-0000-4000-8000-000000000011",
                    "apply-test",
                    "source memory 1",
                    "2026-01-01T10:00:00Z",
                    "general",
                ),
                (
                    "00000000-0000-4000-8000-000000000012",
                    "apply-test",
                    "source memory 2",
                    "2026-01-01T11:00:00Z",
                    "general",
                ),
            ],
        )
        conn.commit()

    result = client.post(
        "/api/compaction/apply",
        json={
            "memory_ids": [
                "00000000-0000-4000-8000-000000000011",
                "00000000-0000-4000-8000-000000000012",
            ],
            "summary_content": "Combined summary of both memories",
            "session_name": "apply-test",
        },
    ).json()

    assert result["status"] == "applied"
    assert result["source_count"] == 2
    summary_id = result["summary_id"]

    with sqlite3.connect(db_path) as conn:
        # Verify summary was created
        summary = conn.execute(
            "SELECT id, session_name, content, compaction_role FROM memories WHERE id = ?",
            (summary_id,),
        ).fetchone()
        assert summary is not None
        assert summary[2] == "Combined summary of both memories"  # content
        assert summary[3] == "summary"  # compaction_role

        # Verify sources were marked
        sources = conn.execute(
            "SELECT id, compaction_role, compacted_into FROM memories WHERE id IN ('00000000-0000-4000-8000-000000000011', '00000000-0000-4000-8000-000000000012')"
        ).fetchall()
        assert len(sources) == 2
        for row in sources:
            assert row[1] == "source"
            assert row[2] == summary_id

        # Verify staging record was created with actual source memory IDs
        staging_row = conn.execute(
            "SELECT status, source_memory_ids FROM compaction_staging WHERE session_name = ?",
            ("apply-test",),
        ).fetchone()
        assert staging_row is not None
        assert staging_row[0] == "applied"

        # Verify source_memory_ids contains the actual source IDs, not summary_id
        import json as test_json

        source_ids = test_json.loads(staging_row[1])
        assert set(source_ids) == {
            "00000000-0000-4000-8000-000000000011",
            "00000000-0000-4000-8000-000000000012",
        }


def test_compaction_apply_rejects_cross_session_memories(monkeypatch, tmp_path):
    """Apply endpoint rejects memories from different sessions."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO memories (id, session_name, content, timestamp, context_type) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "00000000-0000-4000-8000-000000000021",
                    "session-a",
                    "memory in session A",
                    "2026-01-01T10:00:00Z",
                    "general",
                ),
                (
                    "00000000-0000-4000-8000-000000000022",
                    "session-b",
                    "memory in session B",
                    "2026-01-01T11:00:00Z",
                    "general",
                ),
            ],
        )
        conn.commit()

    response = client.post(
        "/api/compaction/apply",
        json={
            "memory_ids": [
                "00000000-0000-4000-8000-000000000021",
                "00000000-0000-4000-8000-000000000022",
            ],
            "summary_content": "invalid cross-session summary",
            "session_name": "session-a",
        },
    )

    assert response.status_code == 400
    assert "session" in response.json()["detail"].lower()


def test_compaction_memories_pagination_works(monkeypatch, tmp_path):
    """Compaction memories list supports limit and offset pagination."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        for i in range(5):
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp, context_type) VALUES (?, ?, ?, ?, ?)",
                (
                    f"page-{i}",
                    "pager",
                    f"memory {i}",
                    "2026-01-01T10:00:00Z",
                    "general",
                ),
            )
        conn.commit()

    page1 = client.get(
        "/api/compaction/memories", params={"limit": 2, "offset": 0}
    ).json()
    page2 = client.get(
        "/api/compaction/memories", params={"limit": 2, "offset": 2}
    ).json()

    assert page1["total"] == 5
    assert len(page1["items"]) == 2
    assert page2["total"] == 5
    assert len(page2["items"]) == 2
    assert {i["id"] for i in page1["items"]}.isdisjoint(
        {i["id"] for i in page2["items"]}
    )


def test_maintenance_compaction_summary_counts_by_status(monkeypatch, tmp_path):
    """Maintenance summary endpoint returns counts grouped by status."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"
    future_expires_at = _future_iso()

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO compaction_staging (id, session_name, source_memory_ids, preview, status, candidate_hash, source_updated_at_snapshot, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "c1",
                    "main",
                    '["m1","m2"]',
                    "preview",
                    "pending_summary",
                    "hash1",
                    "{}",
                    future_expires_at,
                    "2026-01-01T10:00:00Z",
                    "2026-01-01T10:00:00Z",
                ),
                (
                    "c2",
                    "main",
                    '["m3","m4"]',
                    "preview",
                    "summary_staged",
                    "hash2",
                    "{}",
                    future_expires_at,
                    "2026-01-01T11:00:00Z",
                    "2026-01-01T11:00:00Z",
                ),
                (
                    "c3",
                    "main",
                    '["m5","m6"]',
                    "preview",
                    "applied",
                    "hash3",
                    "{}",
                    future_expires_at,
                    "2026-01-01T12:00:00Z",
                    "2026-01-01T12:00:00Z",
                ),
                (
                    "c4",
                    "main",
                    '["m7"]',
                    "preview",
                    "stale",
                    "hash4",
                    "{}",
                    "2026-01-02T00:00:00Z",
                    "2026-01-01T13:00:00Z",
                    "2026-01-01T13:00:00Z",
                ),
            ],
        )
        conn.commit()

    summary = client.get("/api/maintenance/compaction-summary").json()

    assert summary["pending_summary"] == 1
    assert summary["summary_staged"] == 1
    assert summary["applied"] == 1
    assert summary["stale"] == 1
    assert summary["discarded"] == 0


def test_maintenance_candidates_filters_by_session(monkeypatch, tmp_path):
    """Maintenance candidates list filters by session name."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"
    future_expires_at = _future_iso()

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO compaction_staging (id, session_name, source_memory_ids, preview, status, candidate_hash, source_updated_at_snapshot, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "cf1",
                    "alpha",
                    '["m1"]',
                    "alpha preview",
                    "pending_summary",
                    "h1",
                    "{}",
                    future_expires_at,
                    "2026-01-01T10:00:00Z",
                    "2026-01-01T10:00:00Z",
                ),
                (
                    "cf2",
                    "beta",
                    '["m2"]',
                    "beta preview",
                    "pending_summary",
                    "h2",
                    "{}",
                    future_expires_at,
                    "2026-01-01T11:00:00Z",
                    "2026-01-01T11:00:00Z",
                ),
            ],
        )
        conn.commit()

    all_candidates = client.get("/api/maintenance/candidates").json()
    assert all_candidates["total"] == 2

    alpha_only = client.get(
        "/api/maintenance/candidates", params={"session": "alpha"}
    ).json()
    assert alpha_only["total"] == 1
    assert alpha_only["items"][0]["session_name"] == "alpha"


def test_maintenance_candidates_filters_by_status(monkeypatch, tmp_path):
    """Maintenance candidates list filters by status."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"
    future_expires_at = _future_iso()

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO compaction_staging (id, session_name, source_memory_ids, preview, status, candidate_hash, source_updated_at_snapshot, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "st1",
                    "main",
                    '["m1"]',
                    "preview",
                    "pending_summary",
                    "h1",
                    "{}",
                    future_expires_at,
                    "2026-01-01T10:00:00Z",
                    "2026-01-01T10:00:00Z",
                ),
                (
                    "st2",
                    "main",
                    '["m2"]',
                    "preview",
                    "applied",
                    "h2",
                    "{}",
                    future_expires_at,
                    "2026-01-01T11:00:00Z",
                    "2026-01-01T11:00:00Z",
                ),
            ],
        )
        conn.commit()

    pending_only = client.get(
        "/api/maintenance/candidates", params={"status": "pending_summary"}
    ).json()
    assert pending_only["total"] == 1
    assert pending_only["items"][0]["status"] == "pending_summary"

    applied_only = client.get(
        "/api/maintenance/candidates", params={"status": "applied"}
    ).json()
    assert applied_only["total"] == 1
    assert applied_only["items"][0]["status"] == "applied"


def test_maintenance_discard_candidate_marks_as_discarded(monkeypatch, tmp_path):
    """Discard endpoint updates candidate status to discarded."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"
    future_expires_at = _future_iso()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO compaction_staging (id, session_name, source_memory_ids, preview, status, candidate_hash, source_updated_at_snapshot, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "00000000-0000-4000-8000-000000000031",
                "main",
                '["m1"]',
                "preview",
                "pending_summary",
                "h1",
                "{}",
                future_expires_at,
                "2026-01-01T10:00:00Z",
                "2026-01-01T10:00:00Z",
            ),
        )
        conn.commit()

    result = client.post(
        "/api/maintenance/candidates/00000000-0000-4000-8000-000000000031/discard"
    ).json()
    assert result["status"] == "discarded"
    assert result["id"] == "00000000-0000-4000-8000-000000000031"

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, reviewed_at FROM compaction_staging WHERE id = ?",
            ("00000000-0000-4000-8000-000000000031",),
        ).fetchone()
        assert row[0] == "discarded"
        assert row[1] is not None


def test_maintenance_discard_nonexistent_candidate_returns_404(monkeypatch, tmp_path):
    """Discard endpoint returns 404 for nonexistent candidate."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.commit()

    response = client.post("/api/maintenance/candidates/nonexistent-id/discard")
    assert response.status_code == 404


def test_maintenance_candidates_parses_source_memory_ids_json(monkeypatch, tmp_path):
    """Candidates endpoint safely parses source_memory_ids JSON array."""
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"
    future_expires_at = _future_iso()

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO compaction_staging (id, session_name, source_memory_ids, preview, status, candidate_hash, source_updated_at_snapshot, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "json1",
                    "main",
                    '["id1","id2","id3"]',
                    "preview",
                    "pending_summary",
                    "h1",
                    "{}",
                    future_expires_at,
                    "2026-01-01T10:00:00Z",
                    "2026-01-01T10:00:00Z",
                ),
                (
                    "json2",
                    "main",
                    "invalid json",
                    "preview",
                    "pending_summary",
                    "h2",
                    "{}",
                    future_expires_at,
                    "2026-01-01T11:00:00Z",
                    "2026-01-01T11:00:00Z",
                ),
            ],
        )
        conn.commit()

    result = client.get("/api/maintenance/candidates").json()

    valid = next(item for item in result["items"] if item["id"] == "json1")
    assert valid["source_memory_ids"] == ["id1", "id2", "id3"]
    assert valid["source_count"] == 3

    invalid = next(item for item in result["items"] if item["id"] == "json2")
    assert invalid["source_memory_ids"] == []
    assert invalid["source_count"] == 0
