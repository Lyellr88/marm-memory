from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .concept_store import (
    _code_link_evidence_columns,
    _connect,
    _entity,
    _schema_status,
)


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
        link_method, last_verified_at = _code_link_evidence_columns(connection)
        links = connection.execute(
            f"""SELECT entity_id, graph_qualified_name, file_path, {link_method}, {last_verified_at}
                FROM entity_code_links WHERE entity_id IN ({placeholders}) LIMIT 200""",
            list(ids),
        ).fetchall()
    linked_code: dict[int, list[dict]] = {}
    for link in links:
        linked_code.setdefault(link["entity_id"], []).append(
            {
                "qualified_name": link["graph_qualified_name"],
                "file_path": link["file_path"] or "",
                "link_method": link["link_method"],
                "last_verified_at": link["last_verified_at"],
            }
        )
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
