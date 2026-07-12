"""Bounded read queries for MARM's isolated concept graph database."""

from __future__ import annotations

import json
import sqlite3
from array import array
from math import sqrt
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def summary(db_path: Path) -> dict:
    connection = _connect(db_path)
    if connection is None:
        return _empty_summary()
    with connection:
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
    with connection:
        rows = connection.execute(
            f"""
            SELECT e.id, e.name, e.type, e.session_name, e.project, e.source_memory_ids, e.created_at,
                   (SELECT COUNT(*) FROM relationships r WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
            FROM entities e{where}
            ORDER BY degree DESC, e.name COLLATE NOCASE
            LIMIT ?
            """,
            [*params, min(max(limit, 1), 100)],
        ).fetchall()
    return [_entity(row) for row in rows]


def neighborhood(
    db_path: Path,
    entity_id: int,
    depth: int = 1,
    direction: str = "both",
    predicate: str | None = None,
) -> dict | None:
    connection = _connect(db_path)
    if connection is None:
        return None
    depth = min(max(depth, 1), 3)
    with connection:
        seed = connection.execute(
            "SELECT id FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if seed is None:
            return None
        edge_map: dict[int, sqlite3.Row] = {}
        frontier = {entity_id}
        visited: set[int] = set()
        for _ in range(depth):
            if not frontier or len(edge_map) >= 400:
                break
            placeholders = ",".join("?" for _ in frontier)
            if direction == "outgoing":
                edge_scope = f"source_id IN ({placeholders})"
                params: list[object] = list(frontier)
            elif direction == "incoming":
                edge_scope = f"target_id IN ({placeholders})"
                params = list(frontier)
            else:
                edge_scope = (
                    f"(source_id IN ({placeholders}) OR target_id IN ({placeholders}))"
                )
                params = [*frontier, *frontier]
            if predicate:
                edge_scope += " AND predicate = ?"
                params.append(predicate)
            # Deterministic order, typed predicates ahead of co-occurrence,
            # so truncation always drops the lowest-value edges first.
            rows = connection.execute(
                f"""SELECT id, source_id, target_id, predicate, memory_id
                    FROM relationships
                    WHERE {edge_scope}
                    ORDER BY CASE WHEN predicate = 'co_occurs_with' THEN 1 ELSE 0 END, id
                    LIMIT ?""",
                [*params, 400 - len(edge_map)],
            ).fetchall()
            visited |= frontier
            next_frontier: set[int] = set()
            for edge in rows:
                edge_map[edge["id"]] = edge
                for endpoint in (edge["source_id"], edge["target_id"]):
                    if endpoint not in visited:
                        next_frontier.add(endpoint)
            frontier = next_frontier
        # Enforce the 200-node limit: keep edges (in ranked order) only while
        # their endpoints fit; edges between already-included nodes always fit.
        ids = {entity_id}
        edge_rows = []
        nodes_truncated = False
        for edge in edge_map.values():
            new_ids = {edge["source_id"], edge["target_id"]} - ids
            if len(ids) + len(new_ids) > 200:
                nodes_truncated = True
                continue
            ids |= new_ids
            edge_rows.append(edge)
        placeholders = ",".join("?" for _ in ids)
        node_rows = connection.execute(
            f"""
            SELECT e.id, e.name, e.type, e.session_name, e.project, e.source_memory_ids, e.created_at,
                   (SELECT COUNT(*) FROM relationships r WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
            FROM entities e WHERE e.id IN ({placeholders})
            """,
            list(ids),
        ).fetchall()
        links = connection.execute(
            f"""SELECT entity_id, graph_qualified_name, file_path
                FROM entity_code_links WHERE entity_id IN ({placeholders}) LIMIT 200""",
            list(ids),
        ).fetchall()
    linked_code: dict[int, list[dict]] = {}
    for link in links:
        linked_code.setdefault(link["entity_id"], []).append(
            {
                "qualified_name": link["graph_qualified_name"],
                "file_path": link["file_path"] or "",
            }
        )
    # A node's edges already in this response, so hidden = degree - included.
    included_edge_count: dict[int, int] = {}
    for edge in edge_rows:
        for endpoint in (edge["source_id"], edge["target_id"]):
            included_edge_count[endpoint] = included_edge_count.get(endpoint, 0) + 1
    return {
        "seed_id": entity_id,
        "nodes": [
            {
                **_entity(row),
                "hidden_neighbor_count": max(
                    0, row["degree"] - included_edge_count.get(row["id"], 0)
                ),
                "linked_code": linked_code.get(row["id"], []),
            }
            for row in node_rows
        ],
        "edges": [
            {
                "id": row["id"],
                "source": row["source_id"],
                "target": row["target_id"],
                "predicate": row["predicate"],
                "memory_id": row["memory_id"],
            }
            for row in edge_rows
        ],
        "limits": {"nodes": 200, "edges": 400},
        "truncated": nodes_truncated or len(edge_map) >= 400,
    }


def get_entity(db_path: Path, entity_id: int) -> dict | None:
    connection = _connect(db_path)
    if connection is None:
        return None
    with connection:
        row = connection.execute(
            """
            SELECT e.id, e.name, e.type, e.session_name, e.project, e.source_memory_ids,
                   e.created_at,
                   (SELECT COUNT(*) FROM relationships r
                    WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
            FROM entities e WHERE e.id = ?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        links = connection.execute(
            """SELECT graph_qualified_name, file_path
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
            }
            for link in links
        ],
    }


