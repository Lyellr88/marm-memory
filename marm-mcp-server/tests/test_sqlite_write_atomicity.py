"""Rollback regression coverage for the SQLite write-atomicity hardening
effort (docs/current/sqlite-write-atomicity-hardening.md).

Every test here forces a specific SQL statement inside an already-wrapped
BEGIN IMMEDIATE/COMMIT/ROLLBACK block to fail, then asserts the *earlier*
statement(s) in that same block did not durably apply -- proving the
transaction boundary is real, not just present. A test that only checks
the happy path does not prove rollback (see the spec's own Testing
Checklist). Coordinator-owned per the spec's Test Ownership section --
packet agents did not add tests here.
"""

import asyncio
import contextlib
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import load_isolated_server, local_client


# --- shared failure-injection helpers ---


class _FailOnStatement:
    """Wraps a real sqlite3 connection. conn.execute() raises the first
    time it sees SQL containing `trigger` (case-insensitive substring
    match); every other call -- before and after -- passes through to the
    real connection untouched."""

    def __init__(self, real, trigger):
        self._real = real
        self._trigger = trigger.upper()
        self.fired = False

    def execute(self, sql, *args, **kwargs):
        if not self.fired and isinstance(sql, str) and self._trigger in sql.upper():
            self.fired = True
            raise sqlite3.OperationalError(f"forced failure: {self._trigger}")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _fail_on(monkeypatch, mem, trigger):
    """Monkeypatch mem.get_connection so the next connection it hands out
    raises the first time SQL containing `trigger` runs."""
    real_get_connection = mem.get_connection

    @contextlib.contextmanager
    def _patched():
        with real_get_connection() as real_conn:
            yield _FailOnStatement(real_conn, trigger)

    monkeypatch.setattr(mem, "get_connection", _patched)


class _RecordingConn:
    """Wraps a real connection and appends a label to `events` the first
    time SQL matching a key in `label_map` executes. Never raises --
    used to verify call *order*, not to force failures."""

    def __init__(self, real, events, label_map):
        self._real = real
        self._events = events
        self._label_map = label_map

    def execute(self, sql, *args, **kwargs):
        if isinstance(sql, str):
            upper = sql.upper()
            for substr, label in self._label_map.items():
                if substr in upper:
                    self._events.append(label)
                    break
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _record_statements(monkeypatch, mem, events, label_map):
    real_get_connection = mem.get_connection

    @contextlib.contextmanager
    def _patched():
        with real_get_connection() as real_conn:
            yield _RecordingConn(real_conn, events, label_map)

    monkeypatch.setattr(mem, "get_connection", _patched)


# --- Packet A: services/log_entry.py ---


def test_create_log_entry_rollback_no_partial_row_on_second_statement_failure(
    monkeypatch, tmp_path
):
    """create_log_entry's final insert block: log_entries insert, then a
    sessions upsert, then a guarded cache update. Force the sessions
    upsert to fail after the log_entries insert already ran -- the whole
    block must roll back, so no log_entries row should exist afterward."""
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    # load_isolated_server wipes and re-imports the whole marm_mcp_server
    # package tree, so service modules must be imported *after* it runs --
    # importing earlier would capture a stale module the live app no
    # longer uses, and the patch below would silently target nothing.
    import marm_mcp_server.services.log_entry as log_entry

    # Seed the target session first so create_log_entry's explicit
    # session_name path is used (skips the session-switch and
    # dated-fallback blocks, which also do "INSERT INTO sessions" --
    # without this, the trigger could fire on the wrong block).
    client.post(
        "/marm_log_entry",
        json={"session_name": "atomicity-a1", "entry": "2026-01-01-seed-first entry"},
    )

    _fail_on(monkeypatch, log_entry.memory, "INSERT INTO sessions")

    resp = client.post(
        "/marm_log_entry",
        json={
            "session_name": "atomicity-a1",
            "entry": "2026-01-02-forced-should not persist",
        },
    )
    assert resp.json()["status"] == "error"

    db_path = tmp_path / "marm_memory.db"
    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE full_entry LIKE ?",
            ("%should not persist%",),
        ).fetchone()[0]
    assert count == 0, "log_entries row survived a rolled-back transaction"


