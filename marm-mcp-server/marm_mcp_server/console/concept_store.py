from __future__ import annotations

import json
import sqlite3
from array import array
from contextlib import closing
from math import sqrt
from pathlib import Path

from ..core.concept_db import CONCEPT_SCHEMA_VERSION

_CURRENT_CONCEPT_SCHEMA_VERSION = str(CONCEPT_SCHEMA_VERSION)


def _connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _schema_status(connection: sqlite3.Connection) -> str:
    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "entities" not in tables or "relationships" not in tables:
            return "rebuild_required"
        entity_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(entities)")
        }
        relationship_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(relationships)")
        }
        if "platform" not in entity_columns or "platform" not in relationship_columns:
            return "rebuild_required"
        if "concept_schema_metadata" not in tables:
            return "rebuild_required"
        row = connection.execute(
            "SELECT value FROM concept_schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        return (
            "current"
            if row is not None and row["value"] == _CURRENT_CONCEPT_SCHEMA_VERSION
            else "rebuild_required"
        )
    except sqlite3.Error:
        return "unavailable"


def _build_run_columns(connection: sqlite3.Connection) -> tuple[str, str, str, str]:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(concept_build_runs)")
    }
    return (
        "memories_total" if "memories_total" in columns else "0 AS memories_total",
        "last_progress_at"
        if "last_progress_at" in columns
        else "NULL AS last_progress_at",
        "cancel_requested_at"
        if "cancel_requested_at" in columns
        else "NULL AS cancel_requested_at",
        "cancelled_at" if "cancelled_at" in columns else "NULL AS cancelled_at",
    )


def _code_link_evidence_columns(connection: sqlite3.Connection) -> tuple[str, str]:
    """Read link evidence without requiring the writer to have migrated first."""
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(entity_code_links)")
    }
    return (
        "link_method"
        if "link_method" in columns
        else "'legacy_exact_symbol' AS link_method",
        "last_verified_at"
        if "last_verified_at" in columns
        else "NULL AS last_verified_at",
    )


def graph_version(db_path: Path) -> dict:
    """A cheap change marker the Console can poll while the Explorer is open.

    Four counters and the last build's finish time, so a poll costs two counts
    and two max lookups instead of serializing the whole atlas. Only the graph
    itself is refetched, and only when this moves.

    It does not move when an existing entity is merely mentioned by another
    memory: that adds provenance to a row rather than creating one. The node
    is already on screen in that case, which is what this exists to deliver.
    """
    connection = _connect(db_path)
    if connection is None:
        return {"schema_status": "unavailable", "version": "unavailable"}
    with closing(connection), connection:
        schema_status = _schema_status(connection)
        if schema_status != "current":
            return {"schema_status": schema_status, "version": schema_status}
        entities, max_entity = connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM entities"
        ).fetchone()
        relationships, max_relationship = connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM relationships"
        ).fetchone()
        last_build = connection.execute(
            "SELECT COALESCE(MAX(finished_at), '') FROM concept_build_runs"
        ).fetchone()[0]
    return {
        "schema_status": schema_status,
        "version": f"{entities}:{max_entity}:{relationships}:{max_relationship}:{last_build}",
    }


def summary(db_path: Path) -> dict:
    connection = _connect(db_path)
    if connection is None:
        return _empty_summary()
    with closing(connection), connection:
        schema_status = _schema_status(connection)
        if schema_status != "current":
            return {
                **_empty_summary(),
                "schema_status": schema_status,
            }
        entity_count = connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        relationship_count = connection.execute(
            "SELECT COUNT(*) FROM relationships"
        ).fetchone()[0]
        code_link_count = connection.execute(
            "SELECT COUNT(*) FROM entity_code_links"
        ).fetchone()[0]
        by_type = [
            {"type": row["type"], "count": row["count"]}
            for row in connection.execute(
                "SELECT type, COUNT(*) AS count FROM entities GROUP BY type ORDER BY count DESC, type"
            )
        ]
        by_project = [
            {"project": row["project"], "count": row["count"]}
            for row in connection.execute(
                """SELECT project, COUNT(*) AS count FROM entities
                   WHERE project IS NOT NULL AND project != ''
                   GROUP BY project ORDER BY count DESC, project"""
            )
        ]
    return {
        "entities": entity_count,
        "relationships": relationship_count,
        "code_links": code_link_count,
        "by_type": by_type,
        "by_project": by_project,
        "recent_builds": [],
        "schema_status": schema_status,
    }


