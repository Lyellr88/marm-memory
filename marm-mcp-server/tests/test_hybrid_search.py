import sqlite3

import numpy as np
import pytest

from marm_mcp_server.core.memory import (
    MARMMemory,
    _safe_fts_query,
)


# --- _safe_fts_query ---


def test_safe_fts_query_returns_none_for_empty_string():
    assert _safe_fts_query("") is None


def test_safe_fts_query_returns_none_for_punctuation_only():
    assert _safe_fts_query("---") is None
    assert _safe_fts_query("!!!") is None
    assert _safe_fts_query("@#$%") is None


def test_safe_fts_query_quotes_each_token_individually():
    result = _safe_fts_query("docker deployment command")
    assert result == '"docker" "deployment" "command"'


def test_safe_fts_query_strips_cli_flags():
    result = _safe_fts_query("--workers")
    assert result == '"workers"'


def test_safe_fts_query_strips_fts5_operators_from_input():
    result = _safe_fts_query("AND OR NOT NEAR")
    assert result == '"AND" "OR" "NOT" "NEAR"'


def test_safe_fts_query_strips_surrounding_quotes():
    result = _safe_fts_query('"quoted phrase"')
    assert result == '"quoted" "phrase"'


def test_safe_fts_query_preserves_underscore_tokens():
    # Underscores are \w — kept as-is so FTS5 porter tokenizer can split them
    result = _safe_fts_query("COMPACTION_TRIGGER_COUNT")
    assert result == '"COMPACTION_TRIGGER_COUNT"'


# --- FTS5 schema ---


@pytest.mark.asyncio
async def test_fts5_table_and_all_three_triggers_created_on_fresh_db(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    with memory.get_connection() as conn:
        object_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')"
            ).fetchall()
        }

    assert "memories_fts" in object_names
    assert "memories_ai" in object_names
    assert "memories_au" in object_names
    assert "memories_ad" in object_names


@pytest.mark.asyncio
async def test_fts5_trigger_indexes_new_memory_on_insert(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    await memory.store_memory(
        "COMPACTION_TRIGGER_COUNT controls write threshold", session="trigger-test"
    )

    with memory.get_connection() as conn:
        rows = conn.execute(
            "SELECT content FROM memories_fts "
            "WHERE memories_fts MATCH '\"COMPACTION_TRIGGER_COUNT\"'"
        ).fetchall()

    assert len(rows) >= 1
    assert "COMPACTION_TRIGGER_COUNT" in rows[0][0]


@pytest.mark.asyncio
async def test_fts5_backfill_repopulates_after_index_cleared(tmp_path):
    db_path = str(tmp_path / "memory.db")

    m1 = MARMMemory(db_path)
    m1._encoder_failed = True
    await m1.store_memory("backfill target content", session="backfill-test")

    # Verify FTS finds the memory before clearing
    with sqlite3.connect(db_path) as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH '\"backfill\"'"
        ).fetchone()[0]
    assert before >= 1

    # Properly clear the FTS index for a content table
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('delete-all')")
        gone = conn.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH '\"backfill\"'"
        ).fetchone()[0]
    assert gone == 0

    # Re-init via new instance — backfill runs and should re-populate FTS
    m2 = MARMMemory(db_path)
    m2._encoder_failed = True

    with m2.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH '\"backfill\"'"
        ).fetchone()[0]

    assert count >= 1


# --- recall_text_search ---