def build_runs(db_path: Path, limit: int = 20) -> list[dict]:
    connection = _connect(db_path)
    if connection is None:
        return []
    try:
        with connection:
            rows = connection.execute(
                """SELECT id, scope_type, scope_value, status, memories_processed,
                          entities_extracted, relationships_created, code_links_created,
                          duplicate_candidates, duration_ms, error_code, created_at,
                          started_at, finished_at
                   FROM concept_build_runs
                   ORDER BY created_at DESC LIMIT ?""",
                (min(max(limit, 1), 50),),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [_build_run(row) for row in rows]


def get_build_run(db_path: Path, run_id: str) -> dict | None:
    connection = _connect(db_path)
    if connection is None:
        return None
    try:
        with connection:
            row = connection.execute(
                """SELECT id, scope_type, scope_value, status, memories_processed,
                          entities_extracted, relationships_created, code_links_created,
                          duplicate_candidates, duration_ms, error_code, created_at,
                          started_at, finished_at
                   FROM concept_build_runs WHERE id = ?""",
                (run_id,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return _build_run(row) if row else None


def duplicates(db_path: Path, limit: int = 100, threshold: float = 0.88) -> list[dict]:
    connection = _connect(db_path)
    if connection is None:
        return []
    try:
        with connection:
            rows = connection.execute(
                """
                SELECT e.id, e.name, e.type, e.session_name, e.project, e.source_memory_ids,
                       e.created_at, e.name_embedding,
                       (SELECT COUNT(*) FROM relationships r
                        WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
                FROM entities e
                WHERE e.name_embedding IS NOT NULL
                ORDER BY degree DESC, e.id
                LIMIT 300
                """
            ).fetchall()
    except sqlite3.OperationalError:
        return []

    groups: dict[tuple[str | None, str | None], list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault((row["session_name"], row["project"]), []).append(row)

    candidates: list[dict] = []
    for scoped_rows in groups.values():
        vectors = [(row, _unit_vector(row["name_embedding"])) for row in scoped_rows]
        for index, (entity_a, vector_a) in enumerate(vectors):
            if vector_a is None:
                continue
            for entity_b, vector_b in vectors[index + 1 :]:
                if vector_b is None:
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
    return candidates[: min(max(limit, 1), 100)]


def graph_overview(db_path: Path, limit_nodes: int = 150) -> dict:
    """The most-connected slice of the whole graph: top-N entities by degree
    plus every relationship among them. Landing view for the Knowledge page."""
    connection = _connect(db_path)
    if connection is None:
        return {
            "seed_id": None,
            "nodes": [],
            "edges": [],
            "limits": {"nodes": limit_nodes, "edges": 600},
            "truncated": False,
        }
    limit_nodes = min(max(limit_nodes, 10), 300)
    with connection:
        node_rows = connection.execute(
            """
            SELECT e.id, e.name, e.type, e.session_name, e.project, e.source_memory_ids, e.created_at,
                   (SELECT COUNT(*) FROM relationships r WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
            FROM entities e
            ORDER BY degree DESC, e.name COLLATE NOCASE
            LIMIT ?
            """,
            (limit_nodes,),
        ).fetchall()
        ids = [row["id"] for row in node_rows]
        edge_rows: list[sqlite3.Row] = []
        if ids:
            placeholders = ",".join("?" for _ in ids)
            # Deterministic order, typed predicates ahead of co-occurrence,
            # so truncation always drops the lowest-value edges first.
            edge_rows = connection.execute(
                f"""SELECT id, source_id, target_id, predicate, memory_id
                    FROM relationships
                    WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})
                    ORDER BY CASE WHEN predicate = 'co_occurs_with' THEN 1 ELSE 0 END, id
                    LIMIT 600""",
                [*ids, *ids],
            ).fetchall()
    included_edge_count: dict[int, int] = {}
    for edge in edge_rows:
        for endpoint in (edge["source_id"], edge["target_id"]):
            included_edge_count[endpoint] = included_edge_count.get(endpoint, 0) + 1
    return {
        "seed_id": None,
        "nodes": [
            {
                **_entity(row),
                "hidden_neighbor_count": max(
                    0, row["degree"] - included_edge_count.get(row["id"], 0)
                ),
                "linked_code": [],
            }
            for row in node_rows
        ],
        "edges": [
            {
                "id": row["id"],
                "source": row["source_id"],
                "target": row["target_id"],
                "predicate": row["predicate"],
                "memory_id": row["memory_id"],
            }
            for row in edge_rows
        ],
        "limits": {"nodes": limit_nodes, "edges": 600},
        "truncated": len(edge_rows) >= 600,
    }


def _entity(row: sqlite3.Row) -> dict:
    source_ids = json.loads(row["source_memory_ids"] or "[]")
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "session_name": row["session_name"],
        "project": row["project"],
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
        "entities_extracted": row["entities_extracted"],
        "relationships_created": row["relationships_created"],
        "code_links_created": row["code_links_created"],
        "duplicate_candidates": row["duplicate_candidates"],
        "duration_ms": row["duration_ms"],
        "error_code": row["error_code"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
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
    }
