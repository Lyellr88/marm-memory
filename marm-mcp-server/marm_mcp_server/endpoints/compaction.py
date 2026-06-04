"""Compaction MCP endpoint tools — V2 agent-driven summarization, V3 staged apply, V4 write-queue + auto-apply."""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from ..core.compaction import COMPACTION_PROMPT_TEMPLATE
from ..core.consolidation import compute_content_hash
from ..core.memory import memory, sanitize_content
from ..core.models import (
    ApplyCompactionRequest,
    CompactionRequest,
    StageCompactionSummariesRequest,
)

router = APIRouter(prefix="", tags=["Compaction"])


@router.get(
    "/marm_get_compaction_candidates",
    operation_id="marm_get_compaction_candidates",
    include_in_schema=False,
)
async def marm_get_compaction_candidates():
    """
    Return pending_summary compaction candidates with an embedded prompt template.

    Poll this tool to discover memory clusters awaiting agent summarization.
    Each candidate includes its source memory previews and a ready-to-use prompt.
    Returns empty list when no candidates exist — safe to poll at any cadence.
    """
    now = datetime.now(timezone.utc).isoformat()
    with memory.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, session_name, source_memory_ids, preview, created_at, expires_at
            FROM compaction_staging
            WHERE status = 'pending_summary'
              AND expires_at > ?
            ORDER BY created_at ASC
            """,
            (now,),
        ).fetchall()

    if not rows:
        return {"candidates": [], "prompt_template": None}

    candidates = []
    for (
        row_id,
        session_name,
        source_ids_json,
        preview_json,
        created_at,
        expires_at,
    ) in rows:
        source_ids = json.loads(source_ids_json)
        preview = json.loads(preview_json)
        memories_block = "\n".join(f"- {p}" for p in preview)
        prompt = COMPACTION_PROMPT_TEMPLATE.format(memories=memories_block)
        candidates.append(
            {
                "candidate_id": row_id,
                "session_name": session_name,
                "source_memory_ids": source_ids,
                "preview": preview,
                "created_at": created_at,
                "expires_at": expires_at,
                "prompt": prompt,
            }
        )

    return {"candidates": candidates, "prompt_template": COMPACTION_PROMPT_TEMPLATE}


@router.post(
    "/marm_stage_compaction_summaries",
    operation_id="marm_stage_compaction_summaries",
    include_in_schema=False,
)
async def marm_stage_compaction_summaries(request: StageCompactionSummariesRequest):
    """
    Submit agent-generated summaries for pending compaction candidates.

    Advances each candidate from pending_summary → summary_staged.
    Validates: candidate exists, status is pending_summary, summary is non-empty,
    source IDs match, source rows exist in the same session and are not already compacted,
    candidate is not past expires_at.
    """
    now = datetime.now(timezone.utc).isoformat()
    results = []

    # Validate empty summaries up front — no DB work needed
    items_to_process = []
    for item in request.summaries:
        suggested_summary = (
            item.suggested_summary.strip() if item.suggested_summary else ""
        )
        if not suggested_summary:
            results.append(
                {
                    "candidate_id": item.candidate_id,
                    "status": "error",
                    "reason": "summary is empty",
                }
            )
        else:
            items_to_process.append(
                (item.candidate_id, item.source_memory_ids, suggested_summary)
            )

    if not items_to_process:
        return {"results": results}

    # Process all valid items in a single connection
    with memory.get_connection() as conn:
        for candidate_id, source_ids_submitted, suggested_summary in items_to_process:
            row = conn.execute(
                "SELECT id, session_name, source_memory_ids, status, expires_at "
                "FROM compaction_staging WHERE id = ?",
                (candidate_id,),
            ).fetchone()

            if not row:
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "status": "error",
                        "reason": "candidate not found",
                    }
                )
                continue

            _, session_name, source_ids_json, status, expires_at = row

            if status != "pending_summary":
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "status": "error",
                        "reason": f"candidate status is '{status}', expected 'pending_summary'",
                    }
                )
                continue

            if expires_at and now > expires_at:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                    (now, candidate_id),
                )
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "status": "error",
                        "reason": "candidate has expired",
                    }
                )
                continue

            staged_source_ids = json.loads(source_ids_json)

            if source_ids_submitted is not None and sorted(source_ids_submitted) != sorted(staged_source_ids):
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "status": "error",
                        "reason": "source_memory_ids do not match staged candidate",
                    }
                )
                continue

            placeholders = ",".join("?" * len(staged_source_ids))
            current_rows = conn.execute(
                f"SELECT id, session_name, compaction_role FROM memories "
                f"WHERE id IN ({placeholders})",
                staged_source_ids,
            ).fetchall()

            found_ids = {r[0] for r in current_rows}
            missing = set(staged_source_ids) - found_ids
            if missing:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                    (now, candidate_id),
                )
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "status": "error",
                        "reason": f"source memories not found: {sorted(missing)}",
                    }
                )
                continue

            wrong_session = [r[0] for r in current_rows if r[1] != session_name]
            if wrong_session:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                    (now, candidate_id),
                )
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "status": "error",
                        "reason": "some source memories belong to a different session",
                    }
                )
                continue

            already_compacted = [
                r[0] for r in current_rows if r[2] in ("source", "summary")
            ]
            if already_compacted:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                    (now, candidate_id),
                )
                results.append(
                    {
                        "candidate_id": candidate_id,
                        "status": "error",
                        "reason": f"source memories already compacted: {already_compacted}",
                    }
                )
                continue

            conn.execute(
                "UPDATE compaction_staging "
                "SET suggested_summary = ?, status = 'summary_staged', updated_at = ? "
                "WHERE id = ?",
                (suggested_summary, now, candidate_id),
            )
            results.append({"candidate_id": candidate_id, "status": "summary_staged"})

    return {"results": results}


@router.get(
    "/marm_get_staged_summaries",
    operation_id="marm_get_staged_summaries",
    include_in_schema=False,
)
async def marm_get_staged_summaries(limit: int = 20):
    """
    Return all summary_staged compaction proposals awaiting main agent review.

    Returns empty list when nothing is staged. Call marm_apply_compaction with
    action='apply' or action='discard' to act on each proposal.
    """
    limit = max(1, min(limit, 100))
    now = datetime.now(timezone.utc).isoformat()
    with memory.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, session_name, source_memory_ids, preview, suggested_summary,
                   created_at, expires_at
            FROM compaction_staging
            WHERE status = 'summary_staged'
              AND expires_at > ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()

    proposals = []
    for (
        row_id,
        session_name,
        source_ids_json,
        preview_json,
        suggested_summary,
        created_at,
        expires_at,
    ) in rows:
        proposals.append(
            {
                "candidate_id": row_id,
                "session_name": session_name,
                "source_memory_ids": json.loads(source_ids_json),
                "preview": json.loads(preview_json),
                "suggested_summary": suggested_summary,
                "created_at": created_at,
                "expires_at": expires_at,
            }
        )

    return {"proposals": proposals, "limit": limit}


async def _apply_compaction_write(candidate_id: str) -> str:
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
        with memory.get_connection() as conn:
            row = conn.execute(
                "SELECT suggested_summary FROM compaction_staging WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        if row and row[0]:
            precomputed_summary = sanitize_content(row[0])
            precomputed_summary_hash = compute_content_hash(precomputed_summary)
            if memory._load_encoder_lazily():
                summary_vec = await asyncio.to_thread(
                    memory._encode_sync, precomputed_summary
                )
                precomputed_summary_embedding = summary_vec.tobytes()
    except Exception:
        precomputed_summary_hash = None
        precomputed_summary_embedding = None

    with memory.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _committed = False
        now = datetime.now(timezone.utc).isoformat()
        try:
            # Fetch candidate fresh — guards against discard/expire/delete racing
            # with a queued apply between outer validation and here.
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

            # Idempotent: already applied — release lock and return existing summary_id
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

            # Deliberately discarded by human review — don't overwrite status, just skip
            if status == "discarded":
                conn.execute("ROLLBACK")
                _committed = True
                raise RuntimeError(
                    f"compaction candidate {candidate_id} was discarded"
                )

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

            already_compacted = [r[0] for r in current_rows if r[3] in ("source", "summary")]
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

            # All validations pass — sanitize, then compute embedding and write
            suggested_summary = sanitize_content(suggested_summary)
            summary_content_hash = compute_content_hash(suggested_summary)
            summary_embedding = (
                precomputed_summary_embedding
                if precomputed_summary_hash == summary_content_hash
                else None
            )

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


@router.post(
    "/marm_apply_compaction",
    operation_id="marm_apply_compaction",
    include_in_schema=False,
)
async def marm_apply_compaction(request: ApplyCompactionRequest):
    """
    Apply or discard a staged compaction proposal.

    action='apply': inserts a summary memory row, marks source rows as compacted,
    and updates staging status to 'applied'. Idempotent — second call on an
    already-applied candidate returns success without re-writing. Write is routed
    through the write queue when available (V4), or executed directly with
    BEGIN IMMEDIATE when the queue is disabled.

    action='discard': marks staging status to 'discarded'. No write to memories.

    Validations on apply: candidate exists and is summary_staged, source rows exist
    and are not already compacted, source_updated_at_snapshot matches current
    content_hash values, candidate is not past expires_at.
    """
    candidate_id = request.candidate_id
    action = request.action
    now = datetime.now(timezone.utc).isoformat()

    with memory.get_connection() as conn:
        row = conn.execute(
            "SELECT id, session_name, source_memory_ids, suggested_summary, "
            "status, source_updated_at_snapshot, expires_at "
            "FROM compaction_staging WHERE id = ?",
            (candidate_id,),
        ).fetchone()

        if not row:
            return {
                "candidate_id": candidate_id,
                "status": "error",
                "reason": "candidate not found",
            }

        (
            _,
            session_name,
            source_ids_json,
            suggested_summary,
            status,
            snapshot_json,
            expires_at,
        ) = row

        # Idempotent: already applied
        if status == "applied" and action == "apply":
            source_ids = json.loads(source_ids_json)
            summary_row = None
            if source_ids:
                summary_row = conn.execute(
                    "SELECT compacted_into FROM memories "
                    "WHERE id = ? AND compacted_into IS NOT NULL",
                    (source_ids[0],),
                ).fetchone()
            return {
                "candidate_id": candidate_id,
                "status": "applied",
                "summary_memory_id": summary_row[0] if summary_row else None,
            }

        if status != "summary_staged":
            return {
                "candidate_id": candidate_id,
                "status": "error",
                "reason": f"candidate status is '{status}', expected 'summary_staged'",
            }

        if action == "discard":
            conn.execute(
                "UPDATE compaction_staging "
                "SET status = 'discarded', reviewed_at = ?, updated_at = ? "
                "WHERE id = ?",
                (now, now, candidate_id),
            )
            return {"candidate_id": candidate_id, "status": "discarded"}

        # action == "apply" — validate before writing
        if expires_at and now > expires_at:
            conn.execute(
                "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                (now, candidate_id),
            )
            return {
                "candidate_id": candidate_id,
                "status": "error",
                "reason": "candidate has expired",
            }

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
                "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                (now, candidate_id),
            )
            return {
                "candidate_id": candidate_id,
                "status": "error",
                "reason": f"source memories not found: {sorted(missing)}",
            }

        wrong_session = [r[0] for r in current_rows if r[1] != session_name]
        if wrong_session:
            conn.execute(
                "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                (now, candidate_id),
            )
            return {
                "candidate_id": candidate_id,
                "status": "error",
                "reason": "some source memories belong to a different session",
            }

        already_compacted = [
            r[0] for r in current_rows if r[3] in ("source", "summary")
        ]
        if already_compacted:
            conn.execute(
                "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                (now, candidate_id),
            )
            return {
                "candidate_id": candidate_id,
                "status": "error",
                "reason": f"source memories already compacted: {already_compacted}",
            }

        for mem_id, _, content_hash, _, _ in current_rows:
            if snapshot.get(mem_id) != content_hash:
                conn.execute(
                    "UPDATE compaction_staging SET status = 'stale', updated_at = ? WHERE id = ?",
                    (now, candidate_id),
                )
                return {
                    "candidate_id": candidate_id,
                    "status": "error",
                    "reason": "source memory content changed since candidate was detected",
                }

        if not suggested_summary or not suggested_summary.strip():
            return {
                "candidate_id": candidate_id,
                "status": "error",
                "reason": "staged summary is empty — candidate may be corrupted",
            }

    # All validations pass — route write through queue if available, else direct
    if memory._write_queue is not None:
        summary_id = await memory._write_queue.put_callable(
            _apply_compaction_write,
            candidate_id,
        )
    else:
        summary_id = await _apply_compaction_write(candidate_id)

    return {
        "candidate_id": candidate_id,
        "status": "applied",
        "summary_memory_id": summary_id,
    }


def _compaction_status() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with memory.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                CASE
                    WHEN status IN ('pending_summary', 'summary_staged')
                         AND expires_at IS NOT NULL
                         AND expires_at <= ?
                    THEN 'stale'
                    ELSE status
                END,
                COUNT(*)
            FROM compaction_staging
            GROUP BY 1
            """,
            (now,),
        ).fetchall()
        staged_rows = conn.execute(
            """
            SELECT id
            FROM compaction_staging
            WHERE status = 'summary_staged'
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at ASC
            """,
            (now,),
        ).fetchall()

    counts = {status: count for status, count in rows}
    return {
        "status": "ok",
        "counts": {
            "pending_summary": counts.get("pending_summary", 0),
            "summary_staged": counts.get("summary_staged", 0),
            "applied": counts.get("applied", 0),
            "discarded": counts.get("discarded", 0),
            "stale": counts.get("stale", 0),
            "nudge_exhausted": counts.get("nudge_exhausted", 0),
        },
        "staged_candidate_ids": [row[0] for row in staged_rows],
    }


