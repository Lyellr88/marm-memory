"""Durable user decisions for concept duplicate review."""

from __future__ import annotations

import json
from typing import Literal

from .concept_db import ConceptDB


class ConceptReviewError(ValueError):
    """The requested review action is invalid for the current graph."""


def _entity(conn, entity_id: int):
    return conn.execute(
        "SELECT id, name, type, session_name, project, platform, "
        "source_memory_ids, name_embedding FROM entities WHERE id = ?",
        (entity_id,),
    ).fetchone()


def _same_scope(entity_a, entity_b) -> bool:
    return entity_a[3:6] == entity_b[3:6]


def dismiss_duplicate(db_path: str, entity_a_id: int, entity_b_id: int) -> dict:
    if entity_a_id == entity_b_id:
        raise ConceptReviewError("Choose two different concepts.")
    database = ConceptDB(db_path)
    try:
        with database.get_connection() as conn:
            entity_a = _entity(conn, entity_a_id)
            entity_b = _entity(conn, entity_b_id)
            if entity_a is None or entity_b is None:
                raise ConceptReviewError("One of these concepts no longer exists.")
            if not _same_scope(entity_a, entity_b):
                raise ConceptReviewError(
                    "Duplicate decisions must stay within one scope."
                )
            name_a, name_b = sorted((str(entity_a[1]), str(entity_b[1])))
            conn.execute(
                "INSERT OR IGNORE INTO concept_duplicate_dismissals "
                "(name_a, name_b, session_name, project, platform) "
                "VALUES (?, ?, ?, ?, ?)",
                (name_a, name_b, entity_a[3], entity_a[4], entity_a[5]),
            )
        return {"status": "dismissed"}
    finally:
        database.close()


def merge_entities(
    db_path: str,
    entity_a_id: int,
    entity_b_id: int,
    keep: Literal["a", "b"],
) -> dict:
    if entity_a_id == entity_b_id:
        raise ConceptReviewError("Choose two different concepts.")
    database = ConceptDB(db_path)
    try:
        with database.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            entity_a = _entity(conn, entity_a_id)
            entity_b = _entity(conn, entity_b_id)
            if entity_a is None or entity_b is None:
                raise ConceptReviewError("One of these concepts no longer exists.")
            if not _same_scope(entity_a, entity_b):
                raise ConceptReviewError(
                    "Concepts can only be merged within one scope."
                )

            winner, loser = (
                (entity_a, entity_b) if keep == "a" else (entity_b, entity_a)
            )
            winner_id, loser_id = int(winner[0]), int(loser[0])
            winner_sources = json.loads(winner[6] or "[]")
            loser_sources = json.loads(loser[6] or "[]")
            combined_sources = list(dict.fromkeys([*winner_sources, *loser_sources]))
            conn.execute(
                "UPDATE entities SET source_memory_ids = ?, "
                "name_embedding = COALESCE(name_embedding, ?) WHERE id = ?",
                (json.dumps(combined_sources), loser[7], winner_id),
            )

            conn.execute(
                "INSERT OR IGNORE INTO entity_code_links "
                "(entity_id, graph_qualified_name, project, confidence, label, "
                "file_path, created_at) "
                "SELECT ?, graph_qualified_name, project, confidence, label, "
                "file_path, created_at FROM entity_code_links WHERE entity_id = ?",
                (winner_id, loser_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO relationships "
                "(source_id, target_id, predicate, memory_id, project, platform, created_at) "
                "SELECT CASE WHEN source_id = ? THEN ? ELSE source_id END, "
                "CASE WHEN target_id = ? THEN ? ELSE target_id END, predicate, "
                "memory_id, project, platform, created_at FROM relationships "
                "WHERE (source_id = ? OR target_id = ?) "
                "AND CASE WHEN source_id = ? THEN ? ELSE source_id END != "
                "CASE WHEN target_id = ? THEN ? ELSE target_id END",
                (
                    loser_id,
                    winner_id,
                    loser_id,
                    winner_id,
                    loser_id,
                    loser_id,
                    loser_id,
                    winner_id,
                    loser_id,
                    winner_id,
                ),
            )
            conn.execute(
                "DELETE FROM relationships WHERE source_id = ? OR target_id = ?",
                (loser_id, loser_id),
            )
            conn.execute(
                "DELETE FROM entity_code_links WHERE entity_id = ?", (loser_id,)
            )

            scope = (winner[3], winner[4], winner[5])
            conn.execute(
                "UPDATE concept_entity_aliases SET canonical_name = ? "
                "WHERE canonical_name = ? AND session_name IS ? AND project IS ? "
                "AND platform IS ?",
                (winner[1], loser[1], *scope),
            )
            conn.execute(
                "INSERT INTO concept_entity_aliases "
                "(alias_name, canonical_name, session_name, project, platform) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT DO UPDATE SET canonical_name = excluded.canonical_name",
                (loser[1], winner[1], *scope),
            )
            conn.execute(
                "DELETE FROM concept_duplicate_dismissals "
                "WHERE (name_a = ? OR name_b = ?) AND session_name IS ? "
                "AND project IS ? AND platform IS ?",
                (loser[1], loser[1], *scope),
            )
            conn.execute("DELETE FROM entities WHERE id = ?", (loser_id,))

        return {
            "status": "merged",
            "kept_entity_id": winner_id,
            "removed_entity_id": loser_id,
            "canonical_name": winner[1],
        }
    finally:
        database.close()


def remove_entity(db_path: str, entity_id: int) -> dict:
    database = ConceptDB(db_path)
    try:
        with database.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            entity = _entity(conn, entity_id)
            if entity is None:
                raise ConceptReviewError("This concept no longer exists.")
            scope = (entity[3], entity[4], entity[5])
            conn.execute(
                "INSERT OR IGNORE INTO concept_entity_suppressions "
                "(name, session_name, project, platform) VALUES (?, ?, ?, ?)",
                (entity[1], *scope),
            )
            conn.execute(
                "DELETE FROM relationships WHERE source_id = ? OR target_id = ?",
                (entity_id, entity_id),
            )
            conn.execute(
                "DELETE FROM entity_code_links WHERE entity_id = ?", (entity_id,)
            )
            conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        return {"status": "removed", "removed_entity_id": entity_id}
    finally:
        database.close()
