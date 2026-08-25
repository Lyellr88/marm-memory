import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .memory_db import ConnectionContext, SQLiteConnectionPool

MAX_DOCS_DB_CONNECTIONS = 3


def get_docs_db_path() -> str:
    """Mirrors concept_db.get_concept_db_path()'s env-override + default pattern."""
    env_path = os.environ.get("MARM_DOCS_DB_PATH")
    if env_path:
        Path(env_path).parent.mkdir(parents=True, exist_ok=True)
        return env_path

    docs_dir = Path.home() / ".marm" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    return str(docs_dir / "marm_docs.db")


def init_docs_database(db_path: str) -> None:
    """Initialize SQLite database with the docs table."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                session_name TEXT,
                project TEXT,
                platform TEXT,
                source_notebook_name TEXT,
                memory_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_scope_unique "
            "ON docs(name, COALESCE(session_name, ''), COALESCE(project, ''), "
            "COALESCE(platform, ''))"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_memory_id ON docs(memory_id)")
        conn.commit()


@dataclass(frozen=True)
class DocRow:
    id: int
    name: str
    content: str
    session_name: Optional[str]
    project: Optional[str]
    platform: Optional[str]
    source_notebook_name: Optional[str]
    memory_id: Optional[str]
    created_at: str
    updated_at: str


class DocsDB:
    """Owns the docs store's SQLite pool. One instance per process, lazily built."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_docs_db_path()
        init_docs_database(self.db_path)
        self.connection_pool = SQLiteConnectionPool(
            self.db_path, max_connections=MAX_DOCS_DB_CONNECTIONS
        )

    def get_connection(self) -> ConnectionContext:
        return ConnectionContext(self.connection_pool)

    def save_doc(
        self,
        conn: sqlite3.Connection,
        *,
        name: str,
        content: str,
        session_name: Optional[str],
        project: Optional[str],
        platform: Optional[str],
        source_notebook_name: Optional[str],
    ) -> tuple[DocRow, bool]:
        """Create a new doc row or update an existing one's content in place.

        On resave, the prior memory_id is left untouched by the UPDATE --
        it keeps pointing at the last synced mirror until the caller
        re-syncs and calls set_memory_id, so a resave whose mirror write
        fails never loses track of the still-valid old mirror. A brand
        new doc starts with memory_id = NULL, meaning "durable doc exists,
        mirror not synced yet." Returns (doc_row, was_created).
        """
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.execute(
                """
                UPDATE docs SET content = ?, source_notebook_name = ?, updated_at = ?
                WHERE name = ? AND session_name IS ? AND project IS ? AND platform IS ?
                """,
                (
                    content,
                    source_notebook_name,
                    now,
                    name,
                    session_name,
                    project,
                    platform,
                ),
            )
            was_created = cursor.rowcount == 0
            if was_created:
                conn.execute(
                    """
                    INSERT INTO docs
                        (name, content, session_name, project, platform,
                         source_notebook_name, memory_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        name,
                        content,
                        session_name,
                        project,
                        platform,
                        source_notebook_name,
                        now,
                        now,
                    ),
                )
            row = conn.execute(
                """
                SELECT id, name, content, session_name, project, platform,
                       source_notebook_name, memory_id, created_at, updated_at
                FROM docs
                WHERE name = ? AND session_name IS ? AND project IS ? AND platform IS ?
                """,
                (name, session_name, project, platform),
            ).fetchone()
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return DocRow(*row), was_created

    def set_memory_id(
        self, conn: sqlite3.Connection, doc_id: int, memory_id: str
    ) -> None:
        conn.execute("UPDATE docs SET memory_id = ? WHERE id = ?", (memory_id, doc_id))