def test_whole_session_delete_rollback_keeps_rows_on_late_failure(
    monkeypatch, tmp_path
):
    """delete_log_or_notebook_entry's whole-session branch: sessions
    delete, log_entries delete, guarded cache delete, memories delete.
    Force the memories delete (the last statement) to fail -- sessions
    and log_entries rows must still exist afterward."""
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    import marm_mcp_server.services.log_entry as log_entry

    client.post(
        "/marm_log_entry",
        json={"session_name": "atomicity-a2", "entry": "2026-01-01-seed-entry to keep"},
    )

    db_path = tmp_path / "marm_memory.db"
    with sqlite3.connect(db_path) as conn:
        before_sessions = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_name = ?", ("atomicity-a2",)
        ).fetchone()[0]
        before_entries = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE session_name = ?",
            ("atomicity-a2",),
        ).fetchone()[0]
    assert before_sessions == 1
    assert before_entries >= 1

    _fail_on(monkeypatch, log_entry.memory, "DELETE FROM memories")

    resp = client.post("/marm_delete", json={"type": "log", "target": "atomicity-a2"})
    assert resp.json()["status"] == "error"

    with sqlite3.connect(db_path) as conn:
        after_sessions = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_name = ?", ("atomicity-a2",)
        ).fetchone()[0]
        after_entries = conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE session_name = ?",
            ("atomicity-a2",),
        ).fetchone()[0]
    assert after_sessions == before_sessions, "sessions row deleted despite rollback"
    assert after_entries == before_entries, "log_entries row deleted despite rollback"


def test_marm_start_rollback_keeps_previous_active_session(monkeypatch, tmp_path):
    """marm_start: UPDATE sessions SET marm_active = FALSE, then an
    INSERT OR REPLACE for the requested session. Force the insert to
    fail -- the previous active session's marm_active flag must not have
    been cleared."""
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    first = client.post("/marm_start", json={"session_name": "atomicity-a3-old"})
    assert first.status_code == 200

    db_path = tmp_path / "marm_memory.db"
    with sqlite3.connect(db_path) as conn:
        active_before = conn.execute(
            "SELECT marm_active FROM sessions WHERE session_name = ?",
            ("atomicity-a3-old",),
        ).fetchone()[0]
    assert active_before in (1, True)

    import marm_mcp_server.endpoints.session as session_endpoint

    _fail_on(monkeypatch, session_endpoint.memory, "INSERT OR REPLACE INTO sessions")

    second = client.post("/marm_start", json={"session_name": "atomicity-a3-new"})
    # marm_start's error contract differs from marm_log_entry/marm_delete's
    # 200-with-error-dict shape: its except blocks raise HTTPException(500)
    # rather than returning a dict.
    assert second.status_code == 500

    with sqlite3.connect(db_path) as conn:
        active_after = conn.execute(
            "SELECT marm_active FROM sessions WHERE session_name = ?",
            ("atomicity-a3-old",),
        ).fetchone()[0]
    assert active_after in (1, True), (
        "previous active session was cleared even though the new "
        "session's insert (and the whole transaction) failed"
    )


# --- Packet B: services/notebook.py, services/documentation.py ---


