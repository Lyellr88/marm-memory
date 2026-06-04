"""Tests for compaction Layer 3 — write-count trigger, cluster detection, dry-run report."""

import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta

import numpy as np
import pytest

from marm_mcp_server.core.compaction import (
    find_compaction_candidates,
    run_compaction_dry_run,
    trigger_compaction,
)
from marm_mcp_server.core.memory import MARMMemory


# --- Embedding helpers ---

def _make_embedding(direction: int, dim: int = 384) -> bytes:
    """Unit vector pointing mostly in `direction` axis — easy to control similarity."""
    v = np.zeros(dim, dtype=np.float32)
    v[direction] = 1.0
    v[direction + 1] = 0.05
    v[direction + 2] = 0.05
    v = v / np.linalg.norm(v)
    return v.tobytes()


def _make_similar_embeddings(count: int = 3, base_axis: int = 0, dim: int = 384) -> list:
    """Return `count` embeddings with high mutual cosine similarity (all near base_axis).

    Noise scale 0.005 keeps pairwise similarity well above 0.88 threshold.
    """
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
) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    mem_id = str(uuid.uuid4())
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories "
            "(id, session_name, content, embedding, timestamp, context_type, metadata, content_hash, compaction_role) "
            "VALUES (?, ?, ?, ?, ?, 'general', '{}', ?, ?)",
            (mem_id, session, content, embedding, ts, f"hash-{mem_id}", compaction_role),
        )
    return mem_id


# --- find_compaction_candidates ---

def test_existing_embeddings_can_compact_when_encoder_unavailable(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    import marm_mcp_server.config.settings as s
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 0)

    similar = _make_similar_embeddings(3)
    for i, emb in enumerate(similar):
        _insert_memory_row(mem, "sess", f"content {i}", emb)

    result = find_compaction_candidates(mem, "sess")
    assert len(result) == 1
    assert result[0]["session_name"] == "sess"


def test_cluster_below_min_size_not_reported(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = False

    import marm_mcp_server.config.settings as s
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 0)

    similar = _make_similar_embeddings(2)  # only 2 — below min size of 3
    for i, emb in enumerate(similar):
        _insert_memory_row(mem, "sess", f"content {i}", emb, age_hours=48)

    result = find_compaction_candidates(mem, "sess")
    assert result == []


def test_young_memories_excluded_from_candidates(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = False

    import marm_mcp_server.config.settings as s
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 24)

    similar = _make_similar_embeddings(3)
    for i, emb in enumerate(similar):
        _insert_memory_row(mem, "sess", f"content {i}", emb, age_hours=12)  # only 12h old

    result = find_compaction_candidates(mem, "sess")
    assert result == []


def test_already_compacted_source_rows_excluded(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = False

    import marm_mcp_server.config.settings as s
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 0)

    similar = _make_similar_embeddings(3)
    for i, emb in enumerate(similar):
        _insert_memory_row(mem, "sess", f"content {i}", emb, compaction_role="source")

    result = find_compaction_candidates(mem, "sess")
    assert result == []


def test_already_compacted_summary_rows_excluded(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = False

    import marm_mcp_server.config.settings as s
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 0)

    similar = _make_similar_embeddings(3)
    for i, emb in enumerate(similar):
        _insert_memory_row(mem, "sess", f"content {i}", emb, compaction_role="summary")

    result = find_compaction_candidates(mem, "sess")
    assert result == []


def test_cross_session_memories_never_grouped(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = False

    import marm_mcp_server.config.settings as s
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 0)

    similar = _make_similar_embeddings(6)
    # 3 in session-a, 3 in session-b — all similar to each other
    for i, emb in enumerate(similar[:3]):
        _insert_memory_row(mem, "session-a", f"content {i}", emb)
    for i, emb in enumerate(similar[3:]):
        _insert_memory_row(mem, "session-b", f"content {i}", emb)

    result_a = find_compaction_candidates(mem, "session-a")
    result_b = find_compaction_candidates(mem, "session-b")

    # Each session should only return its own cluster, never mixing sessions
    for candidate in result_a:
        assert candidate["session_name"] == "session-a"
    for candidate in result_b:
        assert candidate["session_name"] == "session-b"


def test_qualifying_cluster_reported_with_correct_shape(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = False

    import marm_mcp_server.config.settings as s
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 0)

    similar = _make_similar_embeddings(3)
    for i, emb in enumerate(similar):
        _insert_memory_row(mem, "session-x", f"memory content {i}", emb)

    result = find_compaction_candidates(mem, "session-x")

    assert len(result) == 1
    candidate = result[0]
    assert candidate["session_name"] == "session-x"
    assert len(candidate["source_memory_ids"]) == 3
    assert candidate["reason"] == "semantic_cluster"
    assert candidate["avg_similarity"] >= 0.88
    assert candidate["suggested_summary"] is None
    assert len(candidate["preview"]) == 3


