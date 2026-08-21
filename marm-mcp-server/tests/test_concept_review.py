import json
import sqlite3
import threading

import pytest

from marm_mcp_server.core import concept_review
from marm_mcp_server.core.concept_db import (
    ConceptDB,
    backup_and_reset_concept_database,
)


def _seed_pair(db_path: str) -> tuple[int, int, int]:
    database = ConceptDB(db_path)
    with database.get_connection() as conn:
        winner, _ = database.get_or_create_entity(
            conn, "MARM", "product", "session", "project", "memory-a"
        )
        loser, _ = database.get_or_create_entity(
            conn, "MARM Memory", "product", "session", "project", "memory-b"
        )
        neighbor, _ = database.get_or_create_entity(
            conn, "recall", "concept", "session", "project", "memory-c"
        )
        database.store_relationship(
            conn, loser, neighbor, "uses", "memory-b", "project"
        )
        database.store_code_link(conn, loser, "pkg.memory", "project")
    database.close()
    return winner, loser, neighbor


def test_merge_rewires_graph_and_survives_rebuild_as_alias(tmp_path):
    db_path = str(tmp_path / "concept.db")
    winner, loser, neighbor = _seed_pair(db_path)

    result = concept_review.merge_entities(db_path, winner, loser, "a")

    assert result["canonical_name"] == "MARM"
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT 1 FROM entities WHERE id = ?", (loser,)).fetchone()
            is None
        )
        sources = json.loads(
            conn.execute(
                "SELECT source_memory_ids FROM entities WHERE id = ?", (winner,)
            ).fetchone()[0]
        )
        assert sources == ["memory-a", "memory-b"]
        assert conn.execute(
            "SELECT 1 FROM relationships WHERE source_id = ? AND target_id = ?",
            (winner, neighbor),
        ).fetchone()
        assert conn.execute(
            "SELECT 1 FROM entity_code_links WHERE entity_id = ?", (winner,)
        ).fetchone()

    backup_and_reset_concept_database(db_path)
    database = ConceptDB(db_path)
    with database.get_connection() as conn:
        assert (
            database.resolve_entity_name(
                conn, "MARM Memory", "session", "project", None
            )
            == "MARM"
        )
    database.close()


def test_remove_suppresses_entity_across_rebuild(tmp_path):
    db_path = str(tmp_path / "concept.db")
    winner, _, _ = _seed_pair(db_path)

    concept_review.remove_entity(db_path, winner)
    backup_and_reset_concept_database(db_path)

    database = ConceptDB(db_path)
    with database.get_connection() as conn:
        assert (
            database.resolve_entity_name(conn, "MARM", "session", "project", None)
            is None
        )
    database.close()


def test_remove_rolls_back_when_lease_is_lost_before_entity_deletion(tmp_path):
    db_path = str(tmp_path / "concept.db")
    winner, _, _ = _seed_pair(db_path)

    class LeaseLostAtFinalBoundary(threading.Event):
        def __init__(self) -> None:
            super().__init__()
            self.checks = 0

        def is_set(self) -> bool:
            self.checks += 1
            return self.checks == 5

    with pytest.raises(concept_review.ConceptReviewLeaseLost):
        concept_review.remove_entity(
            db_path, winner, lease_lost=LeaseLostAtFinalBoundary()
        )

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT 1 FROM entities WHERE id = ?", (winner,)).fetchone()
        assert (
            conn.execute("SELECT 1 FROM concept_entity_suppressions").fetchone() is None
        )


def test_dismissal_is_idempotent_and_survives_rebuild(tmp_path):
    db_path = str(tmp_path / "concept.db")
    winner, loser, _ = _seed_pair(db_path)

    concept_review.dismiss_duplicate(db_path, winner, loser)
    concept_review.dismiss_duplicate(db_path, winner, loser)
    backup_and_reset_concept_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name_a, name_b FROM concept_duplicate_dismissals"
        ).fetchall()
    assert rows == [("MARM", "MARM Memory")]
