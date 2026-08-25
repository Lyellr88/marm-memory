import sqlite3

from marm_mcp_server.core.memory_db import init_database


def test_fresh_database_has_session_name_column(tmp_path):
    db_path = tmp_path / "memory.db"
    init_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notebook_entries)")}
    assert "session_name" in cols


def test_legacy_rows_without_session_name_migrate_to_main(tmp_path):
    """A notebook_entries table from before the session_name column existed
    must have its rows land on session_name='main' after init_database runs
    again -- not NULL, which would strand them as an unreachable scope for
    every add/use/show/save caller (all of which default to 'main')."""
    db_path = tmp_path / "memory.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE notebook_entries (
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                embedding BLOB,
                project TEXT DEFAULT NULL,
                platform TEXT DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO notebook_entries (name, data) VALUES ('legacy-rule', 'legacy content')"
        )
        conn.commit()

    init_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT session_name, data FROM notebook_entries WHERE name = 'legacy-rule'"
        ).fetchone()
    assert row is not None
    assert row[0] == "main"
    assert row[1] == "legacy content"


def test_unique_index_includes_session_name(tmp_path):
    """Same name+project+platform must be allowed to coexist across two
    different session scopes after the index rebuild."""
    db_path = tmp_path / "memory.db"
    init_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO notebook_entries (name, data, session_name, project, platform) "
            "VALUES ('shared', 'alpha content', 'alpha', NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO notebook_entries (name, data, session_name, project, platform) "
            "VALUES ('shared', 'beta content', 'beta', NULL, NULL)"
        )
        conn.commit()

        rows = conn.execute(
            "SELECT session_name, data FROM notebook_entries WHERE name = 'shared' "
            "ORDER BY session_name"
        ).fetchall()
    assert rows == [("alpha", "alpha content"), ("beta", "beta content")]


def test_unique_index_still_rejects_duplicate_within_same_scope(tmp_path):
    db_path = tmp_path / "memory.db"
    init_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO notebook_entries (name, data, session_name, project, platform) "
            "VALUES ('dup', 'first', 'main', NULL, NULL)"
        )
        conn.commit()
        try:
            conn.execute(
                "INSERT INTO notebook_entries (name, data, session_name, project, platform) "
                "VALUES ('dup', 'second', 'main', NULL, NULL)"
            )
            conn.commit()
            raised = False
        except sqlite3.IntegrityError:
            raised = True
    assert raised, "duplicate (name, session_name, project, platform) must be rejected"


def test_init_database_is_idempotent_after_migration(tmp_path):
    """Running init_database twice (e.g. two server restarts) must not
    error on the DROP INDEX/session_name ALTER TABLE guards."""
    db_path = tmp_path / "memory.db"
    init_database(str(db_path))
    init_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    assert "idx_notebook_entries_scope_unique" in indexes