def test_notebook_add_rollback_no_partial_update(monkeypatch, tmp_path):
    """_add's update-then-conditional-insert is an UPDATE-XOR-INSERT
    upsert -- only one of the two statements ever actually writes data
    per call, so forcing the INSERT branch to fail proves nothing (a
    single failing statement can't leave a partial row; there's no
    earlier write in that branch to roll back). The real atomicity case
    is the UPDATE branch: seed an existing row so the UPDATE performs a
    real write, then force the commit itself to fail -- the row's
    original data must survive, not the new data."""
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    db_path = tmp_path / "marm_memory.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO notebook_entries (name, data, updated_at, project, platform) "
            "VALUES (?, ?, ?, NULL, NULL)",
            ("atomicity-b1-existing", "original data", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()

    import marm_mcp_server.services.notebook as notebook_service

    _fail_on(monkeypatch, notebook_service.memory, "COMMIT")

    resp = client.post(
        "/marm_notebook",
        json={
            "action": "add",
            "name": "atomicity-b1-existing",
            "data": "replacement data that must not persist",
        },
    )
    assert resp.json()["status"] == "error"

    with sqlite3.connect(db_path) as conn:
        data = conn.execute(
            "SELECT data FROM notebook_entries WHERE name = ?",
            ("atomicity-b1-existing",),
        ).fetchone()[0]
    assert data == "original data", (
        "notebook_entries row was updated despite the commit failing"
    )


def test_legacy_docs_cleanup_rollback_keeps_legacy_entries(monkeypatch, tmp_path):
    """load_marm_documentation's legacy-cleanup block: a loop of DELETEs
    over _LEGACY_SYSTEM_NOTEBOOK_NAMES, then an INSERT OR REPLACE marker
    row. Force the marker insert to fail -- the legacy notebook rows
    must still exist (the cleanup must not have partially applied)."""
    load_isolated_server(monkeypatch, tmp_path)

    import marm_mcp_server.services.documentation as documentation

    db_path = tmp_path / "marm_memory.db"
    legacy_name = "marm_protocol"
    assert legacy_name in documentation._LEGACY_SYSTEM_NOTEBOOK_NAMES
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO notebook_entries (name, data, updated_at) VALUES (?, ?, ?)",
            (legacy_name, "legacy payload", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()

    _fail_on(
        monkeypatch,
        documentation.memory,
        "INSERT OR REPLACE INTO user_settings",
    )

    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(documentation.load_marm_documentation())

    with sqlite3.connect(db_path) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM notebook_entries WHERE name = ?", (legacy_name,)
        ).fetchone()[0]
        marker = conn.execute(
            "SELECT COUNT(*) FROM user_settings WHERE key = 'system_notebook_cleanup_v1'"
        ).fetchone()[0]
    assert remaining == 1, (
        "legacy notebook row was deleted despite the marker insert failing"
    )
    assert marker == 0, "cleanup marker was written despite the transaction failing"


# --- Packet C: core/memory_ops.py ---


def test_update_memory_computes_embedding_before_acquiring_lock(monkeypatch, tmp_path):
    """The whole point of the _update_memory fix: embedding generation
    must complete before BEGIN IMMEDIATE runs, never during an open
    transaction. Verified by call order, not just absence of a crash --
    a wrong order wouldn't raise, it would just silently reintroduce the
    stall risk this fix exists to close."""
    from marm_mcp_server.core.memory import MARMMemory
    from marm_mcp_server.core.memory_ops import _update_memory

    mem = MARMMemory(str(tmp_path / "update-order.db"))
    mem._encoder_failed = False
    mem.encoder = None

    memory_id = str(uuid.uuid4())
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, content_hash, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (memory_id, "s1", "original content", "hash1", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()

    events = []

    def _fake_load_encoder_lazily():
        return True

    def _fake_encode_sync(text):
        events.append("encode")
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(mem, "_load_encoder_lazily", _fake_load_encoder_lazily)
    monkeypatch.setattr(mem, "_encode_sync", _fake_encode_sync)
    _record_statements(monkeypatch, mem, events, {"BEGIN IMMEDIATE": "begin_immediate"})

    asyncio.run(_update_memory(mem, memory_id, "appended content"))

    assert events == ["encode", "begin_immediate"], (
        f"expected embedding computation before BEGIN IMMEDIATE, got {events}"
    )


def test_update_memory_rollback_no_partial_content_or_chunk_update(
    monkeypatch, tmp_path
):
    """_update_memory's write block: UPDATE memories, then a folded-in
    DELETE FROM memory_chunks. Force the chunk delete to fail -- the
    memory row's content must remain the pre-merge original, and any
    pre-existing chunk rows must survive untouched."""
    from marm_mcp_server.core.memory import MARMMemory
    from marm_mcp_server.core.memory_ops import _update_memory

    mem = MARMMemory(str(tmp_path / "update-rollback.db"))
    mem._encoder_failed = True

    memory_id = str(uuid.uuid4())
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, content_hash, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                memory_id,
                "s1",
                "original content before merge",
                "hash-original",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding) "
            "VALUES (?, 0, 'pre-existing chunk', ?)",
            (memory_id, b"\x00\x01"),
        )
        conn.commit()

    _fail_on(monkeypatch, mem, "DELETE FROM memory_chunks")

    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(_update_memory(mem, memory_id, "new content to append"))

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT content, content_hash FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        chunk_count = conn.execute(
            "SELECT COUNT(*) FROM memory_chunks WHERE memory_id = ?", (memory_id,)
        ).fetchone()[0]

    assert row[0] == "original content before merge", (
        "memory content was partially updated despite the chunk delete failing"
    )
    assert row[1] == "hash-original"
    assert chunk_count == 1, "pre-existing chunk row was lost despite the rollback"


