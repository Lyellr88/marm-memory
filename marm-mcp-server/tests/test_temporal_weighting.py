from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import marm_mcp_server.core.memory_recall as memory_recall_module
from marm_mcp_server.core.memory import MARMMemory, _temporal_score

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
    # Build from UTC, then strip tzinfo to model a legacy naive timestamp.
    ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
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
    monkeypatch.setattr(memory_recall_module, "TEMPORAL_WEIGHT", 0.0)
    monkeypatch.setattr(memory_recall_module, "HYBRID_SEARCH_TEXT_WEIGHT", 0.05)

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

    # Give the older memory the lexical advantage below.
    old_id = _insert(
        (base - timedelta(days=90)).isoformat(),
        "zephyr unique keyword only here",
    )
    # The newer memory has identical vector similarity.
    new_id = _insert(
        base.isoformat(), "unrelated content about something else entirely"
    )
    monkeypatch.setattr(
        memory_recall_module,
        "_fetch_fts_candidate_ids",
        lambda *_args, **_kwargs: [(old_id, 1.0), (new_id, 0.0)],
    )

    results = await mem.recall_similar(
        "zephyr unique keyword",
        session="zero-weight",
        limit=5,
        query_vec=unit_vec.copy(),
    )

    ids = [r["id"] for r in results]
    assert ids == [old_id, new_id], (
        "At TEMPORAL_WEIGHT=0 the FTS-dominant old memory should rank above "
        "the newer candidate"
    )


@pytest.mark.asyncio
async def test_text_search_fallback_applies_temporal_but_exact_lane_does_not(tmp_path):
    """When the encoder is unavailable, semantic-intent recall falls back to text
    search WITH temporal decay so newer wins. The exact lane must NOT be reordered
    by age -- identical lexical hits keep BM25 (insertion) order."""
    import sqlite3 as _sqlite3
    import uuid

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True  # forces the text-search fallback path

    base = datetime.now(timezone.utc)

    def _insert(ts):
        mid = str(uuid.uuid4())
        with _sqlite3.connect(str(tmp_path / "memory.db")) as conn:
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp, context_type, metadata) "
                "VALUES (?, 'fallback-temporal', 'temporal keyword content', ?, 'general', '{}')",
                (mid, ts),
            )
            conn.execute(
                "INSERT INTO memories_fts(rowid, content) "
                "SELECT rowid, content FROM memories WHERE id = ?",
                (mid,),
            )
        return mid

    old_id = _insert((base - timedelta(days=120)).isoformat())
    new_id = _insert(base.isoformat())

    # Natural-language query -> auto lane -> encoder unavailable -> temporal fallback
    semantic = await mem.recall_similar(
        "temporal keyword content", session="fallback-temporal", limit=5
    )
    sem_ids = [r["id"] for r in semantic]
    assert sem_ids.index(new_id) < sem_ids.index(old_id), (
        "semantic-intent fallback must rank the newer memory first"
    )

    assert {result["retrieval_mode"] for result in semantic} == {
        "semantic_fallback_fts"
    }

    # Exact lane preserves lexical scores rather than applying temporal decay.
    exact = await mem.recall_similar(
        "temporal keyword content",
        session="fallback-temporal",
        limit=5,
        exact_mode="exact",
    )
    exact_by_id = {result["id"]: result for result in exact}
    assert {result["retrieval_mode"] for result in exact} == {"exact_fts"}
    assert exact_by_id[old_id]["similarity"] == exact_by_id[new_id]["similarity"]


@pytest.mark.asyncio
async def test_temporal_fallback_promotes_newer_result_outside_bm25_limit(tmp_path):
    """With limit=1 on the temporal fallback lane, a newer result ranked just
    outside the top-1 BM25 row must still be promoted. This fails if the lane
    fetches only `limit` BM25 rows before re-ranking, so it guards the widened
    candidate pool."""
    import sqlite3 as _sqlite3
    import uuid

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True  # forces the text-search fallback path

    base = datetime.now(timezone.utc)

    def _insert(ts):
        mid = str(uuid.uuid4())
        with _sqlite3.connect(str(tmp_path / "memory.db")) as conn:
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp, context_type, metadata) "
                "VALUES (?, 'limit-cutoff', 'temporal keyword content', ?, 'general', '{}')",
                (mid, ts),
            )
            conn.execute(
                "INSERT INTO memories_fts(rowid, content) "
                "SELECT rowid, content FROM memories WHERE id = ?",
                (mid,),
            )
        return mid

    # Identical content -> identical BM25. Old is inserted first, so it is the
    # single row a limit=1 BM25 fetch would return; new sits just outside it.
    _insert((base - timedelta(days=120)).isoformat())
    new_id = _insert(base.isoformat())

    results = await mem.recall_similar(
        "temporal keyword content", session="limit-cutoff", limit=1
    )

    assert len(results) == 1
    assert results[0]["id"] == new_id, (
        "temporal fallback must promote the newer row from outside the BM25 limit cutoff"
    )