def search(
    db_path: Path,
    *,
    q: str | None,
    project: str | None,
    session: str | None,
    entity_type: str | None,
    limit: int,
) -> list[dict]:
    connection = _connect(db_path)
    if connection is None:
        return []
    clauses: list[str] = []
    params: list[object] = []
    if q:
        clauses.append("e.name LIKE ? ESCAPE '\\'")
        params.append(
            "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
    for column, value in (
        ("e.project", project),
        ("e.session_name", session),
        ("e.type", entity_type),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(connection), connection:
        if _schema_status(connection) != "current":
            return []
        rows = connection.execute(
            f"""
            SELECT e.id, e.name, e.type, e.session_name, e.project, e.platform,
                   e.source_memory_ids, e.created_at,
                   (SELECT COUNT(*) FROM relationships r WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
            FROM entities e{where}
            ORDER BY degree DESC, e.name COLLATE NOCASE
            LIMIT ?
            """,
            [*params, min(max(limit, 1), 100)],
        ).fetchall()
    return [_entity(row) for row in rows]


def get_entity(db_path: Path, entity_id: int) -> dict | None:
    connection = _connect(db_path)
    if connection is None:
        return None
    with closing(connection), connection:
        if _schema_status(connection) != "current":
            return None
        row = connection.execute(
            """
            SELECT e.id, e.name, e.type, e.session_name, e.project, e.platform,
                   e.source_memory_ids,
                   e.created_at,
                   (SELECT COUNT(*) FROM relationships r
                    WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
            FROM entities e WHERE e.id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        link_method, last_verified_at = _code_link_evidence_columns(connection)
        links = connection.execute(
            f"""SELECT graph_qualified_name, file_path, {link_method}, {last_verified_at}
                FROM entity_code_links WHERE entity_id = ?
                ORDER BY graph_qualified_name LIMIT 50""",
            (entity_id,),
        ).fetchall()
    try:
        source_memory_ids = json.loads(row["source_memory_ids"] or "[]")
    except (TypeError, json.JSONDecodeError):
        source_memory_ids = []
    return {
        **_entity(row),
        "source_memory_ids": [str(memory_id) for memory_id in source_memory_ids],
        "linked_code": [
            {
                "qualified_name": link["graph_qualified_name"],
                "file_path": link["file_path"] or "",
                "link_method": link["link_method"],
                "last_verified_at": link["last_verified_at"],
            }
            for link in links
        ],
    }


def build_runs(db_path: Path, limit: int = 20) -> list[dict]:
    connection = _connect(db_path)
    if connection is None:
        return []
    try:
        with closing(connection), connection:
            (
                memories_total_column,
                progress_column,
                cancel_requested_column,
                cancelled_column,
            ) = _build_run_columns(connection)
            rows = connection.execute(
                f"""SELECT id, scope_type, scope_value, status, memories_processed,
                          {memories_total_column},
                          entities_extracted, relationships_created, code_links_created,
                          duplicate_candidates, duration_ms, error_code, created_at,
                          started_at, {progress_column}, {cancel_requested_column},
                          {cancelled_column}, finished_at
                   FROM concept_build_runs
                   ORDER BY created_at DESC LIMIT ?""",
                (min(max(limit, 1), 100),),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [_build_run(row) for row in rows]


def get_build_run(db_path: Path, run_id: str) -> dict | None:
    connection = _connect(db_path)
    if connection is None:
        return None
    try:
        with closing(connection), connection:
            (
                memories_total_column,
                progress_column,
                cancel_requested_column,
                cancelled_column,
            ) = _build_run_columns(connection)
            row = connection.execute(
                f"""SELECT id, scope_type, scope_value, status, memories_processed,
                          {memories_total_column},
                          entities_extracted, relationships_created, code_links_created,
                          duplicate_candidates, duration_ms, error_code, created_at,
                          started_at, {progress_column}, {cancel_requested_column},
                          {cancelled_column}, finished_at
                   FROM concept_build_runs WHERE id = ?""",
                (run_id,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return _build_run(row) if row else None


_DUPLICATE_SCAN_LIMIT = 300
_DUPLICATE_RESULT_LIMIT = 100
_DUPLICATE_THRESHOLD = 0.88


def _duplicate_candidates(db_path: Path, threshold: float) -> tuple[list[dict], int]:
    connection = _connect(db_path)
    if connection is None:
        return [], 0
    try:
        with closing(connection), connection:
            if _schema_status(connection) != "current":
                return [], 0
            rows = connection.execute(
                """
                SELECT e.id, e.name, e.type, e.session_name, e.project, e.platform,
                       e.source_memory_ids,
                       e.created_at, e.name_embedding,
                       (SELECT COUNT(*) FROM relationships r
                        WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
                FROM entities e
                WHERE e.name_embedding IS NOT NULL
                ORDER BY degree DESC, e.id
                LIMIT ?
                """,
                (_DUPLICATE_SCAN_LIMIT,),
            ).fetchall()
            review_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'concept_duplicate_dismissals'"
                ).fetchall()
            }
            dismissed = (
                {
                    (row[0], row[1], row[2], row[3], row[4])
                    for row in connection.execute(
                        "SELECT name_a, name_b, session_name, project, platform "
                        "FROM concept_duplicate_dismissals"
                    ).fetchall()
                }
                if review_tables
                else set()
            )
    except sqlite3.OperationalError:
        return [], 0

    groups: dict[tuple[str | None, str | None, str | None], list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(
            (row["session_name"], row["project"], row["platform"]), []
        ).append(row)

    candidates: list[dict] = []
    for scoped_rows in groups.values():
        vectors = [(row, _unit_vector(row["name_embedding"])) for row in scoped_rows]
        for index, (entity_a, vector_a) in enumerate(vectors):
            if vector_a is None:
                continue
            for entity_b, vector_b in vectors[index + 1 :]:
                if vector_b is None:
                    continue
                names = tuple(sorted((str(entity_a["name"]), str(entity_b["name"]))))
                dismissal_key = (
                    names[0],
                    names[1],
                    entity_a["session_name"],
                    entity_a["project"],
                    entity_a["platform"],
                )
                if dismissal_key in dismissed:
                    continue
                similarity = sum(a * b for a, b in zip(vector_a, vector_b))
                if similarity >= threshold:
                    candidates.append(
                        {
                            "entity_a": _entity(entity_a),
                            "entity_b": _entity(entity_b),
                            "similarity": round(similarity, 4),
                        }
                    )
    candidates.sort(key=lambda item: item["similarity"], reverse=True)
    return candidates, len(rows)


def duplicates(
    db_path: Path,
    limit: int = _DUPLICATE_RESULT_LIMIT,
    threshold: float = _DUPLICATE_THRESHOLD,
) -> list[dict]:
    candidates, _ = _duplicate_candidates(db_path, threshold)
    return candidates[: min(max(limit, 1), _DUPLICATE_RESULT_LIMIT)]


def duplicate_report(
    db_path: Path,
    limit: int = _DUPLICATE_RESULT_LIMIT,
    offset: int = 0,
    threshold: float = _DUPLICATE_THRESHOLD,
) -> dict:
    candidates, scanned_entities = _duplicate_candidates(db_path, threshold)
    result_limit = min(max(limit, 1), _DUPLICATE_RESULT_LIMIT)
    result_offset = max(offset, 0)
    items = candidates[result_offset : result_offset + result_limit]
    return {
        "items": items,
        "total": len(candidates),
        "threshold": threshold,
        "scanned_entities": scanned_entities,
        "scan_limit": _DUPLICATE_SCAN_LIMIT,
        "result_limit": result_limit,
        "offset": result_offset,
        "has_more": result_offset + len(items) < len(candidates),
    }


def _entity(row: sqlite3.Row) -> dict:
    source_ids = json.loads(row["source_memory_ids"] or "[]")
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "session_name": row["session_name"],
        "project": row["project"],
        "platform": row["platform"] if "platform" in row.keys() else None,
        "mention_count": len(source_ids),
        "degree": row["degree"],
        "created_at": row["created_at"],
    }


def _build_run(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "scope_type": row["scope_type"],
        "scope_value": row["scope_value"],
        "status": row["status"],
        "memories_processed": row["memories_processed"],
        "memories_total": row["memories_total"],
        "entities_extracted": row["entities_extracted"],
        "relationships_created": row["relationships_created"],
        "code_links_created": row["code_links_created"],
        "duplicate_candidates": row["duplicate_candidates"],
        "duration_ms": row["duration_ms"],
        "error_code": row["error_code"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "last_progress_at": row["last_progress_at"],
        "cancel_requested_at": row["cancel_requested_at"],
        "cancelled_at": row["cancelled_at"],
        "finished_at": row["finished_at"],
    }


def _unit_vector(value: bytes) -> tuple[float, ...] | None:
    try:
        vector = array("f")
        vector.frombytes(value)
    except (TypeError, ValueError):
        return None
    magnitude = sqrt(sum(component * component for component in vector))
    if not magnitude:
        return None
    return tuple(component / magnitude for component in vector)


def _empty_summary() -> dict:
    return {
        "entities": 0,
        "relationships": 0,
        "code_links": 0,
        "by_type": [],
        "by_project": [],
        "recent_builds": [],
        "schema_status": "unavailable",
    }