@router.post("/marm_compaction", operation_id="marm_compaction")
async def marm_compaction(request: CompactionRequest):
    """Compact related memories into a single summary to reduce context bloat.

    Workflow: status/candidates → stage → review → apply/discard

    action="status"     — check if compaction candidates exist (run first)
    action="candidates" — get pending candidates with source previews; each includes a ready-to-use prompt
    action="stage"      — submit your summary: {candidate_id, suggested_summary}; source_memory_ids optional
    action="review"     — inspect staged summaries before committing
    action="apply"      — commit a staged summary; source memories are marked compacted
    action="discard"    — reject a staged summary without touching source memories
    """
    if request.action == "status":
        return _compaction_status()

    if request.action == "candidates":
        return await marm_get_compaction_candidates()

    if request.action == "review":
        return await marm_get_staged_summaries(limit=request.limit)

    if request.action == "stage":
        if request.summaries is None:
            return {
                "status": "error",
                "message": "summaries is required for action='stage'",
            }
        return await marm_stage_compaction_summaries(
            StageCompactionSummariesRequest(summaries=request.summaries)
        )

    if request.action in ("apply", "discard"):
        if not request.candidate_id:
            return {
                "status": "error",
                "message": f"candidate_id is required for action='{request.action}'",
            }
        return await marm_apply_compaction(
            ApplyCompactionRequest(
                candidate_id=request.candidate_id,
                action=request.action,
            )
        )

    return {"status": "error", "message": f"unknown action: {request.action}"}


async def auto_apply_staged_summaries() -> dict:
    """V4 scheduled job: auto-apply all summary_staged compaction candidates.

    Reuses marm_apply_compaction so all validation and write-queue routing applies.
    Expired candidates are passed through so marm_apply_compaction can mark them
    stale and report them in skipped rather than silently ignoring them.
    """
    with memory.get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM compaction_staging WHERE status = 'summary_staged'",
        ).fetchall()

    applied = []
    skipped = []
    for (candidate_id,) in rows:
        try:
            result = await marm_apply_compaction(
                ApplyCompactionRequest(candidate_id=candidate_id, action="apply")
            )
        except Exception as exc:
            skipped.append({"candidate_id": candidate_id, "reason": str(exc)})
            continue
        if result.get("status") == "applied":
            applied.append(candidate_id)
        else:
            skipped.append(
                {
                    "candidate_id": candidate_id,
                    "reason": result.get("reason", "unknown"),
                }
            )

    return {"applied": applied, "skipped": skipped}
