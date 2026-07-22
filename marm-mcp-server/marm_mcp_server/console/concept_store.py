"""Bounded read queries for MARM's isolated concept graph database."""

from __future__ import annotations

import json
import sqlite3
from array import array
from collections import deque
from contextlib import closing
from math import sqrt
from pathlib import Path

FULL_ATLAS_MAX_NODES = 750
FULL_ATLAS_MAX_EDGES = 6000
SAMPLED_ATLAS_MAX_NODES = 600
SAMPLED_ATLAS_MAX_EDGES = 4000
SAMPLED_ATLAS_RAW_EDGE_LIMIT = 12000
_CURRENT_CONCEPT_SCHEMA_VERSION = "2"


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
    with closing(connection), connection:
        if _schema_status(connection) != "current":
            return None
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
            SELECT e.id, e.name, e.type, e.session_name, e.project, e.platform,
                   e.source_memory_ids, e.created_at,
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
        with closing(connection), connection:
            if _schema_status(connection) != "current":
                return []
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
        with closing(connection), connection:
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
        with closing(connection), connection:
            if _schema_status(connection) != "current":
                return []
            rows = connection.execute("""
                SELECT e.id, e.name, e.type, e.session_name, e.project, e.platform,
                       e.source_memory_ids,
                       e.created_at, e.name_embedding,
                       (SELECT COUNT(*) FROM relationships r
                        WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
                FROM entities e
                WHERE e.name_embedding IS NOT NULL
                ORDER BY degree DESC, e.id
                LIMIT 300
                """).fetchall()
    except sqlite3.OperationalError:
        return []

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


