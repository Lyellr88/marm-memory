"""Bounded, read-only concept context for smart and explicit recall."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable, Optional

from ..core.concept_db import get_concept_db_path, inspect_concept_schema
from ..core.response_limiter import MCPResponseLimiter

_RELATED_PREFIXES = (
    "related to ",
    "related-to ",
    "relationships of ",
    "connected to ",
    "connections of ",
)
_MAX_SEEDS = 20
_MAX_RELATED = 40
_MAX_CODE_LINKS = 20


def _empty_context(status: str) -> dict:
    return {
        "status": status,
        "entities": [],
        "related_entities": [],
        "linked_code": [],
        "seed_sources": {"memory_results": 0, "query_match": 0},
        "truncated": False,
    }


def _target_name(query: str) -> str:
    target = query.strip()
    lowered = target.lower()
    for prefix in _RELATED_PREFIXES:
        if lowered.startswith(prefix):
            return target[len(prefix) :].strip()
    return target


def _scope_sql(
    alias: str,
    *,
    session_name: Optional[str],
    project: Optional[str],
    platform: Optional[str],
) -> tuple[list[str], list[object]]:
    conditions: list[str] = []
    params: list[object] = []
    for column, value in (
        ("session_name", session_name),
        ("project", project),
        ("platform", platform),
    ):
        if value is not None:
            conditions.append(f"{alias}.{column} = ?")
            params.append(value)
    return conditions, params


def _entity(row: sqlite3.Row) -> dict:
    try:
        mention_count = len(json.loads(row["source_memory_ids"] or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        mention_count = 0
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "mention_count": mention_count,
    }


def traverse_graph(
    conn: sqlite3.Connection,
    seed_ids: list[int],
    *,
    depth: int,
    direction: str,
    limit: int,
    session_name: Optional[str],
    project: Optional[str],
    platform: Optional[str],
) -> tuple[list[dict], set[int], bool]:
    emitted: set[int] = set()
    expanded: set[int] = set(seed_ids)
    paths: dict[int, list[dict]] = {entity_id: [] for entity_id in seed_ids}
    frontier = list(seed_ids)
    results: list[dict] = []
    related_ids: set[int] = set()
    truncated = False

    entity_scope, entity_params = _scope_sql(
        "e", session_name=session_name, project=project, platform=platform
    )
    relationship_scope, relationship_params = _scope_sql(
        "r", session_name=None, project=project, platform=platform
    )
    scoped_where = [*entity_scope, *relationship_scope]
    scope_clause = "" if not scoped_where else " AND " + " AND ".join(scoped_where)
    scope_params = [*entity_params, *relationship_params]

    for hop in range(1, depth + 1):
        if not frontier or len(results) >= limit:
            break
        placeholders = ",".join("?" for _ in frontier)
        rows: list[sqlite3.Row] = []
        if direction in {"outgoing", "both"}:
            rows.extend(
                conn.execute(
                    f"""SELECT r.source_id AS from_id, e.id, e.name, e.type,
                               e.source_memory_ids, r.predicate
                        FROM relationships r JOIN entities e ON e.id = r.target_id
                        WHERE r.source_id IN ({placeholders}){scope_clause}
                        ORDER BY r.id LIMIT ?""",
                    [*frontier, *scope_params, limit + 1],
                ).fetchall()
            )
        if direction in {"incoming", "both"}:
            rows.extend(
                conn.execute(
                    f"""SELECT r.target_id AS from_id, e.id, e.name, e.type,
                               e.source_memory_ids, r.predicate
                        FROM relationships r JOIN entities e ON e.id = r.source_id
                        WHERE r.target_id IN ({placeholders}){scope_clause}
                        ORDER BY r.id LIMIT ?""",
                    [*frontier, *scope_params, limit + 1],
                ).fetchall()
            )

        next_frontier: list[int] = []
        for row in rows:
            from_id, neighbor_id, name, entity_type, _, predicate = row
            if neighbor_id in emitted or (hop > 1 and neighbor_id in expanded):
                continue
            if len(results) >= limit:
                truncated = True
                break
            emitted.add(neighbor_id)
            related_ids.add(neighbor_id)
            paths[neighbor_id] = [
                *paths.get(from_id, []),
                {"predicate": predicate, "name": name},
            ]
            item = {
                "name": name,
                "type": entity_type,
                "predicate": predicate,
                "hop": hop,
            }
            if depth > 1:
                item["path"] = paths[neighbor_id]
            results.append(item)
            if neighbor_id not in expanded:
                expanded.add(neighbor_id)
                next_frontier.append(neighbor_id)
        frontier = next_frontier

    return results, related_ids, truncated


def get_graph_context(
    *,
    query: str,
    memory_ids: Iterable[object] = (),
    session_name: Optional[str] = None,
    project: Optional[str] = None,
    platform: Optional[str] = None,
    limit: int = 10,
    depth: int = 2,
    direction: str = "both",
) -> dict:
    """Read a compact graph sidecar without creating or mutating graph data."""
    db_path = get_concept_db_path()
    schema_state = inspect_concept_schema(db_path)
    if schema_state == "rebuild_required":
        return _empty_context("rebuild_required")
    if schema_state != "current":
        return _empty_context("unavailable")

    seed_limit = min(max(limit, 1), _MAX_SEEDS)
    related_limit = min(max(limit * 3, limit), _MAX_RELATED)
    code_limit = min(max(limit * 2, limit), _MAX_CODE_LINKS)
    memory_values = list(dict.fromkeys(str(value) for value in memory_ids if value))

    try:
        uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0:
                return _empty_context("empty")

            scope_conditions, scope_params = _scope_sql(
                "e",
                session_name=session_name,
                project=project,
                platform=platform,
            )
            seed_rows: dict[int, sqlite3.Row] = {}
            memory_seed_ids: set[int] = set()
            query_seed_ids: set[int] = set()
            seeds_truncated = False

            if memory_values:
                placeholders = ",".join("?" for _ in memory_values)
                where = [
                    f"CAST(j.value AS TEXT) IN ({placeholders})",
                    *scope_conditions,
                ]
                rows = conn.execute(
                    f"""SELECT DISTINCT e.id, e.name, e.type, e.source_memory_ids
                        FROM entities e, json_each(e.source_memory_ids) j
                        WHERE {" AND ".join(where)}
                        ORDER BY e.id LIMIT ?""",
                    [*memory_values, *scope_params, seed_limit + 1],
                ).fetchall()
                seeds_truncated = len(rows) > seed_limit
                for row in rows[:seed_limit]:
                    seed_rows[row["id"]] = row
                    memory_seed_ids.add(row["id"])

            target = _target_name(query)
            if target and len(seed_rows) < seed_limit:
                escaped = (
                    target.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                )
                rows = conn.execute(
                    f"""SELECT e.id, e.name, e.type, e.source_memory_ids
                        FROM entities e
                        WHERE e.name LIKE ? ESCAPE '\\'
                        {"" if not scope_conditions else " AND " + " AND ".join(scope_conditions)}
                        ORDER BY e.name COLLATE NOCASE, e.id LIMIT ?""",
                    [f"%{escaped}%", *scope_params, seed_limit + 1],
                ).fetchall()
                for row in rows:
                    if len(seed_rows) >= seed_limit:
                        seeds_truncated = True
                        break
                    seed_rows.setdefault(row["id"], row)
                    query_seed_ids.add(row["id"])

            if not seed_rows:
                return _empty_context("empty")

            related, related_ids, traversal_truncated = traverse_graph(
                conn,
                list(seed_rows),
                depth=min(max(depth, 1), 5),
                direction=direction,
                limit=related_limit,
                session_name=session_name,
                project=project,
                platform=platform,
            )
            link_ids = list(dict.fromkeys([*seed_rows, *related_ids]))
            linked_code: list[dict] = []
            link_rows: list[sqlite3.Row] = []
            if link_ids:
                placeholders = ",".join("?" for _ in link_ids)
                link_rows = conn.execute(
                    f"""SELECT graph_qualified_name, label, file_path
                        FROM entity_code_links
                        WHERE entity_id IN ({placeholders})
                        ORDER BY entity_id, graph_qualified_name LIMIT ?""",
                    [*link_ids, code_limit + 1],
                ).fetchall()
                linked_code = [
                    {
                        "qualified_name": row["graph_qualified_name"],
                        "label": row["label"],
                        "file_path": row["file_path"],
                    }
                    for row in link_rows[:code_limit]
                ]

            return {
                "status": "available",
                "entities": [_entity(row) for row in seed_rows.values()],
                "related_entities": related,
                "linked_code": linked_code,
                "seed_sources": {
                    "memory_results": len(memory_seed_ids),
                    "query_match": len(query_seed_ids),
                },
                "truncated": (
                    seeds_truncated
                    or traversal_truncated
                    or len(link_rows) > code_limit
                ),
            }
    except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
        return _empty_context("unavailable")


def attach_graph_context(response: dict, graph_context: dict) -> dict:
    """Attach graph data while preserving primary results under the MCP limit."""
    context = {
        **graph_context,
        "entities": list(graph_context.get("entities", [])),
        "related_entities": list(graph_context.get("related_entities", [])),
        "linked_code": list(graph_context.get("linked_code", [])),
    }
    candidate = {**response, "graph_context": context}
    while (
        MCPResponseLimiter.estimate_response_size(candidate)
        > MCPResponseLimiter.CONTENT_LIMIT
    ):
        for key in ("linked_code", "related_entities", "entities"):
            values = context[key]
            if values:
                if len(values) == 1:
                    values.pop()
                else:
                    del values[max(1, len(values) // 2) :]
                context["truncated"] = True
                candidate = {**response, "graph_context": context}
                break
        else:
            context = _empty_context(graph_context.get("status", "unavailable"))
            context["truncated"] = True
            candidate = {**response, "graph_context": context}
            break

    if response.get("status") == "no_results" and context.get("status") == "available":
        candidate["status"] = "success"
    return candidate
