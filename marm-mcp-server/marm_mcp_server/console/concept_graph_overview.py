from __future__ import annotations

from collections import deque
from contextlib import closing
from pathlib import Path

from .concept_store import _connect, _entity, _schema_status

FULL_ATLAS_MAX_NODES = 750
FULL_ATLAS_MAX_EDGES = 6000
SAMPLED_ATLAS_MAX_NODES = 600
SAMPLED_ATLAS_MAX_EDGES = 4000
SAMPLED_ATLAS_RAW_EDGE_LIMIT = 12000


def graph_overview(
    db_path: Path,
    *,
    force_full: bool = False,
    project: str | None = None,
    session: str | None = None,
) -> dict:
    """Return the complete visual graph when requested, else a safe sample."""
    if project is not None and session is not None:
        raise ValueError("Choose either a project or session scope, not both.")

    scope_column = "project" if project is not None else "session_name"
    scope_value = project if project is not None else session
    entity_scope = f" WHERE e.{scope_column} = ?" if scope_value is not None else ""
    entity_scope_params = (scope_value,) if scope_value is not None else ()
    relationship_scope = ""
    relationship_scope_params: tuple[str, ...] = ()
    if scope_value is not None:
        relationship_scope = f"""
            JOIN entities source_entity ON source_entity.id = r.source_id
            JOIN entities target_entity ON target_entity.id = r.target_id
            WHERE source_entity.{scope_column} = ?
              AND target_entity.{scope_column} = ?
        """
        relationship_scope_params = (scope_value, scope_value)

    connection = _connect(db_path)
    if connection is None:
        return {
            "mode": "full",
            "schema_status": "unavailable",
            "total": {"nodes": 0, "edges": 0, "code_links": 0},
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
                "total": {"nodes": 0, "edges": 0, "code_links": 0},
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
        total_nodes = connection.execute(
            f"SELECT COUNT(*) FROM entities e{entity_scope}", entity_scope_params
        ).fetchone()[0]
        total_edges = connection.execute(
            f"SELECT COUNT(*) FROM relationships r{relationship_scope}",
            relationship_scope_params,
        ).fetchone()[0]
        code_link_scope = (
            f" WHERE e.{scope_column} = ?" if scope_value is not None else ""
        )
        total_code_links = connection.execute(
            f"""SELECT COUNT(*)
                FROM entity_code_links link
                JOIN entities e ON e.id = link.entity_id{code_link_scope}""",
            entity_scope_params,
        ).fetchone()[0]
        mode = (
            "full"
            if force_full
            or (
                total_nodes <= FULL_ATLAS_MAX_NODES
                and total_edges <= FULL_ATLAS_MAX_EDGES
            )
            else "sampled"
        )
        node_query = (
            """
            SELECT e.id, e.name, e.type, e.session_name, e.project, e.platform,
                   e.source_memory_ids, e.created_at,
                   (SELECT COUNT(*) FROM relationships r WHERE r.source_id = e.id OR r.target_id = e.id) AS degree
            FROM entities e
        """
            + entity_scope
        )
        if mode == "full":
            node_rows = connection.execute(
                node_query + " ORDER BY e.id", entity_scope_params
            ).fetchall()
            raw_edges = connection.execute(
                f"""SELECT r.id, r.source_id, r.target_id, r.predicate, r.memory_id
                    FROM relationships r{relationship_scope}
                    ORDER BY r.id""",
                relationship_scope_params,
            ).fetchall()
        else:
            node_rows = connection.execute(
                node_query + " ORDER BY degree DESC, e.id LIMIT ?",
                (*entity_scope_params, SAMPLED_ATLAS_MAX_NODES),
            ).fetchall()
            raw_edges = connection.execute(
                """WITH candidates AS (
                       SELECT e.id
                       FROM entities e
                       {entity_scope}
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
                   LIMIT ?""".format(entity_scope=entity_scope),
                (
                    *entity_scope_params,
                    SAMPLED_ATLAS_MAX_NODES,
                    SAMPLED_ATLAS_RAW_EDGE_LIMIT,
                ),
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
        "total": {
            "nodes": total_nodes,
            "edges": total_edges,
            "code_links": total_code_links,
        },
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