def graph_overview(db_path: Path) -> dict:
    """Return the complete visual graph when safe, else a connected sample."""
    connection = _connect(db_path)
    if connection is None:
        return {
            "mode": "full",
            "schema_status": "unavailable",
            "total": {"nodes": 0, "edges": 0},
            "rendered": {"nodes": 0, "edges": 0},
            "sample_reason": None,
            "seed_id": None,
            "nodes": [],
            "edges": [],
            "limits": {
                "nodes": FULL_ATLAS_MAX_NODES,
                "edges": FULL_ATLAS_MAX_EDGES,
            },
            "truncated": False,
        }
    with closing(connection), connection:
        schema_status = _schema_status(connection)
        if schema_status != "current":
            return {
                "mode": "full",
                "schema_status": schema_status,
                "total": {"nodes": 0, "edges": 0},
                "rendered": {"nodes": 0, "edges": 0},
                "sample_reason": "platform-aware concept rebuild required",
                "seed_id": None,
                "nodes": [],
                "edges": [],
                "limits": {
                    "nodes": FULL_ATLAS_MAX_NODES,
                    "edges": FULL_ATLAS_MAX_EDGES,
                },
                "truncated": False,
            }
        total_nodes = connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        total_edges = connection.execute(
            "SELECT COUNT(*) FROM relationships"
        ).fetchone()[0]
        mode = (
            "full"
            if total_nodes <= FULL_ATLAS_MAX_NODES
            and total_edges <= FULL_ATLAS_MAX_EDGES
            else "sampled"
        )
        node_query = """
            SELECT e.id, e.name, e.type, e.session_name, e.project, e.platform,
                   e.source_memory_ids, e.created_at,
                   (SELECT COUNT(*) FROM relationships r WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
            FROM entities e
        """
        if mode == "full":
            node_rows = connection.execute(node_query + " ORDER BY e.id").fetchall()
            raw_edges = connection.execute(
                """SELECT id, source_id, target_id, predicate, memory_id
                   FROM relationships ORDER BY id"""
            ).fetchall()
        else:
            node_rows = connection.execute(
                node_query + " ORDER BY degree DESC, e.id LIMIT ?",
                (SAMPLED_ATLAS_MAX_NODES,),
            ).fetchall()
            raw_edges = connection.execute(
                """WITH candidates AS (
                       SELECT e.id
                       FROM entities e
                       ORDER BY (
                           SELECT COUNT(*) FROM relationships r
                           WHERE r.source_id = e.id OR r.target_id = e.id
                       ) DESC, e.id
                       LIMIT ?
                   )
                   SELECT id, source_id, target_id, predicate, memory_id
                   FROM relationships
                   WHERE source_id IN (SELECT id FROM candidates)
                     AND target_id IN (SELECT id FROM candidates)
                   ORDER BY id
                   LIMIT ?""",
                (SAMPLED_ATLAS_MAX_NODES, SAMPLED_ATLAS_RAW_EDGE_LIMIT),
            ).fetchall()

    edge_groups: dict[tuple[int, int, str], dict] = {}
    for row in raw_edges:
        key = (row["source_id"], row["target_id"], row["predicate"])
        group = edge_groups.setdefault(
            key,
            {
                "id": row["id"],
                "source": row["source_id"],
                "target": row["target_id"],
                "predicate": row["predicate"],
                "memory_id": row["memory_id"],
                "weight": 0,
                "evidence_count": 0,
            },
        )
        group["weight"] += 1
        group["evidence_count"] += 1

    selected_ids = {row["id"] for row in node_rows}
    selected_edge_keys = set(edge_groups)
    limits = {"nodes": FULL_ATLAS_MAX_NODES, "edges": FULL_ATLAS_MAX_EDGES}
    sample_reason = None

    if mode == "sampled":
        limits = {
            "nodes": SAMPLED_ATLAS_MAX_NODES,
            "edges": SAMPLED_ATLAS_MAX_EDGES,
        }
        sample_reason = (
            f"graph exceeds full atlas budget ({FULL_ATLAS_MAX_NODES} nodes / "
            f"{FULL_ATLAS_MAX_EDGES} relationships)"
        )
        degrees = {row["id"]: row["degree"] for row in node_rows}
        adjacency: dict[int, list[tuple[int, tuple[int, int, str], int]]] = {}
        for key, edge in edge_groups.items():
            source, target, _ = key
            adjacency.setdefault(source, []).append((target, key, edge["weight"]))
            adjacency.setdefault(target, []).append((source, key, edge["weight"]))

        selected_ids = set()
        tree_edge_keys: list[tuple[int, int, str]] = []
        ranked_nodes = sorted(degrees, key=lambda node_id: (-degrees[node_id], node_id))
        for root in ranked_nodes:
            if len(selected_ids) >= SAMPLED_ATLAS_MAX_NODES:
                break
            if root in selected_ids:
                continue
            selected_ids.add(root)
            frontier = deque([root])
            while frontier and len(selected_ids) < SAMPLED_ATLAS_MAX_NODES:
                current = frontier.popleft()
                neighbors = sorted(
                    adjacency.get(current, []),
                    key=lambda item: (
                        -item[2],
                        -degrees.get(item[0], 0),
                        item[0],
                        item[1],
                    ),
                )
                for neighbor, edge_key, _ in neighbors:
                    if neighbor in selected_ids:
                        continue
                    selected_ids.add(neighbor)
                    tree_edge_keys.append(edge_key)
                    frontier.append(neighbor)
                    if len(selected_ids) >= SAMPLED_ATLAS_MAX_NODES:
                        break

        induced_keys = [
            key
            for key in edge_groups
            if key[0] in selected_ids and key[1] in selected_ids
        ]
        tree_set = set(tree_edge_keys)
        induced_keys.sort(
            key=lambda key: (
                0 if key in tree_set else 1,
                1 if key[2] == "co_occurs_with" else 0,
                -edge_groups[key]["weight"],
                key,
            )
        )
        selected_edge_keys = set(induced_keys[:SAMPLED_ATLAS_MAX_EDGES])

    selected_nodes = [row for row in node_rows if row["id"] in selected_ids]
    selected_edges = [
        edge_groups[key]
        for key in sorted(
            selected_edge_keys,
            key=lambda key: (
                1 if key[2] == "co_occurs_with" else 0,
                -edge_groups[key]["weight"],
                key,
            ),
        )
    ]
    included_edge_count: dict[int, int] = {}
    for edge in selected_edges:
        included_edge_count[edge["source"]] = (
            included_edge_count.get(edge["source"], 0) + edge["weight"]
        )
        included_edge_count[edge["target"]] = (
            included_edge_count.get(edge["target"], 0) + edge["weight"]
        )

    return {
        "mode": mode,
        "schema_status": schema_status,
        "total": {"nodes": total_nodes, "edges": total_edges},
        "rendered": {"nodes": len(selected_nodes), "edges": len(selected_edges)},
        "sample_reason": sample_reason,
        "seed_id": None,
        "nodes": [
            {
                **_entity(row),
                "hidden_neighbor_count": max(
                    0, row["degree"] - included_edge_count.get(row["id"], 0)
                ),
                "linked_code": [],
            }
            for row in selected_nodes
        ],
        "edges": selected_edges,
        "limits": limits,
        "truncated": mode == "sampled",
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
        "schema_status": "unavailable",
    }
