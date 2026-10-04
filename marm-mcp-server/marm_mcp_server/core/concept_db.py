import json
import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from .code_anchor import span_hash
from .concept_build_runs import BuildRunMixin
from .concept_names import numbers_differ
from .concept_schema import (
    CONCEPT_SCHEMA_VERSION,
    init_concept_database,
    inspect_concept_schema,
    mark_schema_current,
)
from .memory_db import ConnectionContext, SQLiteConnectionPool
from .memory_utils import _safe_print

MAX_CONCEPT_DB_CONNECTIONS = 3

__all__ = [
    "CONCEPT_SCHEMA_VERSION",
    "MAX_CONCEPT_DB_CONNECTIONS",
    "ConceptDB",
    "backup_and_reset_concept_database",
    "get_concept_db_path",
    "init_concept_database",
    "inspect_concept_schema",
    "mark_schema_current",
]


def get_concept_db_path() -> str:
    """Mirrors settings.get_marm_db_path()'s env-override + default pattern."""
    env_path = os.environ.get("MARM_CONCEPT_DB_PATH")
    if env_path:
        Path(env_path).parent.mkdir(parents=True, exist_ok=True)
        return env_path

    index_dir = Path.home() / ".marm" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    return str(index_dir / "marm_index.db")


def backup_and_reset_concept_database(db_path: str) -> str:
    """Back up derived graph data, replace it, and return the backup path."""
    path = Path(db_path)
    if not path.exists():
        init_concept_database(db_path)
        return ""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = path.with_name(f"{path.name}.backup-{stamp}")
    source = sqlite3.connect(db_path)
    backup = sqlite3.connect(backup_path)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()

    reset = sqlite3.connect(db_path, timeout=20.0)
    try:
        reset.execute("PRAGMA foreign_keys=OFF")
        reset.execute("BEGIN IMMEDIATE")
        for table in (
            "entity_code_links",
            "relationships",
            "entities",
            "concept_build_runs",
            "concept_schema_metadata",
        ):
            reset.execute(f"DROP TABLE IF EXISTS {table}")
        reset.execute("COMMIT")
    except Exception:
        reset.rollback()
        raise
    finally:
        reset.close()
    init_concept_database(db_path, mark_current=False)
    return str(backup_path)