@pytest.mark.asyncio
async def test_recall_text_search_returns_bm25_score_not_hardcoded_0_8(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    await memory.store_memory("docker run port mapping deployment", session="s1")

    results = await memory.recall_text_search("docker", session="s1", limit=5)

    assert len(results) == 1
    assert results[0]["similarity"] != 0.8


@pytest.mark.asyncio
async def test_recall_text_search_single_exact_hit_scores_1_0(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    await memory.store_memory("unique canary phrase for scoring", session="single-hit")

    results = await memory.recall_text_search("unique", session="single-hit", limit=5)

    assert len(results) == 1
    assert results[0]["similarity"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_recall_text_search_falls_back_to_like_for_punctuation_only_query(
    tmp_path,
):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    # Content contains literal dashes — LIKE '%---%' will match it
    mem_id = await memory.store_memory(
        "content with --- dashes inside", session="fallback-test"
    )

    # _safe_fts_query("---") returns None — LIKE path must run and return the row
    results = await memory.recall_text_search("---", session="fallback-test", limit=5)

    assert len(results) >= 1
    assert any(r["id"] == mem_id for r in results)


@pytest.mark.asyncio
async def test_recall_text_search_falls_back_to_like_when_fts5_raises(
    monkeypatch, tmp_path
):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    mem_id = await memory.store_memory("fts error fallback content", session="fts-err")
    helper_called = {"value": False}

    def raise_operational_error(*args, **kwargs):
        helper_called["value"] = True
        raise sqlite3.OperationalError("no such table: memories_fts")

    monkeypatch.setitem(
        memory.recall_text_search.__func__.__globals__,
        "_fetch_and_score_fts_rows",
        raise_operational_error,
    )

    results = await memory.recall_text_search(
        "fts error fallback", session="fts-err", limit=5
    )

    assert len(results) >= 1
    assert helper_called["value"] is True
    assert any(r["id"] == mem_id for r in results)
    assert results[0]["content"] == "fts error fallback content"


@pytest.mark.asyncio
async def test_recall_text_search_session_filter_excludes_other_sessions(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    await memory.store_memory("shared keyword content", session="alpha")
    await memory.store_memory("shared keyword content", session="beta")

    results = await memory.recall_text_search("keyword", session="alpha", limit=5)

    assert results
    assert all(r["session_name"] == "alpha" for r in results)


# --- recall_similar hybrid merge ---


@pytest.mark.asyncio
async def test_recall_similar_response_shape_unchanged_with_hybrid_path(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    await memory.store_memory("response shape check content", session="shape-test")

    query_vec = np.zeros(384, dtype=np.float32)
    results = await memory.recall_similar(
        "response shape", session="shape-test", limit=5, query_vec=query_vec
    )

    assert isinstance(results, list)
    assert results
    required = {
        "id",
        "session_name",
        "content",
        "timestamp",
        "context_type",
        "metadata",
        "similarity",
    }
    assert required.issubset(results[0].keys())


@pytest.mark.asyncio
async def test_recall_similar_fts_only_hit_promoted_when_memory_has_no_embedding(
    tmp_path,
):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    # No embedding stored (encoder failed) — row only exists in FTS index
    mem_id = await memory.store_memory(
        "COMPACTION_TRIGGER_COUNT controls write threshold", session="fts-promo"
    )

    # Zero vector — no cosine matches; FTS5 should find and promote the row
    query_vec = np.zeros(384, dtype=np.float32)
    results = await memory.recall_similar(
        "COMPACTION_TRIGGER_COUNT", session="fts-promo", limit=5, query_vec=query_vec
    )

    assert any(r["id"] == mem_id for r in results)


@pytest.mark.asyncio
async def test_recall_similar_fts_only_score_is_in_valid_range(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    await memory.store_memory("hybrid scoring content test", session="hybrid-score")

    query_vec = np.zeros(384, dtype=np.float32)
    results = await memory.recall_similar(
        "hybrid scoring", session="hybrid-score", limit=5, query_vec=query_vec
    )

    for r in results:
        assert 0.0 < r["similarity"] <= 1.0


@pytest.mark.asyncio
async def test_recall_similar_fts_failure_degrades_gracefully_to_vector_only(
    monkeypatch, tmp_path
):
    from marm_mcp_server.core import memory as memory_module

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    await memory.store_memory("degradation test content", session="degrade")

    def raise_operational_error(*args, **kwargs):
        raise sqlite3.OperationalError("no such table: memories_fts")

    monkeypatch.setattr(
        memory_module, "_fetch_and_score_fts_rows", raise_operational_error
    )

    query_vec = np.zeros(384, dtype=np.float32)
    results = await memory.recall_similar(
        "degradation test", session="degrade", limit=5, query_vec=query_vec
    )

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_recall_similar_debug_logs_source_lane_breakdown(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = False

    vec_only_id = "vec-only"
    both_id = "both"
    fts_only_id = "fts-only"

    query_vec = np.zeros(384, dtype=np.float32)
    query_vec[0] = 1.0

    vector_rows = [
        (
            {
                "id": vec_only_id,
                "session_name": "debug-lanes",
                "content": "vector only memory",
                "timestamp": "2026-01-01T00:00:01Z",
                "context_type": "general",
                "metadata": "{}",
            },
            0.9,
        ),
        (
            {
                "id": both_id,
                "session_name": "debug-lanes",
                "content": "shared keyword memory",
                "timestamp": "2026-01-01T00:00:02Z",
                "context_type": "general",
                "metadata": "{}",
            },
            0.8,
        ),
    ]

    fts_rows = [
        (
            {
                "id": both_id,
                "session_name": "debug-lanes",
                "content": "shared keyword memory",
                "timestamp": "2026-01-01T00:00:02Z",
                "context_type": "general",
                "metadata": "{}",
            },
            0.9,
        ),
        (
            {
                "id": fts_only_id,
                "session_name": "debug-lanes",
                "content": "shared keyword no embedding",
                "timestamp": "2026-01-01T00:00:03Z",
                "context_type": "general",
                "metadata": "{}",
            },
            0.7,
        ),
    ]

    monkeypatch.setattr(memory_module, "_RECALL_DEBUG", True)
    monkeypatch.setitem(
        memory.recall_similar.__func__.__globals__,
        "_fetch_and_score_embedding_rows",
        lambda *_: (vector_rows, 0, False),
    )
    monkeypatch.setitem(
        memory.recall_similar.__func__.__globals__,
        "_fetch_and_score_fts_rows",
        lambda *_: fts_rows,
    )

    debug_lines: list[str] = []
    monkeypatch.setattr(memory_module, "_safe_print", debug_lines.append)

    results = await memory.recall_similar(
        "shared keyword",
        session="debug-lanes",
        limit=5,
        query_vec=query_vec,
    )

    assert {r["id"] for r in results} == {vec_only_id, both_id, fts_only_id}
    assert any(
        "candidates: 3 total | vec+fts=1, vec-only=1, fts-only=1" in line
        for line in debug_lines
    )
