"""Connection pooling, schema DDL, and DB-state helpers for the MARM memory system."""

import queue
import sqlite3
import threading
from datetime import datetime, timezone
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory import MARMMemory


class SQLiteConnectionPool:
    """Simple SQLite connection pool for better performance under load"""

    def __init__(self, db_path: str, max_connections: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool: queue.Queue[sqlite3.Connection] = queue.Queue(
            maxsize=max_connections
        )
        self.created_connections = 0
        self.lock = threading.Lock()

        self._create_initial_connections()

    def _create_initial_connections(self) -> None:
        """Create initial pool of connections"""
        for _ in range(min(2, self.max_connections)):
            self.pool.put(self._create_connection())

    def _create_connection(self) -> sqlite3.Connection:
        """Create and return a new SQLite connection with optimal settings."""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=20.0,
            isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA foreign_keys=ON")
        self.created_connections += 1
        return conn

    def get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool"""
        try:
            return self.pool.get(block=False)
        except queue.Empty:
            with self.lock:
                if self.created_connections < self.max_connections:
                    # Return directly — never touch the queue so no other
                    # thread waiting on pool.get() can steal this connection.
                    return self._create_connection()

            return self.pool.get(block=True, timeout=10)

    def return_connection(self, conn: sqlite3.Connection) -> None:
        """Return connection to pool"""
        try:
            self.pool.put(conn, block=False)
        except queue.Full:
            conn.close()

    def close_all(self) -> None:
        """Close all connections in the pool"""
        while not self.pool.empty():
            try:
                conn = self.pool.get(block=False)
                conn.close()
            except queue.Empty:
                break


class ConnectionContext:
    """Context manager for getting database connections from the pool.

    Commits on clean exit, rolls back on exception, always returns the
    connection to the pool.
    """

    def __init__(self, pool: SQLiteConnectionPool) -> None:
        self.pool = pool
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self.conn = self.pool.get_connection()
        return self.conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self.conn:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
            self.pool.return_connection(self.conn)


def init_database(db_path: str) -> None:
    """Initialize SQLite database with all MARM tables"""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                session_name TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB,
                timestamp TEXT NOT NULL,
                context_type TEXT DEFAULT 'general',
                metadata TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_name TEXT PRIMARY KEY,
                marm_active BOOLEAN DEFAULT FALSE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_accessed TEXT DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT DEFAULT '{}'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS log_entries (
                id TEXT PRIMARY KEY,
                session_name TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                full_entry TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notebook_entries (
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                embedding BLOB,
                project TEXT DEFAULT NULL,
                platform TEXT DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS doc_index (
                source_file TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                memory_id TEXT,
                indexed_at TEXT NOT NULL
            )
        """)
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(doc_index)").fetchall()
        }
        if "memory_id" not in existing_cols:
            conn.execute("ALTER TABLE doc_index ADD COLUMN memory_id TEXT")

        mem_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        if "content_hash" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN content_hash TEXT")

        if "compaction_role" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN compaction_role TEXT")
        if "compacted_into" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN compacted_into TEXT")
        if "project" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN project TEXT DEFAULT NULL")
        if "platform" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN platform TEXT DEFAULT NULL")

        log_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(log_entries)").fetchall()
        }
        if "project" not in log_cols:
            conn.execute("ALTER TABLE log_entries ADD COLUMN project TEXT DEFAULT NULL")
        if "platform" not in log_cols:
            conn.execute(
                "ALTER TABLE log_entries ADD COLUMN platform TEXT DEFAULT NULL"
            )

        nb_info = conn.execute("PRAGMA table_info(notebook_entries)").fetchall()
        nb_cols = {row[1] for row in nb_info}
        if "project" not in nb_cols:
            conn.execute(
                "ALTER TABLE notebook_entries ADD COLUMN project TEXT DEFAULT NULL"
            )
        if "platform" not in nb_cols:
            conn.execute(
                "ALTER TABLE notebook_entries ADD COLUMN platform TEXT DEFAULT NULL"
            )
        if "session_name" not in nb_cols:
            conn.execute(
                "ALTER TABLE notebook_entries ADD COLUMN session_name TEXT DEFAULT NULL"
            )
            # Legacy rows predate the session dimension entirely -- migrate
            # them to "main" (notebook_dispatch's own default) rather than
            # leaving them at NULL, which would strand them as a scope no
            # add/use/show/save caller can ever reach again by default.
            conn.execute(
                "UPDATE notebook_entries SET session_name = 'main' WHERE session_name IS NULL"
            )
        if any(row[1] == "name" and row[5] for row in nb_info):
            conn.execute("ALTER TABLE notebook_entries RENAME TO notebook_entries_old")
            conn.execute("""
                CREATE TABLE notebook_entries (
                    name TEXT NOT NULL,
                    data TEXT NOT NULL,
                    embedding BLOB,
                    project TEXT DEFAULT NULL,
                    platform TEXT DEFAULT NULL,
                    session_name TEXT DEFAULT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            old_cols = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(notebook_entries_old)"
                ).fetchall()
            }
            project_expr = "project" if "project" in old_cols else "NULL"
            platform_expr = "platform" if "platform" in old_cols else "NULL"
            session_expr = "session_name" if "session_name" in old_cols else "'main'"
            conn.execute(f"""
                INSERT INTO notebook_entries
                    (name, data, embedding, project, platform, session_name, created_at, updated_at)
                SELECT name, data, embedding, {project_expr}, {platform_expr}, {session_expr},
                       created_at, updated_at
                FROM notebook_entries_old
            """)
            conn.execute("DROP TABLE notebook_entries_old")
        # Replaces the prior 3-column (name, project, platform) unique index --
        # DROP is required because SQLite has no CREATE OR REPLACE INDEX, and
        # the old index would otherwise keep enforcing the narrower identity
        # forever alongside this one.
        conn.execute("DROP INDEX IF EXISTS idx_notebook_entries_scope_unique")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_notebook_entries_scope_unique "
            "ON notebook_entries(name, COALESCE(session_name, ''), "
            "COALESCE(project, ''), COALESCE(platform, ''))"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS compaction_staging (
                id TEXT PRIMARY KEY,
                session_name TEXT NOT NULL,
                source_memory_ids TEXT NOT NULL,
                preview TEXT NOT NULL,
                suggested_summary TEXT,
                status TEXT NOT NULL DEFAULT 'pending_summary',
                candidate_hash TEXT NOT NULL,
                source_updated_at_snapshot TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reviewed_at TEXT,
                nudge_count INTEGER NOT NULL DEFAULT 0,
                last_nudged_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS compaction_session_state (
                session_name TEXT PRIMARY KEY,
                write_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)
        staging_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(compaction_staging)").fetchall()
        }
        if "nudge_count" not in staging_cols:
            conn.execute(
                "ALTER TABLE compaction_staging "
                "ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0"
            )
        if "last_nudged_at" not in staging_cols:
            conn.execute(
                "ALTER TABLE compaction_staging ADD COLUMN last_nudged_at TEXT"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_compaction_staging_session_status "
            "ON compaction_staging(session_name, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_compaction_staging_hash "
            "ON compaction_staging(candidate_hash)"
        )

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, content='memories', content_rowid='rowid',
                           tokenize='porter ascii')
            """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ai
                AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
            END
            """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_au
                AFTER UPDATE OF content ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
                INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
            END
            """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ad
                AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
            END
            """)
        conn.execute(
            "INSERT OR IGNORE INTO memories_fts(rowid, content) "
            "SELECT rowid, content FROM memories"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding BLOB NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_chunks_memory_id"
            " ON memory_chunks(memory_id)"
        )
        # Two writes for the same memory_id with identical content share the
        # same expected_content_hash (_write_chunks' own staleness guard
        # can't tell them apart), so back-to-back resaves with unchanged
        # content -- a real, supported action for a promoted doc -- could
        # otherwise both pass the staleness check and both INSERT a full
        # set of chunk rows, doubling storage with no way to tell the
        # duplicates apart. This index plus _write_chunks' INSERT OR REPLACE
        # makes concurrent identical-content chunk writes idempotent instead.
        #
        # A database that already has duplicate (memory_id, chunk_index)
        # rows from before this index existed (the exact race above,
        # pre-fix) would fail CREATE UNIQUE INDEX outright and the server
        # could never start again. Collapse existing duplicates first --
        # keep the highest id (most recent write) per pair, drop the rest
        # -- but only do this scan once: guard it behind the index not
        # existing yet, so every other startup is a cheap no-op.
        existing_indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        if "idx_memory_chunks_dedup" not in existing_indexes:
            conn.execute("""
                DELETE FROM memory_chunks
                WHERE id NOT IN (
                    SELECT MAX(id) FROM memory_chunks GROUP BY memory_id, chunk_index
                )
                """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_chunks_dedup"
            " ON memory_chunks(memory_id, chunk_index)"
        )

        # Durable outbox for concept indexing. Lives in the memory DB, not the
        # concept DB, so the enqueue can join the same transaction as the
        # memories INSERT and a memory can never exist without its task.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concept_index_queue (
                memory_id    TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                enqueued_at  TEXT NOT NULL,
                state        TEXT NOT NULL DEFAULT 'pending',
                lease_token  TEXT,
                leased_until TEXT,
                attempts     INTEGER NOT NULL DEFAULT 0,
                last_error   TEXT,
                FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_concept_queue_ready"
            " ON concept_index_queue(state, leased_until, enqueued_at)"
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS code_project_bindings (
                graph_project    TEXT PRIMARY KEY,
                memory_project   TEXT NOT NULL UNIQUE,
                root_path        TEXT NOT NULL,
                source           TEXT NOT NULL CHECK (source IN ('auto', 'user')),
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                last_verified_at TEXT NOT NULL
            )
            """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS code_link_refresh_queue (
                graph_project    TEXT PRIMARY KEY,
                memory_project   TEXT NOT NULL,
                root_path        TEXT NOT NULL,
                cursor_entity_id INTEGER NOT NULL DEFAULT 0,
                enqueued_at      TEXT NOT NULL,
                state            TEXT NOT NULL DEFAULT 'pending',
                lease_token      TEXT,
                leased_until     TEXT,
                attempts         INTEGER NOT NULL DEFAULT 0,
                last_error       TEXT
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_code_link_refresh_ready"
            " ON code_link_refresh_queue(state, leased_until, enqueued_at)"
        )

        # One row, held by whoever is currently writing the concept graph.
        # asyncio locks cannot reach across processes, and HTTP and STDIO are
        # two processes: without this, a full rebuild can drop the graph tables
        # while the other process's worker is writing to them.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concept_build_lock (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                holder     TEXT NOT NULL,
                purpose    TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """)

        # Same shape and purpose as concept_build_lock, for the code index. A
        # separate row rather than a shared one: making concept extraction and
        # code indexing mutually exclusive would serialize two unrelated stores.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_index_lock (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                holder     TEXT NOT NULL,
                purpose    TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """)

        # Runtime overrides that must outlive the process and be visible to both
        # transports: auto-index on/off switches and per-project watch
        # suppressions written when a project is deleted.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runtime_flags (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """)

        conn.execute("DROP TABLE IF EXISTS session_summary_chunks")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_summary_cache (
                session_name TEXT PRIMARY KEY,
                raw_digest TEXT NOT NULL DEFAULT '',
                summary_text TEXT NOT NULL DEFAULT '',
                entry_count INTEGER NOT NULL DEFAULT 0,
                dirty BOOLEAN DEFAULT FALSE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
        conn.commit()


def _get_compaction_write_count(mem: "MARMMemory", session: str) -> int:
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT write_count FROM compaction_session_state WHERE session_name = ?",
            (session,),
        ).fetchone()
    count = int(row[0]) if row else 0
    mem._session_write_counts[session] = count
    return count


def _set_compaction_write_count(mem: "MARMMemory", session: str, count: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with mem.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO compaction_session_state
                (session_name, write_count, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_name)
            DO UPDATE SET write_count = excluded.write_count,
                          updated_at = excluded.updated_at
            """,
            (session, count, now),
        )
    mem._session_write_counts[session] = count


def _increment_compaction_write_count(mem: "MARMMemory", session: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO compaction_session_state
                (session_name, write_count, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(session_name)
            DO UPDATE SET write_count = write_count + 1,
                          updated_at = excluded.updated_at
            """,
            (session, now),
        )
        row = conn.execute(
            "SELECT write_count FROM compaction_session_state WHERE session_name = ?",
            (session,),
        ).fetchone()
    count = int(row[0]) if row else 0
    mem._session_write_counts[session] = count
    return count
