"""Tests for compaction Layer 3 — V4 write-queue integration and scheduled auto-apply."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from marm_mcp_server.core.compaction import _compute_candidate_hash
from marm_mcp_server.core.memory import MARMMemory
from marm_mcp_server.core.models import ApplyCompactionRequest, CompactionRequest
from marm_mcp_server.core.write_queue import CallableWriteRequest, WriteQueue
from marm_mcp_server.endpoints.compaction import (
    _apply_compaction_write,
    auto_apply_staged_summaries,
    marm_apply_compaction,
    marm_compaction,
)

# --- helpers (mirrored from v2 test file) ---


def _make_embedding(dim: int = 384) -> bytes:
    rng = np.random.default_rng(seed=7)
    v = rng.standard_normal(dim).astype(np.float32)
    v = v / np.linalg.norm(v)
    return v.tobytes()


def _insert_memory_row(
    mem: MARMMemory,
    session: str,
    content: str,
    age_hours: float = 48.0,
    compaction_role: str | None = None,
) -> tuple[str, str]:
    ts = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    mem_id = str(uuid.uuid4())
    content_hash = f"hash-{mem_id}"
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories "
            "(id, session_name, content, embedding, timestamp, context_type, metadata, content_hash, compaction_role) "
            "VALUES (?, ?, ?, ?, ?, 'general', '{}', ?, ?)",
            (
                mem_id,
                session,
                content,
                _make_embedding(),
                ts,
                content_hash,
                compaction_role,
            ),
        )
    return mem_id, content_hash


def _insert_staging_row(
    mem: MARMMemory,
    session: str,
    source_ids: list,
    status: str = "summary_staged",
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
                suggested_summary or "A concise summary of related memories.",
                status,
                _compute_candidate_hash(source_ids),
                json.dumps(snap),
                expires_at,
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return row_id


def _get_staging_status(mem: MARMMemory, row_id: str) -> str | None:
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM compaction_staging WHERE id = ?", (row_id,)
        ).fetchone()
    return row[0] if row else None


def _get_memory_compaction_role(mem: MARMMemory, mem_id: str) -> str | None:
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT compaction_role FROM memories WHERE id = ?", (mem_id,)
        ).fetchone()
    return row[0] if row else None


# --- fixtures ---


@pytest.fixture
def mem(tmp_path):
    m = MARMMemory(db_path=str(tmp_path / "test.db"))
    m.init_database()
    return m


@pytest.fixture(autouse=True)
def patch_global_memory(mem, monkeypatch):
    """Patch memory in the module dict the collected functions actually reference.

    load_isolated_server in other test files can replace sys.modules entries,
    so a fresh `import ... as ep` may return a different object than what the
    top-level `from ... import func` already bound at collection time. Patching
    via __globals__ targets the real dict these functions use regardless.
    """
    monkeypatch.setitem(marm_apply_compaction.__globals__, "memory", mem)
    yield


# --- write queue unit tests ---


def test_callable_write_request_fields():
    """CallableWriteRequest holds func, args, kwargs, and future."""
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    loop.close()

    async def dummy():
        return "ok"

    req = CallableWriteRequest(func=dummy, args=(), kwargs={}, future=future)
    assert req.func is dummy
    assert req.args == ()
    assert req.kwargs == {}
    assert req.future is future


@pytest.mark.asyncio
async def test_write_queue_put_callable_executes_and_returns(mem):
    """put_callable enqueues an async callable and returns its result."""
    queue = WriteQueue(mem, max_size=10)
    await queue.start()

    async def add(a, b):
        return a + b

    result = await queue.put_callable(add, 3, 4)
    assert result == 7
    await queue.stop()


@pytest.mark.asyncio
async def test_write_queue_put_callable_ordering(mem):
    """Callables execute in FIFO order through the same worker as MemoryWriteRequests."""
    queue = WriteQueue(mem, max_size=10)
    await queue.start()

    order = []

    async def record(n):
        order.append(n)
        return n

    try:
        await queue.put_callable(record, 1)
        await queue.put_callable(record, 2)
        await queue.put_callable(record, 3)
        assert order == [1, 2, 3]
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_write_queue_callable_exception_propagates(mem):
    """An exception raised inside put_callable propagates to the caller."""
    queue = WriteQueue(mem, max_size=10)
    await queue.start()

    async def boom():
        raise ValueError("expected failure")

    with pytest.raises(ValueError, match="expected failure"):
        await queue.put_callable(boom)

    await queue.stop()


@pytest.mark.asyncio
async def test_write_queue_put_callable_rejected_when_stopping(mem):
    """put_callable raises RuntimeError when queue is shutting down."""
    queue = WriteQueue(mem, max_size=10)
    await queue.start()
    queue._stopping = True

    try:
        with pytest.raises(RuntimeError, match="shutting down"):
            await queue.put_callable(lambda: None)
    finally:
        await queue.stop()


# --- apply via write queue ---


@pytest.mark.asyncio
async def test_apply_compaction_routes_through_write_queue(mem):
    """marm_apply_compaction enqueues write via write queue when queue is running."""
    session = "queue-route-session"
    ids_and_hashes = [_insert_memory_row(mem, session, f"memory {i}") for i in range(3)]
    source_ids = [m[0] for m in ids_and_hashes]
    snapshot = {m[0]: m[1] for m in ids_and_hashes}

    candidate_id = _insert_staging_row(
        mem, session, source_ids, status="summary_staged", snapshot=snapshot
    )

    queue = WriteQueue(mem, max_size=10)
    await queue.start()
    mem._write_queue = queue

    result = await marm_apply_compaction(
        ApplyCompactionRequest(candidate_id=candidate_id, action="apply")
    )

    await queue.stop()
    mem._write_queue = None

    assert result["status"] == "applied"
    assert "summary_memory_id" in result
    assert _get_staging_status(mem, candidate_id) == "applied"

    # Source rows should be marked compacted
    for mem_id in source_ids:
        assert _get_memory_compaction_role(mem, mem_id) == "source"


@pytest.mark.asyncio
async def test_unified_apply_compaction_routes_through_write_queue(mem):
    """marm_compaction(action='apply') uses the same queued apply path."""
    session = "unified-queue-route-session"
    ids_and_hashes = [_insert_memory_row(mem, session, f"memory {i}") for i in range(3)]
    source_ids = [m[0] for m in ids_and_hashes]
    snapshot = {m[0]: m[1] for m in ids_and_hashes}

    candidate_id = _insert_staging_row(
        mem, session, source_ids, status="summary_staged", snapshot=snapshot
    )

    queue = WriteQueue(mem, max_size=10)
    await queue.start()
    mem._write_queue = queue

    result = await marm_compaction(
        CompactionRequest(action="apply", candidate_id=candidate_id)
    )

    await queue.stop()
    mem._write_queue = None

    assert result["status"] == "applied"
    assert "summary_memory_id" in result
    assert _get_staging_status(mem, candidate_id) == "applied"
    for mem_id in source_ids:
        assert _get_memory_compaction_role(mem, mem_id) == "source"


@pytest.mark.asyncio
async def test_apply_compaction_direct_when_no_queue(mem):
    """marm_apply_compaction uses BEGIN IMMEDIATE directly when write queue is None."""
    session = "direct-apply-session"
    ids_and_hashes = [_insert_memory_row(mem, session, f"memory {i}") for i in range(3)]
    source_ids = [m[0] for m in ids_and_hashes]
    snapshot = {m[0]: m[1] for m in ids_and_hashes}

    candidate_id = _insert_staging_row(
        mem, session, source_ids, status="summary_staged", snapshot=snapshot
    )

    # Ensure no queue is active
    mem._write_queue = None

    result = await marm_apply_compaction(
        ApplyCompactionRequest(candidate_id=candidate_id, action="apply")
    )

    assert result["status"] == "applied"
    assert _get_staging_status(mem, candidate_id) == "applied"


# --- _apply_compaction_write unit ---


@pytest.mark.asyncio
async def test_apply_compaction_write_inserts_summary_and_marks_sources(mem):
    """_apply_compaction_write correctly inserts summary row and updates source rows."""
    session = "write-unit-session"
    ids_and_hashes = [_insert_memory_row(mem, session, f"fact {i}") for i in range(3)]
    source_ids = [m[0] for m in ids_and_hashes]

    now = datetime.now(timezone.utc).isoformat()
    candidate_id = str(uuid.uuid4())
    snapshot = {mem_id: content_hash for mem_id, content_hash in ids_and_hashes}
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO compaction_staging "
            "(id, session_name, source_memory_ids, preview, suggested_summary, status, "
            "candidate_hash, source_updated_at_snapshot, expires_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'summary_staged', ?, ?, ?, ?, ?)",
            (
                candidate_id,
                session,
                json.dumps(source_ids),
                json.dumps(["p"]),
                "Test summary.",
                _compute_candidate_hash(source_ids),
                json.dumps(snapshot),
                (datetime.now(timezone.utc) + timedelta(hours=168)).isoformat(),
                now,
                now,
            ),
        )

    summary_id = await _apply_compaction_write(candidate_id)

    # Summary row exists with correct role
    with mem.get_connection() as conn:
        summary_row = conn.execute(
            "SELECT id, compaction_role, content FROM memories WHERE id = ?",
            (summary_id,),
        ).fetchone()
    assert summary_row is not None
    assert summary_row[1] == "summary"
    assert summary_row[2] == "Test summary."

    # Source rows updated
    for mem_id in source_ids:
        assert _get_memory_compaction_role(mem, mem_id) == "source"

    # Staging row marked applied
    assert _get_staging_status(mem, candidate_id) == "applied"


# --- auto-apply scheduled job ---


@pytest.mark.asyncio
async def test_auto_apply_applies_all_staged(mem):
    """auto_apply_staged_summaries applies all summary_staged candidates."""
    session = "auto-apply-session"

    candidate_ids = []
    all_source_ids = []
    for batch in range(2):
        ids_and_hashes = [
            _insert_memory_row(mem, session, f"b{batch} m{i}") for i in range(3)
        ]
        source_ids = [m[0] for m in ids_and_hashes]
        snapshot = {m[0]: m[1] for m in ids_and_hashes}
        cid = _insert_staging_row(
            mem, session, source_ids, status="summary_staged", snapshot=snapshot
        )
        candidate_ids.append(cid)
        all_source_ids.extend(source_ids)

    result = await auto_apply_staged_summaries()

    assert len(result["applied"]) == 2
    assert len(result["skipped"]) == 0
    for cid in candidate_ids:
        assert _get_staging_status(mem, cid) == "applied"


@pytest.mark.asyncio
async def test_auto_apply_skips_expired_candidates(mem):
    """auto_apply_staged_summaries reports expired candidates in skipped and marks them stale."""
    session = "auto-apply-expired-session"

    ids_and_hashes = [_insert_memory_row(mem, session, f"m{i}") for i in range(3)]
    source_ids = [m[0] for m in ids_and_hashes]
    snapshot = {m[0]: m[1] for m in ids_and_hashes}

    # Insert expired staging row (expires_at in the past)
    cid = _insert_staging_row(
        mem,
        session,
        source_ids,
        status="summary_staged",
        expires_hours=-1.0,
        snapshot=snapshot,
    )

    result = await auto_apply_staged_summaries()

    # Expired row is fetched, apply rejects it, and it appears in skipped
    assert len(result["applied"]) == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["candidate_id"] == cid
    assert _get_staging_status(mem, cid) == "stale"


@pytest.mark.asyncio
async def test_auto_apply_skips_stale_snapshot_candidate(mem):
    """auto_apply_staged_summaries skips candidates whose snapshot no longer matches."""
    session = "auto-apply-stale-session"

    ids_and_hashes = [_insert_memory_row(mem, session, f"m{i}") for i in range(3)]
    source_ids = [m[0] for m in ids_and_hashes]

    # Snapshot with wrong hashes — will fail validation inside marm_apply_compaction
    bad_snapshot = {sid: "wrong-hash" for sid in source_ids}
    cid = _insert_staging_row(
        mem, session, source_ids, status="summary_staged", snapshot=bad_snapshot
    )

    result = await auto_apply_staged_summaries()

    assert len(result["applied"]) == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["candidate_id"] == cid
    assert _get_staging_status(mem, cid) == "stale"


@pytest.mark.asyncio
async def test_auto_apply_skips_already_compacted_sources(mem):
    """auto_apply_staged_summaries skips candidates whose source rows are already compacted."""
    session = "auto-apply-compacted-session"

    ids_and_hashes = [
        _insert_memory_row(mem, session, f"m{i}", compaction_role="source")
        for i in range(3)
    ]
    source_ids = [m[0] for m in ids_and_hashes]
    snapshot = {m[0]: m[1] for m in ids_and_hashes}

    cid = _insert_staging_row(
        mem, session, source_ids, status="summary_staged", snapshot=snapshot
    )

    result = await auto_apply_staged_summaries()

    assert len(result["applied"]) == 0
    assert len(result["skipped"]) == 1
    assert _get_staging_status(mem, cid) == "stale"


@pytest.mark.asyncio
async def test_auto_apply_mixed_valid_and_stale(mem):
    """auto_apply_staged_summaries applies valid candidates and skips stale ones."""
    session = "auto-apply-mixed-session"

    # Valid candidate
    good_ids_hashes = [_insert_memory_row(mem, session, f"good m{i}") for i in range(3)]
    good_source_ids = [m[0] for m in good_ids_hashes]
    good_snapshot = {m[0]: m[1] for m in good_ids_hashes}
    good_cid = _insert_staging_row(
        mem, session, good_source_ids, status="summary_staged", snapshot=good_snapshot
    )

    # Stale candidate (bad snapshot)
    bad_ids_hashes = [_insert_memory_row(mem, session, f"bad m{i}") for i in range(3)]
    bad_source_ids = [m[0] for m in bad_ids_hashes]
    bad_snapshot = {sid: "wrong-hash" for sid in bad_source_ids}
    bad_cid = _insert_staging_row(
        mem, session, bad_source_ids, status="summary_staged", snapshot=bad_snapshot
    )

    result = await auto_apply_staged_summaries()

    assert good_cid in result["applied"]
    assert any(s["candidate_id"] == bad_cid for s in result["skipped"])
    assert _get_staging_status(mem, good_cid) == "applied"
    assert _get_staging_status(mem, bad_cid) == "stale"


@pytest.mark.asyncio
async def test_auto_apply_empty_when_no_staged(mem):
    """auto_apply_staged_summaries returns empty lists when nothing is staged."""
    result = await auto_apply_staged_summaries()
    assert result == {"applied": [], "skipped": []}


@pytest.mark.asyncio
async def test_auto_apply_routes_through_write_queue(mem):
    """auto_apply_staged_summaries routes writes through the write queue when active."""
    session = "auto-apply-queue-session"
    ids_and_hashes = [_insert_memory_row(mem, session, f"m{i}") for i in range(3)]
    source_ids = [m[0] for m in ids_and_hashes]
    snapshot = {m[0]: m[1] for m in ids_and_hashes}
    cid = _insert_staging_row(
        mem, session, source_ids, status="summary_staged", snapshot=snapshot
    )

    queue = WriteQueue(mem, max_size=10)
    await queue.start()
    mem._write_queue = queue

    result = await auto_apply_staged_summaries()

    await queue.stop()
    mem._write_queue = None

    assert cid in result["applied"]
    assert _get_staging_status(mem, cid) == "applied"


# --- scheduler registration ---


def test_auto_apply_disabled_by_default(monkeypatch):
    """COMPACTION_AUTO_APPLY_ENABLED is False when the env var is not set."""
    import importlib
    import marm_mcp_server.config.settings as settings_mod

    monkeypatch.delenv("COMPACTION_AUTO_APPLY_ENABLED", raising=False)
    settings_mod = importlib.reload(settings_mod)

    assert settings_mod.COMPACTION_AUTO_APPLY_ENABLED is False


def test_maybe_start_scheduler_returns_none_when_disabled(monkeypatch):
    """_maybe_start_compaction_scheduler returns None when COMPACTION_AUTO_APPLY_ENABLED=False."""
    import marm_mcp_server.server as server_mod

    monkeypatch.setattr(server_mod, "COMPACTION_AUTO_APPLY_ENABLED", False)
    result = server_mod._maybe_start_compaction_scheduler()
    assert result is None


def test_maybe_start_scheduler_returns_none_when_unavailable(monkeypatch):
    """_maybe_start_compaction_scheduler returns None when SCHEDULER_AVAILABLE=False."""
    import marm_mcp_server.server as server_mod

    monkeypatch.setattr(server_mod, "COMPACTION_AUTO_APPLY_ENABLED", True)
    monkeypatch.setattr(server_mod, "SCHEDULER_AVAILABLE", False)
    result = server_mod._maybe_start_compaction_scheduler()
    assert result is None


@pytest.mark.asyncio
async def test_maybe_start_scheduler_registers_job_when_enabled(monkeypatch):
    """_maybe_start_compaction_scheduler registers compaction_auto_apply job when both flags are True."""
    import marm_mcp_server.server as server_mod

    monkeypatch.setattr(server_mod, "COMPACTION_AUTO_APPLY_ENABLED", True)
    monkeypatch.setattr(server_mod, "SCHEDULER_AVAILABLE", True)
    monkeypatch.setattr(server_mod, "COMPACTION_AUTO_APPLY_INTERVAL_MINUTES", 60)
    scheduler = server_mod._maybe_start_compaction_scheduler()
    try:
        assert scheduler is not None
        job = scheduler.get_job("compaction_auto_apply")
        assert job is not None
    finally:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
