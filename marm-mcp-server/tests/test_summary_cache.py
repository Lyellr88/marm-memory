import importlib
import sqlite3
import uuid

from conftest import load_isolated_server, local_client


def _insert_log_entry(
    db_path, session, content, entry_date="2026-01-01", topic="general"
):
    entry_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (entry_id, session, entry_date, topic, content, content),
        )
    return entry_id


def _cache_row(db_path, session):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT summary_text, entry_count, dirty FROM session_summary_cache WHERE session_name = ?",
            (session,),
        ).fetchone()


def test_db_init_creates_session_summary_cache(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    db_path = str(tmp_path / "marm_memory.db")
    with sqlite3.connect(db_path) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "session_summary_cache" in tables
    assert "session_summary_chunks" not in tables


def test_first_summary_builds_cache_row(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    _insert_log_entry(db_path, "s1", "decision: use docker stdio")

    assert _cache_row(db_path, "s1") is None

    resp = client.get("/marm_summary", params={"session_name": "s1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    row = _cache_row(db_path, "s1")
    assert row is not None
    assert row[2] == 0
    assert "docker stdio" in row[0]


def test_second_summary_uses_clean_cache(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    _insert_log_entry(db_path, "s2", "initial entry")

    client.get("/marm_summary", params={"session_name": "s2"})

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE session_summary_cache SET summary_text = 'CACHED_SENTINEL', dirty = 0 WHERE session_name = ?",
            ("s2",),
        )

    resp = client.get("/marm_summary", params={"session_name": "s2"})
    assert resp.status_code == 200
    assert "CACHED_SENTINEL" in resp.json()["summary"]


def test_log_entry_marks_cache_dirty(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    _insert_log_entry(db_path, "s3", "first entry")
    client.get("/marm_summary", params={"session_name": "s3"})
    assert _cache_row(db_path, "s3")[2] == 0
    client.post(
        "/marm_log_entry",
        json={"session_name": "s3", "entry": "2026-01-02-work-second entry"},
    )

    assert _cache_row(db_path, "s3")[2] == 1


def test_dirty_cache_rebuilds_with_new_entry(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    _insert_log_entry(db_path, "s4", "original entry")
    client.get("/marm_summary", params={"session_name": "s4"})

    client.post(
        "/marm_log_entry",
        json={"session_name": "s4", "entry": "2026-01-02-work-new entry added"},
    )

    resp = client.get("/marm_summary", params={"session_name": "s4"})
    assert resp.status_code == 200
    assert "new entry added" in resp.json()["summary"]
    assert _cache_row(db_path, "s4")[2] == 0


def test_single_entry_delete_marks_cache_dirty(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    entry_id = _insert_log_entry(db_path, "s5", "entry to delete")
    client.get("/marm_summary", params={"session_name": "s5"})
    assert _cache_row(db_path, "s5")[2] == 0

    client.post(
        "/marm_delete", json={"type": "log", "session_name": "s5", "target": entry_id}
    )

    assert _cache_row(db_path, "s5")[2] == 1


def test_full_session_delete_removes_cache_row(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    _insert_log_entry(db_path, "s6", "some entry")
    client.get("/marm_summary", params={"session_name": "s6"})
    assert _cache_row(db_path, "s6") is not None

    client.post("/marm_delete", json={"type": "log", "target": "s6"})

    assert _cache_row(db_path, "s6") is None


def test_full_session_delete_survives_missing_summary_cache_table(
    monkeypatch, tmp_path
):
    """log-entry-dedup.md: the whole-session marm_delete branch now guards
    its session_summary_cache DELETE in try/except (matching every other
    cache-invalidation call site in services/log_entry.py) instead of
    letting a cache failure abort the log_entries/sessions/memories
    deletes that come after it. Dropping the table is a real, not
    synthetic, way to force that DELETE to raise."""
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    _insert_log_entry(db_path, "s7", "entry that must still be deleted")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE session_summary_cache")

    resp = client.post("/marm_delete", json={"type": "log", "target": "s7"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    with sqlite3.connect(db_path) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE session_name = ?", ("s7",)
        ).fetchone()[0]
    assert remaining == 0


def test_disposable_mode_deletes_clean_cache_after_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("MARM_SUMMARY_CACHE_DISPOSABLE", "1")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    _insert_log_entry(db_path, "s7", "disposable entry")

    resp = client.get("/marm_summary", params={"session_name": "s7"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    assert _cache_row(db_path, "s7") is None


def test_oversized_summary_trims_to_content_limit(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    response_limiter = importlib.import_module("marm_mcp_server.core.response_limiter")
    monkeypatch.setattr(response_limiter.MCPResponseLimiter, "CONTENT_LIMIT", 300)

    for i in range(5):
        _insert_log_entry(
            db_path, "s8", f"entry {i} " + "x" * 180, entry_date=f"2026-0{i + 1}-01"
        )

    resp = client.get("/marm_summary", params={"session_name": "s8"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body.get("_mcp_truncated") is True
    assert (
        response_limiter.MCPResponseLimiter.estimate_response_size(body)
        <= response_limiter.MCPResponseLimiter.CONTENT_LIMIT
    )


def test_cache_with_mismatched_entry_count_forces_rebuild(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = str(tmp_path / "marm_memory.db")

    _insert_log_entry(db_path, "s9", "entry one")
    client.get("/marm_summary", params={"session_name": "s9"})

    _insert_log_entry(db_path, "s9", "entry two silently added")

    resp = client.get("/marm_summary", params={"session_name": "s9"})
    assert "entry two silently added" in resp.json()["summary"]