def test_console_replace_memory_rollback_regression(monkeypatch, tmp_path):
    """_replace_memory already had BEGIN IMMEDIATE before this hardening
    effort (confirmed during Packet C's audit) -- this is a regression
    test proving that pre-existing atomicity still holds, not proof of a
    newly-added transaction. Force the compaction_staging stale-marking
    update (the second statement) to fail after the content UPDATE ran --
    the memory's content must remain unchanged."""
    concept_db_path = tmp_path / "marm_index.db"
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(concept_db_path))
    server = load_isolated_server(
        monkeypatch, tmp_path, api_key="test-key", write_queue_enabled=True
    )
    headers = {"Authorization": "Bearer test-key"}

    with TestClient(server.app) as client:
        create = client.post(
            "/internal/memories",
            headers=headers,
            json={
                "content": "original console memory content",
                "session_name": "atomicity-c3",
                "context_type": "decision",
            },
        )
        assert create.status_code == 201
        memory_id = create.json()["id"]

        import marm_mcp_server.core.memory as memory_module

        _fail_on(monkeypatch, memory_module.memory, "UPDATE compaction_staging")

        # console_replace_memory's endpoint only catches RuntimeError, and
        # TestClient re-raises unhandled server exceptions by default
        # (rather than turning them into a 500 response) -- the forced
        # sqlite3.OperationalError propagates all the way out here. The
        # point of this test is the DB-level rollback, not this
        # endpoint's error-response contract.
        with pytest.raises(sqlite3.OperationalError):
            client.put(
                f"/internal/memories/{memory_id}",
                headers=headers,
                json={
                    "content": "replacement content that must not persist",
                    "session_name": "atomicity-c3",
                    "context_type": "decision",
                },
            )

        db_path = tmp_path / "marm_memory.db"
        with sqlite3.connect(db_path) as conn:
            content = conn.execute(
                "SELECT content FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()[0]
    assert content == "original console memory content", (
        "memory content was replaced despite the transaction's second "
        "statement failing -- _replace_memory's existing atomicity regressed"
    )


def test_stage_compaction_summaries_processes_candidates_independently(
    monkeypatch, tmp_path
):
    """endpoints/compaction.py audit (no code changes made there): every
    per-candidate mutation in marm_stage_compaction_summaries is a single
    UPDATE statement, so there's no multi-statement atomicity gap to
    wrap -- and wrapping the whole per-request loop in one transaction
    would be a *regression*, not a hardening, since each candidate is
    designed to succeed or fail independently. Proves that intended
    semantic directly: one expired candidate in the same request as one
    valid candidate must not block the valid one from staging."""
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    db_path = tmp_path / "marm_memory.db"
    with sqlite3.connect(db_path) as conn:
        for mem_id, content in (
            ("mem-valid", "valid source"),
            ("mem-expired", "expired source"),
        ):
            conn.execute(
                "INSERT INTO memories (id, session_name, content, content_hash, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (mem_id, "atomicity-c4", content, mem_id, "2026-01-01T00:00:00+00:00"),
            )
        conn.execute(
            """
            INSERT INTO compaction_staging (
                id, session_name, source_memory_ids, preview, suggested_summary,
                status, candidate_hash, source_updated_at_snapshot,
                expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "candidate-valid",
                "atomicity-c4",
                '["mem-valid"]',
                "valid source",
                "",
                "pending_summary",
                "hash-valid",
                "{}",
                "2099-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO compaction_staging (
                id, session_name, source_memory_ids, preview, suggested_summary,
                status, candidate_hash, source_updated_at_snapshot,
                expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "candidate-expired",
                "atomicity-c4",
                '["mem-expired"]',
                "expired source",
                "",
                "pending_summary",
                "hash-expired",
                "{}",
                "2020-01-01T00:00:00+00:00",  # already past
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()

    resp = client.post(
        "/marm_stage_compaction_summaries",
        json={
            "summaries": [
                {
                    "candidate_id": "candidate-valid",
                    "suggested_summary": "a real summary",
                },
                {
                    "candidate_id": "candidate-expired",
                    "suggested_summary": "should not matter, candidate is expired",
                },
            ]
        },
    )
    results = {r["candidate_id"]: r for r in resp.json()["results"]}
    assert results["candidate-valid"]["status"] == "summary_staged", (
        "the valid candidate was blocked by the expired one being in the "
        "same request -- per-candidate independence regressed"
    )
    assert results["candidate-expired"]["status"] == "error"

    with sqlite3.connect(db_path) as conn:
        valid_status = conn.execute(
            "SELECT status FROM compaction_staging WHERE id = ?", ("candidate-valid",)
        ).fetchone()[0]
        expired_status = conn.execute(
            "SELECT status FROM compaction_staging WHERE id = ?",
            ("candidate-expired",),
        ).fetchone()[0]
    assert valid_status == "summary_staged"
    assert expired_status == "stale"
