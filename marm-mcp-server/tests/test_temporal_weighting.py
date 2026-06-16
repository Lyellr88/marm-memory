from datetime import datetime, timezone, timedelta

import numpy as np
import pytest

from marm_mcp_server.core.memory import MARMMemory, _temporal_score
import marm_mcp_server.core.memory_ops as memory_ops_module


# --- _temporal_score unit tests ---


def test_temporal_score_brand_new_is_close_to_1():
    ts = datetime.now(timezone.utc).isoformat()
    assert _temporal_score(ts, 30) > 0.99


def test_temporal_score_at_half_life_is_close_to_0_5():
    ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert abs(_temporal_score(ts, 30) - 0.5) < 0.02


def test_temporal_score_old_memory_is_low():
    ts = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
    score = _temporal_score(ts, 30)
    assert score < 0.1


def test_temporal_score_bad_timestamp_returns_neutral():
    assert _temporal_score("not-a-date", 30) == 0.5
    assert _temporal_score("", 30) == 0.5


def test_temporal_score_naive_timestamp_treated_as_utc():
    ts = datetime.now().replace(tzinfo=None).isoformat()
    assert _temporal_score(ts, 30) > 0.99


def test_temporal_score_monotonically_decreases_with_age():
    base = datetime.now(timezone.utc)
    scores = [
        _temporal_score((base - timedelta(days=d)).isoformat(), 30)
        for d in [0, 7, 30, 90, 365]
    ]
    assert scores == sorted(scores, reverse=True)


# --- recall_similar temporal re-ranking ---


@pytest.mark.asyncio
async def test_newer_memory_ranks_above_equally_similar_older_one(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()

    import sqlite3 as _sqlite3
    import uuid

    unit_vec = np.ones(384, dtype=np.float32)
    unit_vec /= np.linalg.norm(unit_vec)

    _ = mem  # triggers init_database via __init__

    def _insert(ts):
        mid = str(uuid.uuid4())
        with _sqlite3.connect(str(tmp_path / "memory.db")) as conn:
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp, context_type, metadata, embedding) "
                "VALUES (?, 'rank-test', 'temporal ranking keyword content', ?, 'general', '{}', ?)",
                (mid, ts, unit_vec.tobytes()),
            )
            conn.execute(
                "INSERT INTO memories_fts(rowid, content) "
                "SELECT rowid, content FROM memories WHERE id = ?",
                (mid,),
            )
        return mid

    old_id = _insert(old_ts)
    new_id = _insert(new_ts)

    results = await mem.recall_similar(
        "temporal ranking keyword",
        session="rank-test",
        limit=5,
        query_vec=unit_vec.copy(),
    )

    ids = [r["id"] for r in results]
    assert new_id in ids
    assert old_id in ids
    assert ids.index(new_id) < ids.index(old_id)


@pytest.mark.asyncio
async def test_temporal_weight_zero_means_fts_winner_ranks_first_despite_age(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(memory_ops_module, "TEMPORAL_WEIGHT", 0.0)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    import sqlite3 as _sqlite3
    import uuid

    base = datetime.now(timezone.utc)

    unit_vec = np.ones(384, dtype=np.float32)
    unit_vec /= np.linalg.norm(unit_vec)

    _ = mem  # triggers init_database via __init__

    def _insert(ts, content):
        mid = str(uuid.uuid4())
        with _sqlite3.connect(str(tmp_path / "memory.db")) as conn:
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp, context_type, metadata, embedding) "
                "VALUES (?, 'zero-weight', ?, ?, 'general', '{}', ?)",
                (mid, content, ts, unit_vec.tobytes()),
            )
            conn.execute(
                "INSERT INTO memories_fts(rowid, content) "
                "SELECT rowid, content FROM memories WHERE id = ?",
                (mid,),
            )
        return mid

    # Old memory has the exact query keyword — FTS filter will include it
    old_id = _insert(
        (base - timedelta(days=90)).isoformat(),
        "zephyr unique keyword only here",
    )
    # New memory has no match for the query — FTS filter will exclude it
    new_id = _insert(
        base.isoformat(), "unrelated content about something else entirely"
    )

    results = await mem.recall_similar(
        "zephyr unique keyword",
        session="zero-weight",
        limit=5,
        query_vec=unit_vec.copy(),
    )

    ids = [r["id"] for r in results]
    assert old_id in ids, "FTS-matching old memory must appear in results"
    # With TEMPORAL_WEIGHT=0, only vec_score determines rank. If new_id also surfaced
    # (e.g. via semantic fallback), old_id must still rank first.
    if new_id in ids:
        assert ids.index(old_id) < ids.index(new_id), (
            "At TEMPORAL_WEIGHT=0 the FTS-dominant old memory should rank above the new non-matching one"
        )
