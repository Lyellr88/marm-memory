"""Tests for core/docs_db.py -- the permanent docs store."""

import contextlib
import sqlite3

from marm_mcp_server.core.docs_db import DocsDB, get_docs_db_path, init_docs_database


class _FailOnStatement:
    """Wraps a real sqlite3 connection. execute() raises the first time it
    sees SQL containing `trigger`; every other call passes through."""

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


def _fail_on(monkeypatch, docs_db, trigger):
    real_get_connection = docs_db.get_connection

    @contextlib.contextmanager
    def _patched():
        with real_get_connection() as real_conn:
            yield _FailOnStatement(real_conn, trigger)

    monkeypatch.setattr(docs_db, "get_connection", _patched)


def test_get_docs_db_path_respects_env_override(tmp_path, monkeypatch):
    override = tmp_path / "custom" / "docs.db"
    monkeypatch.setenv("MARM_DOCS_DB_PATH", str(override))

    resolved = get_docs_db_path()

    assert resolved == str(override)
    assert override.parent.exists()


def test_get_docs_db_path_default_uses_home_docs_subdir(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("MARM_DOCS_DB_PATH", raising=False)
    # Patch Path.home() directly rather than the HOME env var -- HOME is
    # POSIX-only (Windows resolves Path.home() via USERPROFILE instead),
    # so an env-var-based override silently no-ops on Windows and leaves
    # this test asserting against the real, unrelated user home directory.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    resolved = get_docs_db_path()

    assert Path(resolved) == tmp_path / ".marm" / "docs" / "marm_docs.db"


def test_init_docs_database_creates_table_and_indexes(tmp_path):
    db_path = str(tmp_path / "docs.db")
    init_docs_database(db_path)

    import sqlite3

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    assert "docs" in tables
    assert "idx_docs_scope_unique" in indexes
    assert "idx_docs_memory_id" in indexes


def test_save_doc_creates_new_row_with_null_memory_id(tmp_path):
    db = DocsDB(str(tmp_path / "docs.db"))
    with db.get_connection() as conn:
        doc_row, was_created = db.save_doc(
            conn,
            name="architecture-notes",
            content="the system uses three databases",
            session_name="main",
            project="marm",
            platform="claude-code",
            source_notebook_name=None,
        )

    assert was_created is True
    assert doc_row.name == "architecture-notes"
    assert doc_row.content == "the system uses three databases"
    assert doc_row.memory_id is None
    assert doc_row.id is not None


def test_save_doc_resave_updates_content_and_preserves_memory_id(tmp_path):
    db = DocsDB(str(tmp_path / "docs.db"))
    with db.get_connection() as conn:
        first, _ = db.save_doc(
            conn,
            name="notes",
            content="version one",
            session_name="main",
            project=None,
            platform=None,
            source_notebook_name="notes",
        )
        db.set_memory_id(conn, first.id, "mem-123")

    with db.get_connection() as conn:
        second, was_created = db.save_doc(
            conn,
            name="notes",
            content="version two",
            session_name="main",
            project=None,
            platform=None,
            source_notebook_name="notes",
        )

    assert was_created is False
    assert second.id == first.id
    assert second.content == "version two"
    # memory_id must survive a resave untouched -- it only changes via an
    # explicit set_memory_id call after a real mirror sync succeeds.
    assert second.memory_id == "mem-123"


def test_save_doc_runs_under_begin_immediate_and_rolls_back_on_commit_failure(
    tmp_path, monkeypatch
):
    """save_doc's UPDATE-then-conditional-INSERT must be wrapped in a real
    transaction (matching services/notebook.py:_add's established
    pattern) -- without it, two concurrent first-time saves of the same
    scope could both see UPDATE->0 rows and both attempt the INSERT,
    turning a routine race into an IntegrityError instead of a clean
    update. Force the commit itself to fail and confirm no partial row
    survives."""
    db = DocsDB(str(tmp_path / "docs.db"))
    _fail_on(monkeypatch, db, "COMMIT")

    try:
        with db.get_connection() as conn:
            db.save_doc(
                conn,
                name="atomicity-doc",
                content="should not survive",
                session_name="main",
                project=None,
                platform=None,
                source_notebook_name=None,
            )
    except sqlite3.OperationalError:
        pass

    with sqlite3.connect(str(tmp_path / "docs.db")) as raw_conn:
        count = raw_conn.execute(
            "SELECT COUNT(*) FROM docs WHERE name = 'atomicity-doc'"
        ).fetchone()[0]
    assert count == 0, "doc row was inserted despite the commit failing"


def test_save_doc_scope_isolation_same_name_different_sessions(tmp_path):
    db = DocsDB(str(tmp_path / "docs.db"))
    with db.get_connection() as conn:
        row_a, created_a = db.save_doc(
            conn,
            name="shared-name",
            content="alpha content",
            session_name="alpha",
            project=None,
            platform=None,
            source_notebook_name=None,
        )
        row_b, created_b = db.save_doc(
            conn,
            name="shared-name",
            content="beta content",
            session_name="beta",
            project=None,
            platform=None,
            source_notebook_name=None,
        )

    assert created_a is True
    assert created_b is True
    assert row_a.id != row_b.id
    assert row_a.content == "alpha content"
    assert row_b.content == "beta content"


def test_set_memory_id_persists(tmp_path):
    db = DocsDB(str(tmp_path / "docs.db"))
    with db.get_connection() as conn:
        doc_row, _ = db.save_doc(
            conn,
            name="linked-doc",
            content="content",
            session_name="main",
            project=None,
            platform=None,
            source_notebook_name=None,
        )
        db.set_memory_id(conn, doc_row.id, "mem-abc")

    with db.get_connection() as conn:
        stored = conn.execute(
            "SELECT memory_id FROM docs WHERE id = ?", (doc_row.id,)
        ).fetchone()[0]
    assert stored == "mem-abc"