class ConceptDB(BuildRunMixin):
    """Owns the concept graph's SQLite pool. One instance per process, lazily built."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_concept_db_path()
        init_concept_database(self.db_path)
        self.connection_pool = SQLiteConnectionPool(
            self.db_path, max_connections=MAX_CONCEPT_DB_CONNECTIONS
        )

    def get_connection(self) -> ConnectionContext:
        return ConnectionContext(self.connection_pool)

    def close(self) -> None:
        self.connection_pool.close_all()

    def resolve_entity_name(
        self,
        conn: sqlite3.Connection,
        name: str,
        session_name: Optional[str],
        project: Optional[str],
        platform: Optional[str],
    ) -> Optional[str]:
        """Apply durable review aliases and suppressions for one exact scope."""
        resolved = name
        visited: set[str] = set()
        while resolved not in visited:
            visited.add(resolved)
            row = conn.execute(
                "SELECT canonical_name FROM concept_entity_aliases "
                "WHERE alias_name = ? AND session_name IS ? AND project IS ? "
                "AND platform IS ?",
                (resolved, session_name, project, platform),
            ).fetchone()
            if row is None:
                break
            resolved = str(row[0])

        suppressed = conn.execute(
            "SELECT 1 FROM concept_entity_suppressions "
            "WHERE name = ? AND session_name IS ? AND project IS ? AND platform IS ?",
            (resolved, session_name, project, platform),
        ).fetchone()
        return None if suppressed else resolved

    def get_or_create_entity(
        self,
        conn: sqlite3.Connection,
        name: str,
        entity_type: str,
        session_name: Optional[str],
        project: Optional[str],
        memory_id: str,
        name_embedding: Optional[bytes] = None,
        platform: Optional[str] = None,
    ) -> tuple[int, bool]:
        """Insert a new entity or append memory_id to an existing one's source
        list. Returns (entity_id, was_created) -- callers use was_created to
        run duplicate-candidate detection only once per entity ever, not on
        every re-mention across future builds. name_embedding is only stored
        on the INSERT branch; re-mentions never overwrite an existing
        entity's embedding.

        INSERT OR IGNORE + SELECT, not SELECT-then-INSERT -- the latter is a
        TOCTOU race under concurrent builds sharing a scope: two connections
        can both SELECT (no row found) before either INSERTs, and idx_entities_dedup
        (or the table-level UNIQUE, for non-NULL session_name/project) only
        stops one of the two INSERTs, not both from being attempted.

        The re-mention branch's append is a single atomic UPDATE via SQLite's
        JSON1 extension (json_insert/json_each), not a Python read-modify-
        write -- two connections both reading the same source_memory_ids
        array, appending different memory_ids, and whichever UPDATE commits
        last silently discarding the other's append was the same class of
        race as the INSERT-side one above, just on the re-mention path
        instead of the first-mention path."""
        cursor = conn.execute(
            "INSERT OR IGNORE INTO entities "
            "(name, type, session_name, project, platform, source_memory_ids, name_embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                entity_type,
                session_name,
                project,
                platform,
                json.dumps([memory_id]),
                name_embedding,
            ),
        )
        was_created = cursor.rowcount > 0

        row = conn.execute(
            "SELECT id FROM entities "
            "WHERE name = ? AND session_name IS ? AND project IS ? AND platform IS ?",
            (name, session_name, project, platform),
        ).fetchone()
        entity_id = row[0]

        if not was_created:
            conn.execute(
                "UPDATE entities SET source_memory_ids = "
                "json_insert(source_memory_ids, '$[#]', ?) "
                "WHERE id = ? AND NOT EXISTS ("
                "  SELECT 1 FROM json_each(entities.source_memory_ids) WHERE value = ?"
                ")",
                (memory_id, entity_id, memory_id),
            )

        return entity_id, was_created

    def find_similar_entities(
        self,
        conn: sqlite3.Connection,
        name_embedding: bytes,
        session_name: Optional[str],
        project: Optional[str],
        threshold: float,
        exclude_id: Optional[int] = None,
        platform: Optional[str] = None,
        name: Optional[str] = None,
    ) -> list[dict]:
        """Linear cosine-similarity scan against same-scope entities' stored
        name embeddings -- bounded by deployment scale (personal/small-team
        memory stores, CONCEPT_BUILD_ROW_CAP=500 memories/build), no vector
        index needed at this scale. Mirrors memory_scoring.py's batched-numpy
        cosine pattern. Returns candidates >= threshold, most-similar-first.

        With `name`, entities whose name carries different numbers are
        skipped: an embedding cannot tell `v2.1.0` from `v2.0.0`."""
        rows = conn.execute(
            "SELECT id, name, name_embedding FROM entities "
            "WHERE session_name IS ? AND project IS ? AND platform IS ? "
            "AND name_embedding IS NOT NULL AND id != ?",
            (
                session_name,
                project,
                platform,
                exclude_id if exclude_id is not None else -1,
            ),
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
        dim_skipped = 0
        for entity_id, row_name, emb_bytes in rows:
            try:
                vector = np.frombuffer(emb_bytes, dtype=np.float32)
            except Exception:
                continue
            if vector.shape[0] != query_vec.shape[0]:
                dim_skipped += 1
                continue
            vectors.append(vector)
            kept_rows.append((entity_id, row_name))

        if dim_skipped:
            _safe_print(
                "Concept similarity skipped "
                f"{dim_skipped} incompatible embedding vector(s); "
                "run marm-mcp-server --migrate-embeddings"
            )

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
            and not (name is not None and numbers_differ(name, kept_rows[i][1]))
        ]
        candidates.sort(key=lambda c: c["similarity"], reverse=True)
        return candidates

    def store_relationship(
        self,
        conn: sqlite3.Connection,
        source_id: int,
        target_id: int,
        predicate: str,
        memory_id: str,
        project: Optional[str],
        platform: Optional[str] = None,
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
            "(source_id, target_id, predicate, memory_id, project, platform) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, target_id, predicate, memory_id, project, platform),
        )
        return cursor.rowcount > 0

    def store_code_link(
        self,
        conn: sqlite3.Connection,
        entity_id: int,
        graph_qualified_name: str,
        project: str,
        confidence: float = 1.0,
        label: Optional[str] = None,
        file_path: Optional[str] = None,
        link_method: str = "exact_symbol",
        anchor_hash: Optional[str] = None,
    ) -> bool:
        """label/file_path are denormalized from marm-graph's response at build
        time (not in the original spec schema) so marm_concept_recall's
        linked_code field works even if marm-graph is unavailable at recall
        time -- avoids a live re-query dependency the spec's response shape
        otherwise implied without actually storing the data for it. Returns
        True only if a row was actually inserted (False on a dedup-index
        conflict from a repeat build), so callers can count real writes."""
        existing = conn.execute(
            "SELECT 1 FROM entity_code_links WHERE entity_id = ? "
            "AND graph_qualified_name = ?",
            (entity_id, graph_qualified_name),
        ).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO entity_code_links "
            "(entity_id, graph_qualified_name, project, confidence, label, file_path, "
            "link_method, resolved_at, last_verified_at, anchor_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(entity_id, graph_qualified_name) DO UPDATE SET "
            "project = excluded.project, confidence = excluded.confidence, "
            "label = excluded.label, file_path = excluded.file_path, "
            "link_method = excluded.link_method, "
            "resolved_at = COALESCE(entity_code_links.resolved_at, excluded.resolved_at), "
            "last_verified_at = excluded.last_verified_at, "
            # The anchor is the code the link was first made against; a later
            # hash that differs marks the code changed, and it stays changed.
            # A fingerprint from another hashing version is replaced, never
            # compared: the version is the text before the first ':'.
            "anchor_hash = CASE WHEN entity_code_links.anchor_hash IS NULL "
            "OR (excluded.anchor_hash IS NOT NULL "
            "AND substr(excluded.anchor_hash, 1, instr(excluded.anchor_hash, ':')) "
            "!= substr(entity_code_links.anchor_hash, 1, "
            "instr(entity_code_links.anchor_hash, ':'))) "
            "THEN COALESCE(excluded.anchor_hash, entity_code_links.anchor_hash) "
            "ELSE entity_code_links.anchor_hash END, "
            "code_changed_at = CASE WHEN entity_code_links.anchor_hash IS NOT NULL "
            "AND excluded.anchor_hash IS NOT NULL "
            "AND substr(excluded.anchor_hash, 1, instr(excluded.anchor_hash, ':')) "
            "= substr(entity_code_links.anchor_hash, 1, "
            "instr(entity_code_links.anchor_hash, ':')) "
            "AND excluded.anchor_hash != entity_code_links.anchor_hash "
            "THEN COALESCE(entity_code_links.code_changed_at, excluded.last_verified_at) "
            "ELSE entity_code_links.code_changed_at END",
            (
                entity_id,
                graph_qualified_name,
                project,
                confidence,
                label,
                file_path,
                link_method,
                now,
                now,
                anchor_hash,
            ),
        )
        return existing is None

    def entities_for_project(
        self,
        conn: sqlite3.Connection,
        project: str,
        after_id: int,
        limit: int,
    ) -> list[tuple[int, str]]:
        return [
            (int(row[0]), str(row[1]))
            for row in conn.execute(
                "SELECT id, name FROM entities WHERE project = ? AND id > ? "
                "ORDER BY id LIMIT ?",
                (project, after_id, limit),
            ).fetchall()
        ]

    def reconcile_code_link(
        self,
        conn: sqlite3.Connection,
        entity_id: int,
        project: str,
        outcome: dict,
        root_path: Optional[str] = None,
        not_after: Optional[float] = None,
    ) -> str:
        """Persist only authoritative resolutions for one entity/project pair."""
        status = outcome.get("status")
        if status == "matched":
            qualified_name = outcome.get("qualified_name")
            if not isinstance(qualified_name, str) or not qualified_name:
                return "unavailable"
            created = self.store_code_link(
                conn,
                entity_id,
                qualified_name,
                project,
                label=outcome.get("label"),
                file_path=outcome.get("file_path"),
                link_method="exact_symbol",
                anchor_hash=span_hash(
                    root_path,
                    outcome.get("file_path"),
                    outcome.get("start_line"),
                    outcome.get("end_line"),
                    not_after,
                )
                if root_path
                else None,
            )
            conn.execute(
                "DELETE FROM entity_code_links WHERE entity_id = ? AND project = ? "
                "AND link_method = 'exact_symbol' AND graph_qualified_name != ?",
                (entity_id, project, qualified_name),
            )
            return "created" if created else "refreshed"
        if status == "no_match":
            conn.execute(
                "DELETE FROM entity_code_links WHERE entity_id = ? AND project = ? "
                "AND link_method = 'exact_symbol'",
                (entity_id, project),
            )
            return "removed"
        return "retry"

    def cleanup_graph_project_links(self, project: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM entity_code_links WHERE project = ?", (project,)
            )
        return max(int(cursor.rowcount), 0)

    def graph_project_link_count(self, project: str) -> int:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM entity_code_links WHERE project = ?", (project,)
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def code_links_for_graph_project(
        self, project: str, limit: int = 200
    ) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT l.graph_qualified_name, l.file_path, l.link_method, "
                "l.last_verified_at, e.id, e.name, e.type FROM entity_code_links l "
                "JOIN entities e ON e.id = l.entity_id WHERE l.project = ? "
                "ORDER BY l.last_verified_at DESC, l.graph_qualified_name LIMIT ?",
                (project, max(1, min(limit, 200))),
            ).fetchall()
        return [
            {
                "qualified_name": row[0],
                "file_path": row[1] or "",
                "link_method": row[2],
                "last_verified_at": row[3],
                "entity_id": int(row[4]),
                "entity_name": row[5],
                "entity_type": row[6],
            }
            for row in rows
        ]

    def cleanup_deleted_memory_provenance(self, memory_ids: list[str]) -> dict:
        """Remove concept provenance for deleted memory rows.

        Concept cleanup runs after the memory delete commits. It is deliberately
        best-effort: failures are reported to the caller but never undo the
        durable memory mutation.
        """
        deleted_ids = {str(memory_id) for memory_id in memory_ids}
        if not deleted_ids:
            return {
                "status": "skipped",
                "relationships_deleted": 0,
                "entities_updated": 0,
                "entities_deleted": 0,
            }
        with self.get_connection() as conn:
            counts = self.retract_memory_provenance(conn, deleted_ids)
        return {"status": "success", **counts}

    def retract_memory_provenance(
        self,
        conn: sqlite3.Connection,
        memory_ids: Iterable[str],
        *,
        keep_entities: Iterable[int] = (),
        keep_relationships: Iterable[tuple[int, int, str]] = (),
    ) -> dict:
        """Withdraw what these memories contributed to the graph, on `conn`.

        What `keep_*` names is what a re-extraction just re-asserted, so it
        stays, with its ids. An entity another memory still cites keeps that
        citation; one left citing nothing goes, with its relationships and
        code links.
        """
        kept_entities = set(keep_entities)
        kept_relationships = set(keep_relationships)
        ids = {str(memory_id) for memory_id in memory_ids}
        if not ids:
            return {
                "relationships_deleted": 0,
                "entities_updated": 0,
                "entities_deleted": 0,
            }
        placeholders = ",".join("?" for _ in ids)
        stale = [
            rel_id
            for rel_id, source_id, target_id, predicate in conn.execute(
                "SELECT id, source_id, target_id, predicate FROM relationships "
                f"WHERE memory_id IN ({placeholders})",
                list(ids),
            ).fetchall()
            if (source_id, target_id, predicate) not in kept_relationships
        ]
        conn.executemany(
            "DELETE FROM relationships WHERE id = ?", [(rel_id,) for rel_id in stale]
        )
        # A textual prefilter; the JSON parse below is the real test.
        where = " OR ".join("source_memory_ids LIKE ?" for _ in ids)
        entity_rows = conn.execute(
            f"SELECT id, source_memory_ids FROM entities WHERE {where}",
            [f'%"{memory_id}"%' for memory_id in ids],
        ).fetchall()
        entities_updated = 0
        entities_deleted = 0
        for entity_id, source_json in entity_rows:
            if entity_id in kept_entities:
                continue
            try:
                source_ids = [str(item) for item in json.loads(source_json or "[]")]
            except (TypeError, ValueError, json.JSONDecodeError):
                source_ids = []
            remaining = [memory_id for memory_id in source_ids if memory_id not in ids]
            if remaining == source_ids:
                continue
            if remaining:
                conn.execute(
                    "UPDATE entities SET source_memory_ids = ? WHERE id = ?",
                    (json.dumps(remaining), entity_id),
                )
                entities_updated += 1
                continue
            conn.execute(
                "DELETE FROM relationships WHERE source_id = ? OR target_id = ?",
                (entity_id, entity_id),
            )
            conn.execute(
                "DELETE FROM entity_code_links WHERE entity_id = ?", (entity_id,)
            )
            conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
            entities_deleted += 1
        return {
            "relationships_deleted": len(stale),
            "entities_updated": entities_updated,
            "entities_deleted": entities_deleted,
        }
