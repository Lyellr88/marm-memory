"""Schema, connection pool, and DB-state helpers for the concept graph.

Own SQLite file (~/.marm/index/marm_index.db), own SQLiteConnectionPool
instance — reuses memory_db.py's pool/context-manager classes (generic,
already parameterized by db_path) but never shares memory.py's pool
instance. Concept graph writes must never be able to block or corrupt the
production-critical memories table's WAL.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

from .memory_db import ConnectionContext, SQLiteConnectionPool

MAX_CONCEPT_DB_CONNECTIONS = 3


def get_concept_db_path() -> str:
    """Mirrors settings.get_marm_db_path()'s env-override + default pattern."""
    env_path = os.environ.get("MARM_CONCEPT_DB_PATH")
    if env_path:
        Path(env_path).parent.mkdir(parents=True, exist_ok=True)
        return env_path

    index_dir = Path.home() / ".marm" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    return str(index_dir / "marm_index.db")


def init_concept_database(db_path: str) -> None:
    """Initialize SQLite database with concept graph tables."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                session_name TEXT,
                project TEXT,
                source_memory_ids TEXT DEFAULT '[]',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, session_name, project)
            )
        """)

        # Additive column, guarded rather than assumed -- CREATE TABLE IF NOT
        # EXISTS above is a no-op against a pre-existing local DB from testing
        # this branch before this column existed.
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(entity_id) REFERENCES entities(id)
            )
        """)

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
        # Without these, re-running marm_concept_build on the same corpus (the
        # documented expected usage) re-inserts every relationship/code-link
        # row, and an entity mentioned in N memories gets N duplicate code
        # links -- both surface directly in marm_concept_recall's response.
        # INSERT OR IGNORE (see store_relationship/store_code_link) relies on
        # these to make builds idempotent.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_relationships_dedup "
            "ON relationships(source_id, target_id, predicate, memory_id)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_code_links_dedup "
            "ON entity_code_links(entity_id, graph_qualified_name)"
        )


class ConceptDB:
    """Owns the concept graph's SQLite pool. One instance per process, lazily built."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_concept_db_path()
        init_concept_database(self.db_path)
        self.connection_pool = SQLiteConnectionPool(
            self.db_path, max_connections=MAX_CONCEPT_DB_CONNECTIONS
        )

    def get_connection(self):
        return ConnectionContext(self.connection_pool)

    def get_or_create_entity(
        self,
        conn,
        name: str,
        entity_type: str,
        session_name: Optional[str],
        project: Optional[str],
        memory_id: str,
        name_embedding: Optional[bytes] = None,
    ) -> tuple[int, bool]:
        """Insert a new entity or append memory_id to an existing one's source
        list. Returns (entity_id, was_created) -- callers use was_created to
        run duplicate-candidate detection only once per entity ever, not on
        every re-mention across future builds. name_embedding is only stored
        on the INSERT branch; re-mentions never overwrite an existing
        entity's embedding."""
        row = conn.execute(
            "SELECT id, source_memory_ids FROM entities "
            "WHERE name = ? AND session_name IS ? AND project IS ?",
            (name, session_name, project),
        ).fetchone()

        if row is not None:
            entity_id, source_ids_json = row
            source_ids = json.loads(source_ids_json)
            if memory_id not in source_ids:
                source_ids.append(memory_id)
                conn.execute(
                    "UPDATE entities SET source_memory_ids = ? WHERE id = ?",
                    (json.dumps(source_ids), entity_id),
                )
            return entity_id, False

        cursor = conn.execute(
            "INSERT INTO entities "
            "(name, type, session_name, project, source_memory_ids, name_embedding) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                name,
                entity_type,
                session_name,
                project,
                json.dumps([memory_id]),
                name_embedding,
            ),
        )
        return cursor.lastrowid, True

    def find_similar_entities(
        self,
        conn,
        name_embedding: bytes,
        session_name: Optional[str],
        project: Optional[str],
        threshold: float,
        exclude_id: Optional[int] = None,
    ) -> list[dict]:
        """Linear cosine-similarity scan against same-scope entities' stored
        name embeddings -- bounded by deployment scale (personal/small-team
        memory stores, CONCEPT_BUILD_ROW_CAP=500 memories/build), no vector
        index needed at this scale. Mirrors memory_scoring.py's batched-numpy
        cosine pattern. Returns candidates >= threshold, most-similar-first."""
        rows = conn.execute(
            "SELECT id, name, name_embedding FROM entities "
            "WHERE session_name IS ? AND project IS ? "
            "AND name_embedding IS NOT NULL AND id != ?",
            (session_name, project, exclude_id if exclude_id is not None else -1),
        ).fetchall()
        if not rows:
            return []

        query_vec = np.frombuffer(name_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []
        normalized_query = query_vec / query_norm

        vectors = []
        kept_rows = []
        for entity_id, name, emb_bytes in rows:
            try:
                vector = np.frombuffer(emb_bytes, dtype=np.float32)
            except Exception:
                continue
            if vector.shape[0] != query_vec.shape[0]:
                continue
            vectors.append(vector)
            kept_rows.append((entity_id, name))

        if not vectors:
            return []

        matrix = np.vstack(vectors).astype(np.float32, copy=False)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / (norms + 1e-12)
        scores = matrix @ normalized_query

        candidates = [
            {
                "entity_id": kept_rows[i][0],
                "name": kept_rows[i][1],
                "similarity": float(scores[i]),
            }
            for i in range(len(kept_rows))
            if scores[i] >= threshold
        ]
        candidates.sort(key=lambda c: c["similarity"], reverse=True)
        return candidates

    def store_relationship(
        self,
        conn,
        source_id: int,
        target_id: int,
        predicate: str,
        memory_id: str,
        project: Optional[str],
    ) -> bool:
        """Insert a relationship. Caller must have already confirmed both entity
        ids exist (get_or_create_entity returns real ids) — this only guards
        against the source == target no-op case. Returns True only if a row
        was actually inserted (False on the self-loop no-op or a dedup-index
        conflict from a repeat build), so callers can count real writes."""
        if source_id == target_id:
            return False
        cursor = conn.execute(
            "INSERT OR IGNORE INTO relationships "
            "(source_id, target_id, predicate, memory_id, project) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, target_id, predicate, memory_id, project),
        )
        return cursor.rowcount > 0

    def store_code_link(
        self,
        conn,
        entity_id: int,
        graph_qualified_name: str,
        project: str,
        confidence: float = 1.0,
        label: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> bool:
        """label/file_path are denormalized from marm-graph's response at build
        time (not in the original spec schema) so marm_concept_recall's
        linked_code field works even if marm-graph is unavailable at recall
        time -- avoids a live re-query dependency the spec's response shape
        otherwise implied without actually storing the data for it. Returns
        True only if a row was actually inserted (False on a dedup-index
        conflict from a repeat build), so callers can count real writes."""
        cursor = conn.execute(
            "INSERT OR IGNORE INTO entity_code_links "
            "(entity_id, graph_qualified_name, project, confidence, label, file_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (entity_id, graph_qualified_name, project, confidence, label, file_path),
        )
        return cursor.rowcount > 0
