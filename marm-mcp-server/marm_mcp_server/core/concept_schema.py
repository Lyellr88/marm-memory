import sqlite3
from contextlib import closing
from pathlib import Path

CONCEPT_SCHEMA_VERSION = 3
_SCHEMA_VERSION_KEY = "schema_version"


def init_concept_database(db_path: str, mark_current: bool = True) -> None:
    """Initialize SQLite database with concept graph tables.

    Pass mark_current=False when initializing a graph that still has to be
    rebuilt. Writing the version and deleting it again leaves a window where a
    crash, or another process reading the schema state, sees an empty graph
    reported as current.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        existing_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "entities" in existing_tables:
            entity_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(entities)")
            }
            relationship_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(relationships)")
            }
            if (
                "platform" not in entity_columns
                or "platform" not in relationship_columns
            ):
                return

        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                session_name TEXT,
                project TEXT,
                platform TEXT,
                source_memory_ids TEXT DEFAULT '[]',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, session_name, project, platform)
            )
        """)

        existing_entity_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(entities)")
        }
        if "name_embedding" not in existing_entity_cols:
            conn.execute("ALTER TABLE entities ADD COLUMN name_embedding BLOB")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                predicate TEXT NOT NULL,
                memory_id TEXT,
                project TEXT,
                platform TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(source_id) REFERENCES entities(id),
                FOREIGN KEY(target_id) REFERENCES entities(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_code_links (
                entity_id INTEGER NOT NULL,
                graph_qualified_name TEXT NOT NULL,
                project TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                label TEXT,
                file_path TEXT,
                link_method TEXT NOT NULL DEFAULT 'legacy_exact_symbol',
                resolved_at TEXT,
                last_verified_at TEXT,
                anchor_hash TEXT,
                code_changed_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(entity_id) REFERENCES entities(id)
            )
        """)
        existing_link_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(entity_code_links)")
        }
        if "link_method" not in existing_link_cols:
            conn.execute(
                "ALTER TABLE entity_code_links ADD COLUMN link_method TEXT NOT NULL "
                "DEFAULT 'legacy_exact_symbol'"
            )
        if "resolved_at" not in existing_link_cols:
            conn.execute("ALTER TABLE entity_code_links ADD COLUMN resolved_at TEXT")
        if "last_verified_at" not in existing_link_cols:
            conn.execute(
                "ALTER TABLE entity_code_links ADD COLUMN last_verified_at TEXT"
            )
        for column in ("anchor_hash", "code_changed_at"):
            if column not in existing_link_cols:
                conn.execute(f"ALTER TABLE entity_code_links ADD COLUMN {column} TEXT")
        conn.execute(
            "UPDATE entity_code_links SET resolved_at = created_at "
            "WHERE resolved_at IS NULL"
        )
        conn.execute(
            "UPDATE entity_code_links SET last_verified_at = created_at "
            "WHERE last_verified_at IS NULL"
        )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_code_links_entity ON entity_code_links(entity_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_code_links_project ON entity_code_links(project)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_relationships_dedup "
            "ON relationships(source_id, target_id, predicate, memory_id, "
            "COALESCE(platform, ''))"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_code_links_dedup "
            "ON entity_code_links(entity_id, graph_qualified_name)"
        )

        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_dedup "
            "ON entities(name, COALESCE(session_name, ''), COALESCE(project, ''), "
            "COALESCE(platform, ''))"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concept_schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        if mark_current and "entities" not in existing_tables:
            conn.execute(
                "INSERT INTO concept_schema_metadata (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO NOTHING",
                (_SCHEMA_VERSION_KEY, str(CONCEPT_SCHEMA_VERSION)),
            )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concept_build_runs (
                id TEXT PRIMARY KEY,
                scope_type TEXT NOT NULL,
                scope_value TEXT,
                status TEXT NOT NULL,
                memories_processed INTEGER NOT NULL DEFAULT 0,
                memories_total INTEGER NOT NULL DEFAULT 0,
                entities_extracted INTEGER NOT NULL DEFAULT 0,
                relationships_created INTEGER NOT NULL DEFAULT 0,
                code_links_created INTEGER NOT NULL DEFAULT 0,
                duplicate_candidates INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER,
                error_code TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                last_progress_at TEXT,
                cancel_requested_at TEXT,
                cancelled_at TEXT,
                finished_at TEXT
            )
        """)
        build_run_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(concept_build_runs)")
        }
        if "memories_total" not in build_run_columns:
            conn.execute(
                "ALTER TABLE concept_build_runs "
                "ADD COLUMN memories_total INTEGER NOT NULL DEFAULT 0"
            )
        if "last_progress_at" not in build_run_columns:
            conn.execute(
                "ALTER TABLE concept_build_runs ADD COLUMN last_progress_at TEXT"
            )
        if "cancel_requested_at" not in build_run_columns:
            conn.execute(
                "ALTER TABLE concept_build_runs ADD COLUMN cancel_requested_at TEXT"
            )
        if "cancelled_at" not in build_run_columns:
            conn.execute("ALTER TABLE concept_build_runs ADD COLUMN cancelled_at TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_concept_build_runs_created "
            "ON concept_build_runs(created_at DESC)"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS concept_entity_aliases (
                alias_name TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                session_name TEXT,
                project TEXT,
                platform TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_aliases_scope "
            "ON concept_entity_aliases(alias_name, COALESCE(session_name, ''), "
            "COALESCE(project, ''), COALESCE(platform, ''))"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concept_entity_suppressions (
                name TEXT NOT NULL,
                session_name TEXT,
                project TEXT,
                platform TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_suppressions_scope "
            "ON concept_entity_suppressions(name, COALESCE(session_name, ''), "
            "COALESCE(project, ''), COALESCE(platform, ''))"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concept_duplicate_dismissals (
                name_a TEXT NOT NULL,
                name_b TEXT NOT NULL,
                session_name TEXT,
                project TEXT,
                platform TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_dismissals_scope "
            "ON concept_duplicate_dismissals(name_a, name_b, "
            "COALESCE(session_name, ''), COALESCE(project, ''), "
            "COALESCE(platform, ''))"
        )


def inspect_concept_schema(db_path: str) -> str:
    """Return missing, current, rebuild_required, or unavailable without DDL."""
    path = Path(db_path)
    if not path.exists():
        return "missing"
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "entities" not in tables or "relationships" not in tables:
                return "rebuild_required"
            entity_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(entities)")
            }
            relationship_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(relationships)")
            }
            if (
                "platform" not in entity_columns
                or "platform" not in relationship_columns
            ):
                return "rebuild_required"
            if "concept_schema_metadata" not in tables:
                return "rebuild_required"
            row = conn.execute(
                "SELECT value FROM concept_schema_metadata WHERE key = ?",
                (_SCHEMA_VERSION_KEY,),
            ).fetchone()
            if row is None or row[0] != str(CONCEPT_SCHEMA_VERSION):
                return "rebuild_required"
            return "current"
    except (OSError, sqlite3.Error):
        return "unavailable"


def mark_schema_current(db_path: str) -> None:
    """Record that this graph was built under the current extraction rules.

    Called only after a full build finishes. Between the reset and this call
    the graph reports `rebuild_required`, so an interrupted rebuild is retried
    rather than mistaken for a complete one.
    """
    with closing(sqlite3.connect(db_path, timeout=20.0)) as conn:
        conn.execute(
            "INSERT INTO concept_schema_metadata (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_SCHEMA_VERSION_KEY, str(CONCEPT_SCHEMA_VERSION)),
        )
        conn.commit()