# --- run_compaction_dry_run ---

def test_dry_run_does_not_mutate_db(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = False

    import marm_mcp_server.config.settings as s
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 0)

    similar = _make_similar_embeddings(3)
    inserted_ids = []
    for i, emb in enumerate(similar):
        inserted_ids.append(_insert_memory_row(mem, "sess", f"content {i}", emb))

    run_compaction_dry_run(mem, "sess")

    with mem.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, compaction_role, compacted_into FROM memories WHERE session_name = ?",
            ("sess",),
        ).fetchall()

    assert len(rows) == 3
    for row_id, role, compacted_into in rows:
        assert row_id in inserted_ids
        assert role is None
        assert compacted_into is None


def test_dry_run_writes_report_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = False

    import marm_mcp_server.config.settings as s
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 0)

    similar = _make_similar_embeddings(3)
    for i, emb in enumerate(similar):
        _insert_memory_row(mem, "my-session", f"content {i}", emb)

    run_compaction_dry_run(mem, "my-session")

    report_dir = tmp_path / "scripts" / "out" / "compaction"
    reports = list(report_dir.glob("compaction-report-my-session-*.json"))
    assert len(reports) == 1

    data = json.loads(reports[0].read_text())
    assert "candidates" in data
    assert len(data["candidates"]) == 1


