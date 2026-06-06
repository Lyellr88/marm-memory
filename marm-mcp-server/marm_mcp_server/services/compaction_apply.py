"""Apply staged compaction summaries inside an atomic DB transaction."""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from ..core.consolidation import compute_content_hash
from ..core.memory import sanitize_content


async def apply_compaction_write(memory_store, candidate_id: str) -> str:
    """Execute the atomic compaction write inside BEGIN IMMEDIATE. Returns summary_id.

    Fetches all candidate and source data fresh inside the lock so this function
    is safe to call via the write queue after an arbitrary delay. Computes fresh
    timestamps inside the lock to avoid TOCTOU on expiry checks. Marks the
    candidate stale on any validation failure so it is not retried by the scheduler.
    Uses _committed to prevent the except-block ROLLBACK from firing after an
    explicit COMMIT or ROLLBACK in a validation branch.
    """
    precomputed_summary_hash = None
    precomputed_summary_embedding = None
    try:
        with memory_store.get_connection() as conn:
            row = conn.execute(
                "SELECT suggested_summary FROM compaction_staging WHERE id = ?",
                (candidate_id,),
            ).fetchone()
    except Exception:
        row = None

    if row and row[0]:
        precomputed_summary = sanitize_content(row[0])
        precomputed_summary_hash = compute_content_hash(precomputed_summary)
        if memory_store._load_encoder_lazily():
            summary_vec = await asyncio.to_thread(
                memory_store._encode_sync, precomputed_summary
            )
            precomputed_summary_embedding = summary_vec.tobytes()

    with memory_store.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _committed = False
        now = datetime.now(timezone.utc).isoformat()
        try:
            row = conn.execute(
                "SELECT session_name, source_memory_ids, suggested_summary, status, "
                "source_updated_at_snapshot, expires_at "
                "FROM compaction_staging WHERE id = ?",
                (candidate_id,),
            ).fetchone()

            if not row:
                raise RuntimeError(
                    f"compaction candidate {candidate_id} no longer exists"
                )

            (
                session_name,
                source_ids_json,
                suggested_summary,
                status,
                snapshot_json,
                expires_at,
            ) = row

            if status == "applied":
                conn.execute("ROLLBACK")
                _committed = True
                source_ids = json.loads(source_ids_json)
                idempotent_row = conn.execute(
                    "SELECT compacted_into FROM memories "
                    "WHERE id = ? AND compacted_into IS NOT NULL",
                    (source_ids[0],),
                ).fetchone()
                return idempotent_row[0] if idempotent_row else candidate_id

            if status == "discarded":
                conn.execute("ROLLBACK")
                _committed = True
                raise RuntimeError(f"compaction candidate {candidate_id} was discarded")

            if status != "summary_staged":
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? "
                    "WHERE id = ?",
                    (now, candidate_id),
                )
                conn.execute("COMMIT")
                _committed = True
                raise RuntimeError(
                    f"compaction candidate became '{status}' before write could execute"
                )

            if expires_at and now > expires_at:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? "
                    "WHERE id = ?",
                    (now, candidate_id),
                )
                conn.execute("COMMIT")
                _committed = True
                raise RuntimeError(
                    f"compaction candidate {candidate_id} expired before write could execute"
                )

            if not suggested_summary or not suggested_summary.strip():
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? "
                    "WHERE id = ?",
                    (now, candidate_id),
                )
                conn.execute("COMMIT")
                _committed = True
                raise RuntimeError(
                    f"compaction candidate {candidate_id} has empty summary"
                )

            source_ids = json.loads(source_ids_json)
            snapshot = json.loads(snapshot_json)
            placeholders = ",".join("?" * len(source_ids))
            current_rows = conn.execute(
                f"SELECT id, session_name, content_hash, compaction_role, metadata "
                f"FROM memories WHERE id IN ({placeholders})",
                source_ids,
            ).fetchall()

            found_ids = {r[0] for r in current_rows}
            missing = set(source_ids) - found_ids
            if missing:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? "
                    "WHERE id = ?",
                    (now, candidate_id),
                )
                conn.execute("COMMIT")
                _committed = True
                raise RuntimeError(f"source memories not found: {sorted(missing)}")

            wrong_session = [r[0] for r in current_rows if r[1] != session_name]
            if wrong_session:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? "
                    "WHERE id = ?",
                    (now, candidate_id),
                )
                conn.execute("COMMIT")
                _committed = True
                raise RuntimeError(
                    f"source memories belong to different session: {wrong_session}"
                )

            already_compacted = [
                r[0] for r in current_rows if r[3] in ("source", "summary")
            ]
            if already_compacted:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? "
                    "WHERE id = ?",
                    (now, candidate_id),
                )
                conn.execute("COMMIT")
                _committed = True
                raise RuntimeError(
                    f"source memories already compacted: {already_compacted}"
                )

            for mem_id, _, content_hash, _, _ in current_rows:
                if snapshot.get(mem_id) != content_hash:
                    conn.execute(
                        "UPDATE compaction_staging SET status = 'stale', updated_at = ? "
                        "WHERE id = ?",
                        (now, candidate_id),
                    )
                    conn.execute("COMMIT")
                    _committed = True
                    raise RuntimeError(
                        f"source memory {mem_id} content changed since candidate was detected"
                    )

            suggested_summary = sanitize_content(suggested_summary)
            summary_content_hash = compute_content_hash(suggested_summary)
            summary_embedding = (
                precomputed_summary_embedding
                if precomputed_summary_hash == summary_content_hash
                else None
            )
            if summary_embedding is None and memory_store._load_encoder_lazily():
                summary_embedding = memory_store._encode_sync(
                    suggested_summary
                ).tobytes()

            summary_id = str(uuid.uuid4())
            compacted_at = now
            summary_metadata = {
                "compaction_role": "summary",
                "source_memory_ids": source_ids,
                "source_count": len(source_ids),
                "compacted_at": compacted_at,
                "strategy": "semantic_cluster_summary",
            }

            conn.execute(
                """
                INSERT INTO memories
                    (id, session_name, content, embedding, content_hash, timestamp,
                     context_type, metadata, compaction_role)
                VALUES (?, ?, ?, ?, ?, ?, 'general', ?, 'summary')
                """,
                (
                    summary_id,
                    session_name,
                    suggested_summary,
                    summary_embedding,
                    summary_content_hash,
                    compacted_at,
                    json.dumps(summary_metadata),
                ),
            )

            for mem_id, _, _, _, metadata_json in current_rows:
                existing_meta = json.loads(metadata_json) if metadata_json else {}
                existing_meta.update(
                    {
                        "compaction_role": "source",
                        "compacted_into": summary_id,
                        "compacted_at": compacted_at,
                    }
                )
                conn.execute(
                    "UPDATE memories "
                    "SET compaction_role = 'source', compacted_into = ?, metadata = ? "
                    "WHERE id = ?",
                    (summary_id, json.dumps(existing_meta), mem_id),
                )

            conn.execute(
                "UPDATE compaction_staging "
                "SET status = 'applied', reviewed_at = ?, updated_at = ? "
                "WHERE id = ?",
                (now, now, candidate_id),
            )
            conn.execute("COMMIT")
            _committed = True
        except Exception:
            if not _committed:
                conn.execute("ROLLBACK")
            raise

    return summary_id
