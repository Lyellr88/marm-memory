"""Tests for compaction Layer 3 — V2 staging and V3 apply."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import numpy as np
import pytest

from marm_mcp_server.core.compaction import (
    _compute_candidate_hash,
    _build_compaction_prompt_block,
    claim_pending_compaction_prompt,
    mark_stale_candidates,
    persist_candidates_to_staging,
)
from marm_mcp_server.core.memory import MARMMemory


# --- helpers ---

def _make_similar_embeddings(count: int = 3, base_axis: int = 0, dim: int = 384) -> list:
    rng = np.random.default_rng(seed=42)
    base = np.zeros(dim, dtype=np.float32)
    base[base_axis] = 1.0
    results = []
    for _ in range(count):
        noise = rng.standard_normal(dim).astype(np.float32) * 0.005
        v = base + noise
        v = v / np.linalg.norm(v)
        results.append(v.tobytes())
    return results


def _insert_memory_row(
    mem: MARMMemory,
    session: str,
    content: str,
    embedding: bytes,
    age_hours: float = 48.0,
    compaction_role: str | None = None,
    content_hash: str | None = None,
) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    mem_id = str(uuid.uuid4())
    ch = content_hash or f"hash-{mem_id}"
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories "
            "(id, session_name, content, embedding, timestamp, context_type, metadata, content_hash, compaction_role) "
            "VALUES (?, ?, ?, ?, ?, 'general', '{}', ?, ?)",
            (mem_id, session, content, embedding, ts, ch, compaction_role),
        )
    return mem_id


def _insert_staging_row(
    mem: MARMMemory,
    session: str,
    source_ids: list,
    status: str = "pending_summary",
    expires_hours: float = 168.0,
    snapshot: dict | None = None,
    suggested_summary: str | None = None,
) -> str:
    row_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=expires_hours)).isoformat()
    snap = snapshot or {sid: f"hash-{sid}" for sid in source_ids}
    with mem.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO compaction_staging
                (id, session_name, source_memory_ids, preview, suggested_summary,
                 status, candidate_hash, source_updated_at_snapshot,
                 expires_at, created_at, updated_at, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                row_id,
                session,
                json.dumps(source_ids),
                json.dumps([f"preview of {sid}" for sid in source_ids]),
                suggested_summary,
                status,
                _compute_candidate_hash(source_ids),
                json.dumps(snap),
                expires_at,
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return row_id


def _get_staging_row(mem: MARMMemory, row_id: str) -> dict | None:
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT id, status, suggested_summary, reviewed_at FROM compaction_staging WHERE id = ?",
            (row_id,),
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "status": row[1], "suggested_summary": row[2], "reviewed_at": row[3]}


# --- _compute_candidate_hash ---

def test_candidate_hash_is_order_independent():
    ids = ["a", "b", "c"]
    assert _compute_candidate_hash(ids) == _compute_candidate_hash(["c", "a", "b"])


def test_candidate_hash_differs_for_different_ids():
    assert _compute_candidate_hash(["a", "b"]) != _compute_candidate_hash(["a", "c"])


# --- persist_candidates_to_staging ---

def test_persist_inserts_new_candidates(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]

    candidates = [{
        "session_name": "sess",
        "source_memory_ids": ids,
        "preview": ["c0", "c1", "c2"],
    }]
    persist_candidates_to_staging(mem, candidates)

    with mem.get_connection() as conn:
        rows = conn.execute("SELECT status FROM compaction_staging WHERE session_name = 'sess'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "pending_summary"


def test_persist_skips_duplicate_hash_when_pending(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]

    candidates = [{"session_name": "sess", "source_memory_ids": ids, "preview": ["c0", "c1", "c2"]}]

    persist_candidates_to_staging(mem, candidates)
    persist_candidates_to_staging(mem, candidates)  # second call = no-op

    with mem.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM compaction_staging").fetchone()[0]
    assert count == 1


def test_persist_skips_duplicate_hash_when_summary_staged(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]

    _insert_staging_row(mem, "sess", ids, status="summary_staged")

    candidates = [{"session_name": "sess", "source_memory_ids": ids, "preview": ["c0", "c1", "c2"]}]
    persist_candidates_to_staging(mem, candidates)

    with mem.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM compaction_staging").fetchone()[0]
    assert count == 1


def test_persist_allows_reinsertion_after_applied(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]

    _insert_staging_row(mem, "sess", ids, status="applied")

    candidates = [{"session_name": "sess", "source_memory_ids": ids, "preview": ["c0", "c1", "c2"]}]
    persist_candidates_to_staging(mem, candidates)

    with mem.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM compaction_staging").fetchone()[0]
    assert count == 2  # original applied + new pending_summary


# --- mark_stale_candidates ---

def test_mark_stale_expires_past_expiry(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]

    snap = {mem_id: f"hash-{mem_id}" for mem_id in ids}
    row_id = _insert_staging_row(mem, "sess", ids, expires_hours=-1, snapshot=snap)

    mark_stale_candidates(mem, "sess")

    assert _get_staging_row(mem, row_id)["status"] == "stale"


def test_mark_stale_detects_content_hash_change(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"original-{i}") for i in range(3)]

    # Snapshot uses original hashes
    snap = {ids[i]: f"original-{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, snapshot=snap)

    # Simulate content change on first source row
    with mem.get_connection() as conn:
        conn.execute("UPDATE memories SET content_hash = 'changed-hash' WHERE id = ?", (ids[0],))

    mark_stale_candidates(mem, "sess")

    assert _get_staging_row(mem, row_id)["status"] == "stale"


def test_mark_stale_detects_already_compacted_source(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"h{i}") for i in range(3)]

    snap = {ids[i]: f"h{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, snapshot=snap)

    # Mark first source as already compacted
    with mem.get_connection() as conn:
        conn.execute("UPDATE memories SET compaction_role = 'source' WHERE id = ?", (ids[0],))

    mark_stale_candidates(mem, "sess")

    assert _get_staging_row(mem, row_id)["status"] == "stale"


def test_mark_stale_detects_missing_source(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]

    snap = {mem_id: f"hash-{mem_id}" for mem_id in ids}
    row_id = _insert_staging_row(mem, "sess", ids, snapshot=snap)

    # Delete a source row
    with mem.get_connection() as conn:
        conn.execute("DELETE FROM memories WHERE id = ?", (ids[0],))

    mark_stale_candidates(mem, "sess")

    assert _get_staging_row(mem, row_id)["status"] == "stale"


def test_mark_stale_leaves_valid_candidate_unchanged(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"stable-{i}") for i in range(3)]

    snap = {ids[i]: f"stable-{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, snapshot=snap)

    mark_stale_candidates(mem, "sess")

    assert _get_staging_row(mem, row_id)["status"] == "pending_summary"


# --- endpoint function tests (calling async functions directly) ---

import pytest_asyncio


@pytest.mark.asyncio
async def test_get_candidates_excludes_expired(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    snap = {mem_id: f"hash-{mem_id}" for mem_id in ids}

    # expired candidate
    _insert_staging_row(mem, "sess", ids, expires_hours=-1, snapshot=snap)

    result = await ep.marm_get_compaction_candidates()
    assert result["candidates"] == []


@pytest.mark.asyncio
async def test_get_staged_excludes_expired(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]

    _insert_staging_row(mem, "sess", ids, status="summary_staged",
                         suggested_summary="A summary.", expires_hours=-1)

    result = await ep.marm_get_staged_summaries()
    assert result["proposals"] == []


@pytest.mark.asyncio
async def test_get_candidates_empty_when_no_pending(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    result = await ep.marm_get_compaction_candidates()
    assert result["candidates"] == []
    assert result["prompt_template"] is None


@pytest.mark.asyncio
async def test_get_candidates_returns_pending_with_prompt(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"content {i}", similar[i]) for i in range(3)]
    snap = {mem_id: f"hash-{mem_id}" for mem_id in ids}
    _insert_staging_row(mem, "sess", ids, snapshot=snap)

    result = await ep.marm_get_compaction_candidates()
    assert len(result["candidates"]) == 1
    cand = result["candidates"][0]
    assert cand["session_name"] == "sess"
    assert sorted(cand["source_memory_ids"]) == sorted(ids)
    assert "prompt" in cand
    assert "{memories}" not in cand["prompt"]  # placeholder was filled in
    assert "preview of" in cand["prompt"]  # staged preview text appears in filled prompt
    assert result["prompt_template"] is not None


@pytest.mark.asyncio
async def test_unified_compaction_candidates_action(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import CompactionRequest

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"content {i}", similar[i]) for i in range(3)]
    _insert_staging_row(mem, "sess", ids)

    result = await ep.marm_compaction(CompactionRequest(action="candidates"))

    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["session_name"] == "sess"


@pytest.mark.asyncio
async def test_unified_compaction_status_action_is_bounded(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import CompactionRequest

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids_a = [_insert_memory_row(mem, "sess", f"a{i}", similar[i]) for i in range(3)]
    ids_b = [_insert_memory_row(mem, "sess", f"b{i}", similar[i]) for i in range(3)]
    _insert_staging_row(mem, "sess", ids_a, status="pending_summary")
    staged_id = _insert_staging_row(
        mem,
        "sess",
        ids_b,
        status="summary_staged",
        suggested_summary="B summary.",
    )

    result = await ep.marm_compaction(CompactionRequest(action="status"))

    assert result["status"] == "ok"
    assert result["counts"]["pending_summary"] == 1
    assert result["counts"]["summary_staged"] == 1
    assert result["staged_candidate_ids"] == [staged_id]
    assert "candidates" not in result
    assert "proposals" not in result


@pytest.mark.asyncio
async def test_unified_compaction_review_action_returns_staged_proposals(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import CompactionRequest

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(
        mem,
        "sess",
        ids,
        status="summary_staged",
        suggested_summary="Reviewable staged summary.",
    )

    result = await ep.marm_compaction(CompactionRequest(action="review"))

    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["candidate_id"] == row_id
    assert result["proposals"][0]["suggested_summary"] == "Reviewable staged summary."
    assert result["limit"] == 20


@pytest.mark.asyncio
async def test_unified_compaction_review_action_is_limited(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import CompactionRequest

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    for idx in range(3):
        ids = [
            _insert_memory_row(mem, "sess", f"review {idx}-{i}", similar[i])
            for i in range(3)
        ]
        _insert_staging_row(
            mem,
            "sess",
            ids,
            status="summary_staged",
            suggested_summary=f"Summary {idx}.",
        )

    result = await ep.marm_compaction(CompactionRequest(action="review", limit=2))

    assert result["limit"] == 2
    assert len(result["proposals"]) == 2


@pytest.mark.asyncio
async def test_stage_summaries_advances_to_summary_staged(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import StageCompactionSummariesRequest, StagedSummaryItem
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"ch{i}") for i in range(3)]
    snap = {ids[i]: f"ch{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, snapshot=snap)

    req = StageCompactionSummariesRequest(summaries=[
        StagedSummaryItem(candidate_id=row_id, source_memory_ids=ids, suggested_summary="Summary of cluster.")
    ])
    result = await ep.marm_stage_compaction_summaries(req)

    assert result["results"][0]["status"] == "summary_staged"
    assert _get_staging_row(mem, row_id)["status"] == "summary_staged"
    assert _get_staging_row(mem, row_id)["suggested_summary"] == "Summary of cluster."


@pytest.mark.asyncio
async def test_unified_compaction_stage_action(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import CompactionRequest, StagedSummaryItem

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"ch{i}") for i in range(3)]
    snap = {ids[i]: f"ch{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, snapshot=snap)

    result = await ep.marm_compaction(
        CompactionRequest(
            action="stage",
            summaries=[
                StagedSummaryItem(
                    candidate_id=row_id,
                    source_memory_ids=ids,
                    suggested_summary="Unified summary.",
                )
            ],
        )
    )

    assert result["results"][0]["status"] == "summary_staged"
    assert _get_staging_row(mem, row_id)["suggested_summary"] == "Unified summary."


@pytest.mark.asyncio
async def test_stage_succeeds_without_source_memory_ids(monkeypatch, tmp_path):
    """source_memory_ids is optional — server uses staged IDs when omitted."""
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import CompactionRequest, StagedSummaryItem

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"ch{i}") for i in range(3)]
    snap = {ids[i]: f"ch{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, snapshot=snap)

    result = await ep.marm_compaction(
        CompactionRequest(
            action="stage",
            summaries=[
                StagedSummaryItem(
                    candidate_id=row_id,
                    suggested_summary="Summary without providing source IDs.",
                )
            ],
        )
    )

    assert result["results"][0]["status"] == "summary_staged"
    assert _get_staging_row(mem, row_id)["suggested_summary"] == "Summary without providing source IDs."


@pytest.mark.asyncio
async def test_unified_compaction_stage_requires_summaries(monkeypatch, tmp_path):
    from pydantic import ValidationError
    from marm_mcp_server.core.models import CompactionRequest

    with pytest.raises(ValidationError, match="summaries is required"):
        CompactionRequest(action="stage")


@pytest.mark.asyncio
async def test_stage_summaries_rejects_wrong_status(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import StageCompactionSummariesRequest, StagedSummaryItem
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids, status="summary_staged")

    req = StageCompactionSummariesRequest(summaries=[
        StagedSummaryItem(candidate_id=row_id, source_memory_ids=ids, suggested_summary="A summary.")
    ])
    result = await ep.marm_stage_compaction_summaries(req)

    assert result["results"][0]["status"] == "error"
    assert "pending_summary" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_stage_summaries_rejects_empty_summary(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import StageCompactionSummariesRequest, StagedSummaryItem
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids)

    req = StageCompactionSummariesRequest(summaries=[
        StagedSummaryItem(candidate_id=row_id, source_memory_ids=ids, suggested_summary="   ")
    ])
    result = await ep.marm_stage_compaction_summaries(req)

    assert result["results"][0]["status"] == "error"
    assert "empty" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_stage_summaries_rejects_mismatched_source_ids(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import StageCompactionSummariesRequest, StagedSummaryItem
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids)

    wrong_ids = ids[:2] + [str(uuid.uuid4())]
    req = StageCompactionSummariesRequest(summaries=[
        StagedSummaryItem(candidate_id=row_id, source_memory_ids=wrong_ids, suggested_summary="A summary.")
    ])
    result = await ep.marm_stage_compaction_summaries(req)

    assert result["results"][0]["status"] == "error"
    assert "source_memory_ids" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_stage_summaries_rejects_already_compacted_source(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import StageCompactionSummariesRequest, StagedSummaryItem
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids)

    # Mark first source as already compacted
    with mem.get_connection() as conn:
        conn.execute("UPDATE memories SET compaction_role = 'source' WHERE id = ?", (ids[0],))

    req = StageCompactionSummariesRequest(summaries=[
        StagedSummaryItem(candidate_id=row_id, source_memory_ids=ids, suggested_summary="A summary.")
    ])
    result = await ep.marm_stage_compaction_summaries(req)

    assert result["results"][0]["status"] == "error"
    assert "already compacted" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_get_staged_summaries_returns_only_summary_staged(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids_a = [_insert_memory_row(mem, "s", f"a{i}", similar[i]) for i in range(3)]
    ids_b = [_insert_memory_row(mem, "s", f"b{i}", similar[i]) for i in range(3)]

    _insert_staging_row(mem, "s", ids_a, status="pending_summary")
    row_id = _insert_staging_row(mem, "s", ids_b, status="summary_staged", suggested_summary="B summary.")

    result = await ep.marm_get_staged_summaries()
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["candidate_id"] == row_id
    assert result["proposals"][0]["suggested_summary"] == "B summary."


@pytest.mark.asyncio
async def test_get_staged_summaries_empty_when_none(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    result = await ep.marm_get_staged_summaries()
    assert result["proposals"] == []


@pytest.mark.asyncio
async def test_apply_discard_no_write_to_memories(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import ApplyCompactionRequest
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids, status="summary_staged", suggested_summary="A summary.")

    with mem.get_connection() as conn:
        count_before = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    result = await ep.marm_apply_compaction(ApplyCompactionRequest(candidate_id=row_id, action="discard"))

    assert result["status"] == "discarded"
    assert _get_staging_row(mem, row_id)["status"] == "discarded"
    assert _get_staging_row(mem, row_id)["reviewed_at"] is not None

    with mem.get_connection() as conn:
        count_after = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    assert count_after == count_before  # no write


@pytest.mark.asyncio
async def test_unified_compaction_discard_action(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import CompactionRequest

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(
        mem,
        "sess",
        ids,
        status="summary_staged",
        suggested_summary="A summary.",
    )

    result = await ep.marm_compaction(
        CompactionRequest(action="discard", candidate_id=row_id)
    )

    assert result["status"] == "discarded"
    assert _get_staging_row(mem, row_id)["status"] == "discarded"


@pytest.mark.asyncio
async def test_apply_action_inserts_summary_and_marks_sources(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import ApplyCompactionRequest
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True  # skip embedding generation
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"ch{i}") for i in range(3)]
    snap = {ids[i]: f"ch{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, status="summary_staged",
                                  suggested_summary="Merged cluster.", snapshot=snap)

    result = await ep.marm_apply_compaction(ApplyCompactionRequest(candidate_id=row_id, action="apply"))

    assert result["status"] == "applied"
    summary_id = result["summary_memory_id"]

    # Staging row updated
    assert _get_staging_row(mem, row_id)["status"] == "applied"
    assert _get_staging_row(mem, row_id)["reviewed_at"] is not None

    with mem.get_connection() as conn:
        # Summary row exists
        summary_row = conn.execute(
            "SELECT compaction_role, content, metadata FROM memories WHERE id = ?", (summary_id,)
        ).fetchone()
        assert summary_row is not None
        assert summary_row[0] == "summary"
        assert summary_row[1] == "Merged cluster."
        meta = json.loads(summary_row[2])
        assert meta["compaction_role"] == "summary"
        assert sorted(meta["source_memory_ids"]) == sorted(ids)

        # Source rows updated
        for mem_id in ids:
            src_row = conn.execute(
                "SELECT compaction_role, compacted_into FROM memories WHERE id = ?", (mem_id,)
            ).fetchone()
            assert src_row[0] == "source"
            assert src_row[1] == summary_id

        # Source rows still exist — not deleted
        remaining = conn.execute(
            f"SELECT COUNT(*) FROM memories WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchone()[0]
    assert remaining == len(ids)


@pytest.mark.asyncio
async def test_unified_compaction_apply_action(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import CompactionRequest

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"ch{i}") for i in range(3)]
    snap = {ids[i]: f"ch{i}" for i in range(3)}
    row_id = _insert_staging_row(
        mem,
        "sess",
        ids,
        status="summary_staged",
        suggested_summary="Merged cluster.",
        snapshot=snap,
    )

    result = await ep.marm_compaction(
        CompactionRequest(action="apply", candidate_id=row_id)
    )

    assert result["status"] == "applied"
    assert _get_staging_row(mem, row_id)["status"] == "applied"


@pytest.mark.asyncio
async def test_unified_compaction_apply_requires_candidate_id(monkeypatch, tmp_path):
    from pydantic import ValidationError
    from marm_mcp_server.core.models import CompactionRequest

    with pytest.raises(ValidationError, match="candidate_id is required"):
        CompactionRequest(action="apply")


@pytest.mark.asyncio
async def test_apply_is_idempotent(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import ApplyCompactionRequest
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"ch{i}") for i in range(3)]
    snap = {ids[i]: f"ch{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, status="summary_staged",
                                  suggested_summary="A summary.", snapshot=snap)

    r1 = await ep.marm_apply_compaction(ApplyCompactionRequest(candidate_id=row_id, action="apply"))
    assert r1["status"] == "applied"

    with mem.get_connection() as conn:
        count_after_first = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    r2 = await ep.marm_apply_compaction(ApplyCompactionRequest(candidate_id=row_id, action="apply"))
    assert r2["status"] == "applied"  # idempotent — returns success

    with mem.get_connection() as conn:
        count_after_second = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    assert count_after_first == count_after_second  # no second write


@pytest.mark.asyncio
async def test_apply_rejects_wrong_status(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import ApplyCompactionRequest
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids, status="pending_summary")

    result = await ep.marm_apply_compaction(ApplyCompactionRequest(candidate_id=row_id, action="apply"))

    assert result["status"] == "error"
    assert "summary_staged" in result["reason"]


@pytest.mark.asyncio
async def test_apply_rejects_already_compacted_source(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import ApplyCompactionRequest
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"ch{i}") for i in range(3)]
    snap = {ids[i]: f"ch{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, status="summary_staged",
                                  suggested_summary="A summary.", snapshot=snap)

    # Compacted between staging and apply
    with mem.get_connection() as conn:
        conn.execute("UPDATE memories SET compaction_role = 'source' WHERE id = ?", (ids[0],))

    result = await ep.marm_apply_compaction(ApplyCompactionRequest(candidate_id=row_id, action="apply"))

    assert result["status"] == "error"
    assert "already compacted" in result["reason"]


@pytest.mark.asyncio
async def test_apply_marks_stale_on_snapshot_mismatch(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import ApplyCompactionRequest
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"orig{i}") for i in range(3)]
    snap = {ids[i]: f"orig{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, status="summary_staged",
                                  suggested_summary="A summary.", snapshot=snap)

    # Content changed after staging
    with mem.get_connection() as conn:
        conn.execute("UPDATE memories SET content_hash = 'changed' WHERE id = ?", (ids[1],))

    result = await ep.marm_apply_compaction(ApplyCompactionRequest(candidate_id=row_id, action="apply"))

    assert result["status"] == "error"
    assert "changed" in result["reason"]
    assert _get_staging_row(mem, row_id)["status"] == "stale"


@pytest.mark.asyncio
async def test_stage_marks_stale_when_source_missing(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import StageCompactionSummariesRequest, StagedSummaryItem
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids)

    with mem.get_connection() as conn:
        conn.execute("DELETE FROM memories WHERE id = ?", (ids[0],))

    req = StageCompactionSummariesRequest(summaries=[
        StagedSummaryItem(candidate_id=row_id, source_memory_ids=ids, suggested_summary="A summary.")
    ])
    result = await ep.marm_stage_compaction_summaries(req)

    assert result["results"][0]["status"] == "error"
    assert _get_staging_row(mem, row_id)["status"] == "stale"


@pytest.mark.asyncio
async def test_stage_marks_stale_when_source_already_compacted(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import StageCompactionSummariesRequest, StagedSummaryItem
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids)

    with mem.get_connection() as conn:
        conn.execute("UPDATE memories SET compaction_role = 'source' WHERE id = ?", (ids[0],))

    req = StageCompactionSummariesRequest(summaries=[
        StagedSummaryItem(candidate_id=row_id, source_memory_ids=ids, suggested_summary="A summary.")
    ])
    result = await ep.marm_stage_compaction_summaries(req)

    assert result["results"][0]["status"] == "error"
    assert "already compacted" in result["results"][0]["reason"]
    assert _get_staging_row(mem, row_id)["status"] == "stale"


@pytest.mark.asyncio
async def test_apply_marks_stale_when_source_missing(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import ApplyCompactionRequest
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"ch{i}") for i in range(3)]
    snap = {ids[i]: f"ch{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, status="summary_staged",
                                  suggested_summary="A summary.", snapshot=snap)

    # Delete one source row after staging
    with mem.get_connection() as conn:
        conn.execute("DELETE FROM memories WHERE id = ?", (ids[0],))

    result = await ep.marm_apply_compaction(ApplyCompactionRequest(candidate_id=row_id, action="apply"))

    assert result["status"] == "error"
    assert "not found" in result["reason"]
    assert _get_staging_row(mem, row_id)["status"] == "stale"


@pytest.mark.asyncio
async def test_apply_marks_stale_when_source_already_compacted_at_apply(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import ApplyCompactionRequest
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i], content_hash=f"ch{i}") for i in range(3)]
    snap = {ids[i]: f"ch{i}" for i in range(3)}
    row_id = _insert_staging_row(mem, "sess", ids, status="summary_staged",
                                  suggested_summary="A summary.", snapshot=snap)

    # Compact one source between staging and apply
    with mem.get_connection() as conn:
        conn.execute("UPDATE memories SET compaction_role = 'source' WHERE id = ?", (ids[1],))

    result = await ep.marm_apply_compaction(ApplyCompactionRequest(candidate_id=row_id, action="apply"))

    assert result["status"] == "error"
    assert "already compacted" in result["reason"]
    assert _get_staging_row(mem, row_id)["status"] == "stale"


@pytest.mark.asyncio
async def test_apply_not_found_returns_error(monkeypatch, tmp_path):
    import marm_mcp_server.endpoints.compaction as ep
    from marm_mcp_server.core.models import ApplyCompactionRequest
    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(ep, "memory", mem)

    result = await ep.marm_apply_compaction(
        ApplyCompactionRequest(candidate_id=str(uuid.uuid4()), action="apply")
    )
    assert result["status"] == "error"
    assert "not found" in result["reason"]


# --- compaction nudge claim ---


def test_claim_pending_compaction_prompt_increments_nudge_count(monkeypatch, tmp_path):
    import marm_mcp_server.core.compaction as compaction_module

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_MAX_NUDGES", 5)
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_NUDGE_COOLDOWN_SECONDS", 2
    )
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_INJECTION_BYTE_BUDGET", 2048
    )

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids)

    block = compaction_module.claim_pending_compaction_prompt(mem)

    assert block is not None
    assert block["type"] == "text"
    assert "[MARM COMPACTION REQUEST]" in block["text"]
    assert row_id in block["text"]
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT nudge_count, last_nudged_at, status FROM compaction_staging WHERE id = ?",
            (row_id,),
        ).fetchone()
    assert row[0] == 1
    assert row[1] is not None
    assert row[2] == "pending_summary"


def test_compaction_prompt_block_enforces_byte_budget_and_preserves_footer():
    row = (
        "candidate-1",
        "session-1",
        json.dumps(["m1", "m2", "m3"]),
        json.dumps(["x" * 1000, "y" * 1000, "z" * 1000]),
        "2026-06-01T00:00:00+00:00",
        "2026-06-02T00:00:00+00:00",
        1,
    )

    block = _build_compaction_prompt_block(row, 200)

    assert len(block["text"].encode("utf-8")) <= 200
    assert "Do not invent facts" in block["text"]


def test_claim_pending_compaction_prompt_respects_cooldown(monkeypatch, tmp_path):
    import marm_mcp_server.core.compaction as compaction_module

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_MAX_NUDGES", 5)
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_NUDGE_COOLDOWN_SECONDS", 60
    )

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids)

    assert compaction_module.claim_pending_compaction_prompt(mem) is not None
    assert compaction_module.claim_pending_compaction_prompt(mem) is None
    with mem.get_connection() as conn:
        nudge_count = conn.execute(
            "SELECT nudge_count FROM compaction_staging WHERE id = ?",
            (row_id,),
        ).fetchone()[0]
    assert nudge_count == 1


def test_claim_pending_compaction_prompt_marks_nudge_exhausted(monkeypatch, tmp_path):
    import marm_mcp_server.core.compaction as compaction_module

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_MAX_NUDGES", 1)
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_NUDGE_COOLDOWN_SECONDS", 0
    )

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids)

    assert compaction_module.claim_pending_compaction_prompt(mem) is not None
    assert compaction_module.claim_pending_compaction_prompt(mem) is None
    assert _get_staging_row(mem, row_id)["status"] == "nudge_exhausted"


def test_auto_apply_enabled_does_not_suppress_pending_summary_injection(monkeypatch, tmp_path):
    import marm_mcp_server.core.compaction as compaction_module

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_AUTO_APPLY_ENABLED", True
    )
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_MAX_NUDGES", 5)
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_NUDGE_COOLDOWN_SECONDS", 2
    )

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids, status="pending_summary")

    block = compaction_module.claim_pending_compaction_prompt(mem)

    assert block is not None
    assert row_id in block["text"]
    assert _get_staging_row(mem, row_id)["status"] == "pending_summary"


def test_claim_pending_compaction_prompt_concurrent_claims_one(monkeypatch, tmp_path):
    import marm_mcp_server.core.compaction as compaction_module

    mem = MARMMemory(str(tmp_path / "memory.db"))
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_MAX_NUDGES", 5)
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_NUDGE_COOLDOWN_SECONDS", 60
    )

    similar = _make_similar_embeddings(3)
    ids = [_insert_memory_row(mem, "sess", f"c{i}", similar[i]) for i in range(3)]
    row_id = _insert_staging_row(mem, "sess", ids)

    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(compaction_module.claim_pending_compaction_prompt, mem) for _ in range(5)]
        for future in as_completed(futures):
            results.append(future.result())

    assert sum(1 for item in results if item is not None) == 1
    with mem.get_connection() as conn:
        nudge_count = conn.execute(
            "SELECT nudge_count FROM compaction_staging WHERE id = ?",
            (row_id,),
        ).fetchone()[0]
    assert nudge_count == 1