def test_dry_run_uses_existing_embeddings_when_encoder_unavailable(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    similar = _make_similar_embeddings(3)
    for i, emb in enumerate(similar):
        _insert_memory_row(mem, "sess", f"content {i}", emb)

    report = run_compaction_dry_run(mem, "sess")
    assert len(report["candidates"]) == 1


def test_dry_run_no_file_written_when_no_candidates(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    run_compaction_dry_run(mem, "sess")

    report_dir = tmp_path / "scripts" / "out" / "compaction"
    assert not report_dir.exists()


# --- Write counter ---

@pytest.mark.asyncio
async def test_write_counter_increments_on_new_insert(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(memory_module, "COMPACTION_TRIGGER_COUNT", 99)

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("first write", "sess-counter")
    assert mem._session_write_counts.get("sess-counter") == 1

    await mem.store_memory("second write", "sess-counter")
    assert mem._session_write_counts.get("sess-counter") == 2


@pytest.mark.asyncio
async def test_write_counter_does_not_increment_on_layer1_skip(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    monkeypatch.setattr(memory_module, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(memory_module, "COMPACTION_TRIGGER_COUNT", 99)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("exact duplicate content", "sess-l1")
    count_after_first = mem._session_write_counts.get("sess-l1", 0)

    # Second write is an exact duplicate — Layer 1 skips it, counter must not increment
    await mem.store_memory("exact duplicate content", "sess-l1")
    assert mem._session_write_counts.get("sess-l1", 0) == count_after_first


@pytest.mark.asyncio
async def test_write_counter_increments_on_layer2_merge(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "CONSOLIDATION_ENABLED", True)
    monkeypatch.setattr(memory_module, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(memory_module, "COMPACTION_TRIGGER_COUNT", 99)

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    first_id = await mem.store_memory("original content about the login fix", "sess-l2")
    count_after_first = mem._session_write_counts.get("sess-l2", 0)

    # Patch the name in memory_module's namespace — that's what store_memory calls
    async def _fake_semantic_dup(memory, content, session, threshold, query_vec=None):
        return first_id

    monkeypatch.setattr(memory_module, "find_semantic_duplicate", _fake_semantic_dup)

    await mem.store_memory("similar content about the auth fix", "sess-l2")

    assert mem._session_write_counts.get("sess-l2", 0) == count_after_first + 1


# --- Trigger threshold ---

@pytest.mark.asyncio
async def test_counter_threshold_default_mode_is_5(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module
    import marm_mcp_server.config.settings as s

    assert s.COMPACTION_TRIGGER_COUNT == 5


@pytest.mark.asyncio
async def test_counter_threshold_set_to_20_for_swarm_preset():
    from marm_mcp_server.server import apply_runtime_preset
    from marm_mcp_server.core import memory as memory_module
    import marm_mcp_server.config.settings as s

    original = s.COMPACTION_TRIGGER_COUNT
    try:
        result = apply_runtime_preset(swarm=True)
        assert s.COMPACTION_TRIGGER_COUNT == 20
        assert memory_module.COMPACTION_TRIGGER_COUNT == 20
    finally:
        s.COMPACTION_TRIGGER_COUNT = original
        memory_module.COMPACTION_TRIGGER_COUNT = original


@pytest.mark.asyncio
async def test_counter_threshold_set_to_20_for_trusted_preset():
    from marm_mcp_server.server import apply_runtime_preset
    from marm_mcp_server.core import memory as memory_module
    import marm_mcp_server.config.settings as s

    original = s.COMPACTION_TRIGGER_COUNT
    try:
        apply_runtime_preset(trusted=True)
        assert s.COMPACTION_TRIGGER_COUNT == 20
        assert memory_module.COMPACTION_TRIGGER_COUNT == 20
    finally:
        s.COMPACTION_TRIGGER_COUNT = original
        memory_module.COMPACTION_TRIGGER_COUNT = original


@pytest.mark.asyncio
async def test_counter_threshold_set_to_20_for_custom_preset():
    from marm_mcp_server.server import apply_runtime_preset
    from marm_mcp_server.core import memory as memory_module
    import marm_mcp_server.config.settings as s

    original = s.COMPACTION_TRIGGER_COUNT
    try:
        apply_runtime_preset(rate_limit_rpm=100)
        assert s.COMPACTION_TRIGGER_COUNT == 20
        assert memory_module.COMPACTION_TRIGGER_COUNT == 20
    finally:
        s.COMPACTION_TRIGGER_COUNT = original
        memory_module.COMPACTION_TRIGGER_COUNT = original


# --- Trigger scheduling ---

@pytest.mark.asyncio
async def test_counter_resets_and_scan_scheduled_on_threshold(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module
    import marm_mcp_server.config.settings as s

    monkeypatch.setattr(memory_module, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(memory_module, "COMPACTION_TRIGGER_COUNT", 3)
    monkeypatch.setattr(s, "COMPACTION_ACTIVE_SESSION_GRACE_MINUTES", 60)  # won't fire in test

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("write 1", "sess-trigger")
    await mem.store_memory("write 2", "sess-trigger")
    assert mem._session_write_counts.get("sess-trigger") == 2

    await mem.store_memory("write 3", "sess-trigger")

    # Counter resets to 0 after threshold
    assert mem._session_write_counts.get("sess-trigger") == 0
    # A pending scan task was scheduled
    assert "sess-trigger" in mem._pending_compaction_scans
    task = mem._pending_compaction_scans["sess-trigger"]
    assert not task.done()
    task.cancel()


@pytest.mark.asyncio
async def test_new_write_cancels_pending_scan(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module
    import marm_mcp_server.config.settings as s

    monkeypatch.setattr(memory_module, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(memory_module, "COMPACTION_TRIGGER_COUNT", 2)
    monkeypatch.setattr(s, "COMPACTION_ACTIVE_SESSION_GRACE_MINUTES", 60)

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("write 1", "sess-cancel")
    await mem.store_memory("write 2", "sess-cancel")

    first_task = mem._pending_compaction_scans.get("sess-cancel")
    assert first_task is not None and not first_task.done()

    # New write arrives before the scan fires — must cancel the pending task
    await mem.store_memory("write 3", "sess-cancel")
    await asyncio.sleep(0)  # yield so the event loop can process the cancellation

    assert first_task.cancelled()


@pytest.mark.asyncio
async def test_different_sessions_have_independent_counters(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(memory_module, "COMPACTION_TRIGGER_COUNT", 99)

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("session-a write 1", "session-a")
    await mem.store_memory("session-a write 2", "session-a")
    await mem.store_memory("session-b write 1", "session-b")

    assert mem._session_write_counts.get("session-a") == 2
    assert mem._session_write_counts.get("session-b") == 1


@pytest.mark.asyncio
async def test_scan_fires_after_grace_period(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module
    import marm_mcp_server.config.settings as s
    import marm_mcp_server.core.compaction as compaction_module

    monkeypatch.setattr(memory_module, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(memory_module, "COMPACTION_TRIGGER_COUNT", 1)
    monkeypatch.setattr(s, "COMPACTION_ACTIVE_SESSION_GRACE_MINUTES", 0)

    scan_called = []

    def _fake_find_candidates(memory, session_name):
        scan_called.append(session_name)
        return []

    monkeypatch.setattr(compaction_module, "find_compaction_candidates", _fake_find_candidates)

    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("trigger write", "sess-fire")

    deadline = asyncio.get_running_loop().time() + 1.0
    while "sess-fire" not in scan_called and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)

    assert "sess-fire" in scan_called
