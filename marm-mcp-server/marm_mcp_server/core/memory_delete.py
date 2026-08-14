"""Memory deletion and compaction-lineage cleanup for the MARM memory system."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .concept_queue import dequeue as dequeue_concept_index

if TYPE_CHECKING:
    from .memory import MARMMemory


async def _delete_memory(mem: "MARMMemory", memory_id: str) -> bool:
    result = await _delete_memories(mem, [memory_id])
    return bool(result["deleted_ids"])


def _delete_impact(conn: sqlite3.Connection, memory_id: str) -> dict:
    row = conn.execute(
        "SELECT id, compaction_role, compacted_into, metadata FROM memories WHERE id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        return {"memory_id": memory_id, "exists": False}

    metadata = json.loads(row[3]) if row[3] else {}
    staging_rows = conn.execute(
        """
        SELECT id, status FROM compaction_staging
        WHERE EXISTS (
            SELECT 1 FROM json_each(compaction_staging.source_memory_ids)
            WHERE value = ?
        )
        """,
        (memory_id,),
    ).fetchall()
    return {
        "memory_id": row[0],
        "exists": True,
        "compaction_role": row[1] or "none",
        "compacted_into": row[2],
        "summary_source_ids": metadata.get("source_memory_ids", []),
        "staging_candidates": [
            {"id": candidate_id, "status": status}
            for candidate_id, status in staging_rows
        ],
    }


def _remove_deleted_sources_from_summary(
    conn: sqlite3.Connection, summary_id: str, deleted_source_ids: set[str], now: str
) -> int:
    row = conn.execute(
        "SELECT metadata FROM memories WHERE id = ? AND compaction_role = 'summary'",
        (summary_id,),
    ).fetchone()
    if row is None:
        return 0
    metadata = json.loads(row[0]) if row[0] else {}
    source_ids = [str(item) for item in metadata.get("source_memory_ids", [])]
    remaining = [item for item in source_ids if item not in deleted_source_ids]
    if remaining == source_ids:
        return 0
    deleted_seen = {str(item) for item in metadata.get("deleted_source_memory_ids", [])}
    deleted_seen.update(item for item in source_ids if item in deleted_source_ids)
    metadata["source_memory_ids"] = remaining
    metadata["source_count"] = len(remaining)
    metadata["deleted_source_memory_ids"] = sorted(deleted_seen)
    metadata["updated_at"] = now
    conn.execute(
        "UPDATE memories SET metadata = ? WHERE id = ?",
        (json.dumps(metadata), summary_id),
    )
    return 1


def _restore_sources_from_deleted_summary(
    conn: sqlite3.Connection, summary_id: str, deleted_ids: set[str], now: str
) -> int:
    rows = conn.execute(
        "SELECT id, metadata FROM memories WHERE compacted_into = ?",
        (summary_id,),
    ).fetchall()
    restored = 0
    for source_id, metadata_json in rows:
        if source_id in deleted_ids:
            continue
        metadata = json.loads(metadata_json) if metadata_json else {}
        metadata.pop("compaction_role", None)
        metadata.pop("compacted_into", None)
        metadata["restored_from_deleted_summary"] = summary_id
        metadata["restored_at"] = now
        conn.execute(
            "UPDATE memories SET compaction_role = NULL, compacted_into = NULL, metadata = ? WHERE id = ?",
            (json.dumps(metadata), source_id),
        )
        restored += 1
    return restored


async def _delete_memories(mem: "MARMMemory", memory_ids: list[str]) -> dict:
    unique_ids = list(dict.fromkeys(str(memory_id) for memory_id in memory_ids))
    if not unique_ids:
        return {
            "deleted_ids": [],
            "missing_ids": [],
            "impacts": [],
            "compaction_updates": {
                "staging_candidates_marked_stale": 0,
                "summaries_updated": 0,
                "sources_restored": 0,
            },
        }

    now = datetime.now(timezone.utc).isoformat()
    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        impacts = [_delete_impact(conn, memory_id) for memory_id in unique_ids]
        existing_ids = {
            str(item["memory_id"]) for item in impacts if item.get("exists")
        }
        missing_ids = [
            memory_id for memory_id in unique_ids if memory_id not in existing_ids
        ]
        if not existing_ids:
            return {
                "deleted_ids": [],
                "missing_ids": missing_ids,
                "impacts": impacts,
                "compaction_updates": {
                    "staging_candidates_marked_stale": 0,
                    "summaries_updated": 0,
                    "sources_restored": 0,
                },
            }

        source_summary_ids = {
            compacted_into
            for item in impacts
            if item.get("exists")
            and item.get("compaction_role") == "source"
            and (compacted_into := item.get("compacted_into"))
            and compacted_into not in existing_ids
        }
        summaries_updated = sum(
            _remove_deleted_sources_from_summary(conn, summary_id, existing_ids, now)
            for summary_id in source_summary_ids
        )

        deleted_summary_ids = [
            item["memory_id"]
            for item in impacts
            if item.get("exists") and item.get("compaction_role") == "summary"
        ]
        sources_restored = sum(
            _restore_sources_from_deleted_summary(conn, summary_id, existing_ids, now)
            for summary_id in deleted_summary_ids
        )

        placeholders = ",".join("?" for _ in existing_ids)
        stale_cursor = conn.execute(
            f"""
            UPDATE compaction_staging
            SET status = 'stale', updated_at = ?
            WHERE status != 'applied'
              AND EXISTS (
                  SELECT 1 FROM json_each(compaction_staging.source_memory_ids)
                  WHERE value IN ({placeholders})
              )
            """,
            [now, *existing_ids],
        )
        for memory_id in existing_ids:
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))
        # Same transaction as the delete. A task left behind points at a
        # memory that no longer exists, and the worker would keep claiming it
        # until it burned the attempt budget and parked it.
        dequeue_concept_index(conn, existing_ids)
        delete_cursor = conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            list(existing_ids),
        )

    return {
        "deleted_ids": sorted(existing_ids),
        "missing_ids": missing_ids,
        "impacts": impacts,
        "compaction_updates": {
            "staging_candidates_marked_stale": stale_cursor.rowcount,
            "summaries_updated": summaries_updated,
            "sources_restored": sources_restored,
        },
        "deleted_count": delete_cursor.rowcount,
    }
