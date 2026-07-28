import os
import pathlib
import sqlite3
import sys
import uuid as _uuid_module
from datetime import datetime, timezone as _timezone

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


# --- _wide_fts_query (semantic lane) ---
#
# The strict builder above is the exact/lexical lane and must stay unchanged; the
# assertions in this block cover the widened semantic-lane builder only.


def _wide(query, mode="or_nostop", stopwords=None):
    """Call _wide_fts_query with a pinned mode, since it reads module-level config."""
    from marm_mcp_server.core import memory_utils

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(memory_utils, "FTS_QUERY_MODE", mode)
        if stopwords is not None:
            mp.setattr(memory_utils, "_FTS_STOPWORDS", frozenset(stopwords))
        return memory_utils._wide_fts_query(query)


def test_wide_fts_query_ors_tokens_and_drops_stopwords():
    # The regression this fix exists for: six AND-ed tokens matched nothing.
    assert _wide("What pet does the speaker have?") == '"pet" OR "speaker"'


def test_wide_fts_query_quotes_every_token_to_neutralize_fts5_operators():
    # Quoting is a safety control: unquoted NEAR/OR/* would be parsed as syntax.
    result = _wide("config NEAR value", stopwords=set())
    assert result == '"config" OR "NEAR" OR "value"'


def test_wide_fts_query_drops_stopwords_case_insensitively():
    assert _wide("The THE tHe cat") == '"cat"'


def test_wide_fts_query_returns_none_when_only_stopwords_remain():
    # Routes to pure semantic recall instead of OR-ing filler against every row.
    assert _wide("what is the") is None
    assert _wide("how do you do it") is None


def test_wide_fts_query_returns_none_for_empty_and_punctuation():
    # Parity with _safe_fts_query so callers' fail-open path is unchanged.
    assert _wide("") is None
    assert _wide("---") is None
    assert _wide("@#$%") is None


def test_wide_fts_query_and_mode_matches_strict_builder_exactly():
    query = "docker deployment command"
    assert _wide(query, mode="and") == _safe_fts_query(query)


def test_wide_fts_query_or_mode_keeps_stopwords():
    assert _wide("the cat", mode="or") == '"the" OR "cat"'


def test_wide_fts_query_honors_extra_stopwords():
    assert _wide("docker deployment", stopwords={"docker"}) == '"deployment"'


def test_wide_fts_query_single_token_has_no_or_operator():
    assert _wide("deployment") == '"deployment"'


def test_wide_fts_query_keeps_words_that_double_as_content():
    """The FTS5 tokenizer is case-insensitive, so a stopword entry also discards
    its proper-noun or content twin -- "May" the month, "US" the country, "won"
    the verb. Dropping those left queries with only a generic term, and because
    any match at all suppresses the full semantic scan, the relevant memory
    became unreachable rather than merely lower-ranked.
    """
    from marm_mcp_server.core import memory_utils

    for word in ("may", "will", "us", "won", "can", "get", "need", "know", "said"):
        assert word not in memory_utils._FTS_BASE_STOPWORDS, (
            f"{word!r} has a content sense; listing it discards that meaning "
            "for every query, since FTS5 matching is case-insensitive"
        )

    assert _wide("What happened in May?") == '"happened" OR "May"'
    assert _wide("Will the US ship it?") == '"Will" OR "US" OR "ship"'
    assert _wide("Who won the game?") == '"won" OR "game"'


def test_fts_query_mode_rejects_invalid_values(monkeypatch):
    """An unrecognized FTS_QUERY_MODE falls back to the default instead of
    reaching the query builder and producing invalid FTS5 syntax."""
    from marm_mcp_server.config.settings import FTS_QUERY_MODES, _safe_choice

    monkeypatch.setenv("FTS_QUERY_MODE", "nonsense")
    assert _safe_choice("FTS_QUERY_MODE", "or_nostop", FTS_QUERY_MODES) == "or_nostop"

    # Valid values pass through, case- and whitespace-insensitively.
    monkeypatch.setenv("FTS_QUERY_MODE", "  AND  ")
    assert _safe_choice("FTS_QUERY_MODE", "or_nostop", FTS_QUERY_MODES) == "and"

    monkeypatch.delenv("FTS_QUERY_MODE")
    assert _safe_choice("FTS_QUERY_MODE", "or_nostop", FTS_QUERY_MODES) == "or_nostop"


def test_extra_stopwords_parsing(monkeypatch):
    """FTS_EXTRA_STOPWORDS is comma-separated, lowercased, and blank-tolerant."""
    from marm_mcp_server.config.settings import _csv_frozenset

    monkeypatch.setenv("FTS_EXTRA_STOPWORDS", " Docker ,, DEPLOY ,")
    assert _csv_frozenset("FTS_EXTRA_STOPWORDS") == {"docker", "deploy"}

    monkeypatch.setenv("FTS_EXTRA_STOPWORDS", "")
    assert _csv_frozenset("FTS_EXTRA_STOPWORDS") == frozenset()


def test_hybrid_search_text_weight_default_is_the_swept_value():
    """The weight is the one number this whole change exists to establish.

    0.05 came from a LoCoMo sweep over 0.00-0.50 where any-hit peaked in a broad
    0.04-0.08 plateau, well above both 0.0 (lexical scoring off) and the old
    unvalidated 0.35. Guards against a silent drift back to either.
    """
    from marm_mcp_server.config import settings

    if "HYBRID_SEARCH_TEXT_WEIGHT" in os.environ:
        pytest.skip(
            "environment pins HYBRID_SEARCH_TEXT_WEIGHT; default not observable"
        )
    assert settings.HYBRID_SEARCH_TEXT_WEIGHT == 0.05


def test_fts_candidate_limit_default_is_the_swept_value():
    """200 was chosen to recover the multi-hop recall that v2.31.0's 50-candidate
    pool cost. Below ~200 multi-hop drops; far above it the pool stops acting as
    a precision gate and the adversarial gain erodes."""
    from marm_mcp_server.config import settings

    if "FTS_CANDIDATE_LIMIT" in os.environ:
        pytest.skip("environment pins FTS_CANDIDATE_LIMIT; default not observable")
    assert settings.FTS_CANDIDATE_LIMIT == 200


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
async def test_semantic_fallback_like_marks_its_retrieval_mode(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    mem_id = await memory.store_memory(
        "content with --- dashes inside", session="semantic-like"
    )

    results = await memory.recall_similar(
        "---", session="semantic-like", limit=5, exact_mode="semantic"
    )

    assert any(result["id"] == mem_id for result in results)
    assert {result["retrieval_mode"] for result in results} == {
        "semantic_fallback_like"
    }


@pytest.mark.asyncio
async def test_recall_text_search_falls_back_to_like_when_fts5_raises(
    monkeypatch, tmp_path
):
    from marm_mcp_server.core.memory import MARMMemory

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    mem_id = await memory.store_memory("fts error fallback content", session="fts-err")
    helper_called = {"value": False}

    def raise_operational_error(*args, **kwargs):
        helper_called["value"] = True
        raise sqlite3.OperationalError("no such table: memories_fts")

    from marm_mcp_server.core import memory_recall as memory_recall_module

    monkeypatch.setattr(
        memory_recall_module, "_fetch_and_score_fts_rows", raise_operational_error
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


# --- recall_similar filter->rerank ---


def _insert_with_embedding(conn, session: str, content: str, vec: np.ndarray) -> str:
    """Insert a memory row directly with a pre-built embedding. Returns the memory ID."""
    mem_id = str(_uuid_module.uuid4())
    content_hash = f"{hash(content + mem_id)}"
    ts = datetime.now(_timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO memories"
        " (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata)"
        " VALUES (?, ?, ?, ?, ?, ?, 'general', '{}')",
        (mem_id, session, content, vec.tobytes(), content_hash, ts),
    )
    return mem_id


@pytest.mark.asyncio
async def test_recall_similar_response_shape_unchanged_with_filter_rerank(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with memory.get_connection() as conn:
        _insert_with_embedding(conn, "shape-test", "response shape check content", vec)

    results = await memory.recall_similar(
        "response shape", session="shape-test", limit=5, query_vec=vec.copy()
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
async def test_recall_similar_filter_rerank_surfaces_keyword_matching_memory(tmp_path):
    """FTS filter should surface the keyword-matching memory and rerank by embedding."""
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with memory.get_connection() as conn:
        target_id = _insert_with_embedding(
            conn, "fts-rerank", "docker deployment config", vec
        )
        _insert_with_embedding(conn, "fts-rerank", "unrelated content here", vec)

    results = await memory.recall_similar(
        "docker", session="fts-rerank", limit=5, query_vec=vec.copy()
    )

    assert any(r["id"] == target_id for r in results)


@pytest.mark.asyncio
async def test_recall_similar_memory_without_embedding_excluded_from_results(tmp_path):
    """Memories matching FTS but lacking an embedding cannot appear in results."""
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    no_embed_id = await memory.store_memory(
        "COMPACTION_TRIGGER_COUNT controls write threshold", session="no-embed-test"
    )

    query_vec = np.zeros(384, dtype=np.float32)
    results = await memory.recall_similar(
        "COMPACTION_TRIGGER_COUNT",
        session="no-embed-test",
        limit=5,
        query_vec=query_vec,
        exact_mode="semantic",
    )

    assert no_embed_id not in {r["id"] for r in results}


@pytest.mark.asyncio
async def test_recall_similar_similarity_scores_in_valid_range(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with memory.get_connection() as conn:
        _insert_with_embedding(conn, "score-range", "hybrid scoring content test", vec)

    results = await memory.recall_similar(
        "hybrid scoring", session="score-range", limit=5, query_vec=vec.copy()
    )

    assert results
    for r in results:
        assert 0.0 < r["similarity"] <= 1.0 + 1e-4


@pytest.mark.asyncio
async def test_recall_similar_falls_back_to_semantic_scan_when_fts_returns_no_candidates(
    monkeypatch, tmp_path
):
    """Semantic fallback must return results when FTS finds no candidates."""
    from marm_mcp_server.core import memory_recall as memory_recall_module

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with memory.get_connection() as conn:
        embed_id = _insert_with_embedding(
            conn, "fallback-test", "semantic fallback content", vec
        )

    monkeypatch.setattr(memory_recall_module, "_fetch_fts_candidate_ids", lambda *_: [])

    results = await memory.recall_similar(
        "fallback content", session="fallback-test", limit=5, query_vec=vec.copy()
    )

    assert any(r["id"] == embed_id for r in results)


@pytest.mark.asyncio
async def test_recall_similar_falls_back_when_fts_candidates_have_no_embeddings(
    monkeypatch, tmp_path
):
    """When FTS candidates exist but none are scoreable, semantic fallback must run."""
    from marm_mcp_server.core import memory_recall as memory_recall_module

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with memory.get_connection() as conn:
        embed_id = _insert_with_embedding(
            conn, "embed-fallback", "semantic content here", vec
        )

    # Return a non-existent ID so ID-bounded fetch finds nothing scoreable
    monkeypatch.setattr(
        memory_recall_module,
        "_fetch_fts_candidate_ids",
        lambda *_: [("non-existent-id", 1.0)],
    )

    results = await memory.recall_similar(
        "semantic content", session="embed-fallback", limit=5, query_vec=vec.copy()
    )

    assert any(r["id"] == embed_id for r in results)


@pytest.mark.asyncio
async def test_recall_similar_falls_back_when_fts_candidates_are_all_wrong_dimension(
    monkeypatch, tmp_path
):
    """When FTS returns a real ID whose embedding has the wrong dimension, all candidates
    are dimension-skipped, similarities is empty, and semantic fallback must run."""
    from marm_mcp_server.core import memory_recall as memory_recall_module

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    correct_dim = 384
    wrong_dim = 768

    correct_vec = np.ones(correct_dim, dtype=np.float32)
    correct_vec /= np.linalg.norm(correct_vec)
    wrong_vec = np.ones(wrong_dim, dtype=np.float32)
    wrong_vec /= np.linalg.norm(wrong_vec)

    with mem.get_connection() as conn:
        # Wrong-dim row: FTS will be forced to return this ID
        wrong_id = _insert_with_embedding(
            conn, "dim-fallback", "dimension mismatch content", wrong_vec
        )
        # Correct-dim row: semantic fallback should find this
        correct_id = _insert_with_embedding(
            conn, "dim-fallback", "dimension correct content", correct_vec
        )

    # Force FTS to return only the wrong-dimension ID
    monkeypatch.setattr(
        memory_recall_module, "_fetch_fts_candidate_ids", lambda *_: [(wrong_id, 1.0)]
    )

    query_vec = correct_vec.copy()
    results = await mem.recall_similar(
        "dimension content", session="dim-fallback", limit=5, query_vec=query_vec
    )

    result_ids = {r["id"] for r in results}
    assert wrong_id not in result_ids, "wrong-dimension FTS candidate must be skipped"
    assert correct_id in result_ids, (
        "semantic fallback must surface the correct-dimension memory"
    )


@pytest.mark.asyncio
async def test_recall_similar_respects_fts_candidate_limit(monkeypatch, tmp_path):
    """Scorer receives no more than max(limit, FTS_CANDIDATE_LIMIT) IDs."""
    from marm_mcp_server.core import memory_recall as memory_recall_module

    cap = 3
    recall_limit = 5
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with mem.get_connection() as conn:
        for i in range(10):
            _insert_with_embedding(conn, "cap-test", f"canary memory entry {i}", vec)

    scored_ids: list[str] = []
    original_scorer = memory_recall_module._fetch_and_score_by_ids

    def capturing_scorer(db_path, memory_ids, query_embedding):
        scored_ids.extend(memory_ids)
        return original_scorer(db_path, memory_ids, query_embedding)

    monkeypatch.setattr(memory_recall_module, "FTS_CANDIDATE_LIMIT", cap)
    monkeypatch.setattr(
        memory_recall_module, "_fetch_and_score_by_ids", capturing_scorer
    )

    await mem.recall_similar(
        "canary", session="cap-test", limit=recall_limit, query_vec=vec.copy()
    )

    expected_ceiling = max(recall_limit, cap)
    assert len(scored_ids) <= expected_ceiling, (
        f"scorer received {len(scored_ids)} IDs but ceiling is max({recall_limit}, {cap})={expected_ceiling}"
    )


@pytest.mark.asyncio
async def test_recall_similar_fts_filter_failure_falls_back_to_semantic_scan(
    monkeypatch, tmp_path
):
    """An exception from _fetch_fts_candidate_ids must not crash recall."""
    from marm_mcp_server.core import memory_recall as memory_recall_module

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with memory.get_connection() as conn:
        embed_id = _insert_with_embedding(
            conn, "fts-fail", "content for fts failure test", vec
        )

    def raise_fts_error(*args, **kwargs):
        raise sqlite3.OperationalError("no such table: memories_fts")

    monkeypatch.setattr(
        memory_recall_module, "_fetch_fts_candidate_ids", raise_fts_error
    )

    results = await memory.recall_similar(
        "content", session="fts-fail", limit=5, query_vec=vec.copy()
    )

    assert isinstance(results, list)
    assert any(r["id"] == embed_id for r in results)


@pytest.mark.asyncio
async def test_recall_similar_scan_metadata_false_on_filter_rerank_path(tmp_path):
    """scan_truncated must be False when filter->rerank handles the query."""
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with memory.get_connection() as conn:
        _insert_with_embedding(conn, "meta-rerank", "docker deployment content", vec)

    _results, meta = await memory.recall_similar(
        "docker",
        session="meta-rerank",
        limit=5,
        query_vec=vec.copy(),
        include_scan_metadata=True,
    )

    assert meta["recall_scan_truncated"] is False


@pytest.mark.asyncio
async def test_recall_similar_debug_logs_filter_rerank_path(monkeypatch, tmp_path):
    """Debug output must identify the filter->rerank path when FTS finds scoreable candidates."""
    from marm_mcp_server.core.memory import MARMMemory

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with mem.get_connection() as conn:
        embed_id = _insert_with_embedding(
            conn, "debug-rerank", "docker deployment debug", vec
        )

    from marm_mcp_server.core import memory_recall as memory_recall_module

    debug_calls: list[str] = []
    monkeypatch.setattr(memory_recall_module, "_recall_debug", debug_calls.append)
    monkeypatch.setattr(
        memory_recall_module, "_fetch_fts_candidate_ids", lambda *_: [(embed_id, 1.0)]
    )

    await mem.recall_similar(
        "docker", session="debug-rerank", limit=5, query_vec=vec.copy()
    )

    assert any("filter->rerank" in msg for msg in debug_calls)


@pytest.mark.asyncio
async def test_recall_similar_debug_logs_semantic_fallback_path(monkeypatch, tmp_path):
    """Debug output must identify the semantic fallback path when FTS finds no candidates."""
    from marm_mcp_server.core.memory import MARMMemory

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with mem.get_connection() as conn:
        _insert_with_embedding(
            conn, "debug-fallback", "semantic fallback debug content", vec
        )

    from marm_mcp_server.core import memory_recall as memory_recall_module

    debug_calls: list[str] = []
    monkeypatch.setattr(memory_recall_module, "_recall_debug", debug_calls.append)
    monkeypatch.setattr(memory_recall_module, "_fetch_fts_candidate_ids", lambda *_: [])

    await mem.recall_similar(
        "fallback debug", session="debug-fallback", limit=5, query_vec=vec.copy()
    )

    assert any("semantic fallback" in msg for msg in debug_calls)


@pytest.mark.asyncio
async def test_recall_similar_fuses_bm25_into_ranking(monkeypatch, tmp_path):
    """Two candidates with identical embeddings must be ordered by their BM25
    score, proving the lexical signal is fused into the blend rather than
    discarded after the FTS filter."""
    from marm_mcp_server.core import memory_recall as memory_recall_module

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with memory.get_connection() as conn:
        strong_id = _insert_with_embedding(conn, "fuse", "docker deployment", vec)
        weak_id = _insert_with_embedding(conn, "fuse", "docker sidebar", vec)

    # The shipped 0.05 weight is deliberately small. This test covers the fusion
    # mechanism itself, so it pins a larger non-zero weight rather than depending
    # on the shipped default.
    monkeypatch.setattr(memory_recall_module, "HYBRID_SEARCH_TEXT_WEIGHT", 0.35)

    # Identical embeddings -> identical vec_score. Only the BM25 term differs,
    # so any ordering must come from lexical fusion.
    monkeypatch.setattr(
        memory_recall_module,
        "_fetch_fts_candidate_ids",
        lambda *_: [(strong_id, 1.0), (weak_id, 0.0)],
    )

    results = await memory.recall_similar(
        "docker", session="fuse", limit=5, query_vec=vec.copy()
    )
    ids = [r["id"] for r in results]

    assert ids.index(strong_id) < ids.index(weak_id)
    strong_sim = results[ids.index(strong_id)]["similarity"]
    weak_sim = results[ids.index(weak_id)]["similarity"]
    assert strong_sim > weak_sim


def test_normalize_bm25_maps_more_negative_to_higher_score():
    """BM25 is more-negative = better, so normalization must invert: the most
    negative raw score becomes 1.0 and the least negative becomes 0.0."""
    from marm_mcp_server.core.memory_scoring import _normalize_bm25

    assert _normalize_bm25([-5.0, -3.0, -1.0]) == [1.0, 0.5, 0.0]
    assert _normalize_bm25([-2.0]) == [1.0]
    assert _normalize_bm25([]) == []
    # All-equal scores collapse to 1.0 so a lone lexical hit keeps full weight.
    assert _normalize_bm25([-2.0, -2.0]) == [1.0, 1.0]


def test_normalize_bm25_lone_hit_score_covers_both_degenerate_shapes():
    """`lone_hit_score` must apply to every set min-max cannot normalize.

    Both a single row and a multi-row set where every score ties are degenerate:
    there is no spread, so the caller's value is used verbatim. The all-equal
    shape is the one easily missed -- a wide OR query where several memories hit
    the same number of terms lands there, not on the single-row branch.
    """
    from marm_mcp_server.core.memory_scoring import _normalize_bm25

    assert _normalize_bm25([-2.0], lone_hit_score=0.3) == [0.3]
    assert _normalize_bm25([-2.0, -2.0, -2.0], lone_hit_score=0.3) == [0.3, 0.3, 0.3]
    assert _normalize_bm25([], lone_hit_score=0.3) == []
    # Zero is a real choice (ignore the lexical signal entirely), not "unset".
    assert _normalize_bm25([-2.0], lone_hit_score=0.0) == [0.0]


def test_normalize_bm25_lone_hit_score_ignored_when_spread_exists():
    """A set with real spread must normalize identically regardless of the
    parameter. Guards against the value leaking into the non-degenerate math."""
    from marm_mcp_server.core.memory_scoring import _normalize_bm25

    assert _normalize_bm25([-5.0, -3.0, -1.0], lone_hit_score=0.0) == [1.0, 0.5, 0.0]


def test_lone_hit_score_applies_to_semantic_lane_but_not_exact_lane(
    tmp_path, monkeypatch
):
    """The two lanes must diverge on the same degenerate result set.

    One memory matches, so both fetchers see a single row and take the
    degenerate branch. The semantic lane's pool comes from a wide OR where a
    lone hit means one term matched, so it gets FTS_LONE_HIT_SCORE. The exact
    lane's strict AND means a lone hit contained every term, so it keeps 1.0.
    Asserting both against one real FTS5 index is what proves the wiring went
    to the right call site.
    """
    from marm_mcp_server.core import memory_scoring

    vec = np.ones(384, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    with memory.get_connection() as conn:
        only_id = _insert_with_embedding(
            conn, "lone", "The quarterly budget was approved.", vec
        )
        _insert_with_embedding(conn, "lone", "Unrelated note about weather.", vec)

    monkeypatch.setattr(memory_scoring, "FTS_LONE_HIT_SCORE", 0.25)

    pairs = memory_scoring._fetch_fts_candidate_ids(
        memory.db_path, "lone", '"budget"', 50
    )
    assert pairs == [(only_id, 0.25)]

    exact = memory_scoring._fetch_and_score_fts_rows(
        memory.db_path, "lone", '"budget"', 50
    )
    assert [score for _, score in exact] == [1.0]


def test_tied_bm25_candidates_cut_off_deterministically(tmp_path):
    """The candidate pool must not depend on SQLite's incidental row order.

    BM25 ties at the LIMIT boundary are the common case, not an edge case: 53.7%
    of LoCoMo queries had one at the 50-row cutoff. Without a tiebreak, which
    candidates entered the pool varied between processes, and identical
    benchmark configs scored up to 0.5pp apart -- larger than several of the
    effects the pool is used to measure.

    Six identical documents tie exactly, so only the ORDER BY tiebreak decides
    which three survive a LIMIT 3. They are inserted in scrambled id order, so a
    fetcher relying on scan order would return the insertion-order prefix
    instead of the id-sorted one.
    """
    from marm_mcp_server.core.memory_scoring import (
        _fetch_and_score_fts_rows,
        _fetch_fts_candidate_ids,
    )

    vec = np.ones(384, dtype=np.float32)
    vec /= np.linalg.norm(vec)
    insertion_order = ["id-5", "id-2", "id-6", "id-1", "id-4", "id-3"]

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True
    with memory.get_connection() as conn:
        for mem_id in insertion_order:
            conn.execute(
                "INSERT INTO memories"
                " (id, session_name, content, embedding, content_hash, timestamp,"
                "  context_type, metadata)"
                " VALUES (?, 'tie', 'tiebreak marker', ?, ?, ?, 'general', '{}')",
                (
                    mem_id,
                    vec.tobytes(),
                    f"hash-{mem_id}",
                    datetime.now(_timezone.utc).isoformat(),
                ),
            )

    pairs = _fetch_fts_candidate_ids(memory.db_path, "tie", '"marker"', 3)
    assert [cid for cid, _ in pairs] == ["id-1", "id-2", "id-3"]

    rows = _fetch_and_score_fts_rows(memory.db_path, "tie", '"marker"', 3)
    assert [row["id"] for row, _ in rows] == ["id-1", "id-2", "id-3"]


def test_fts_lone_hit_score_clamped_to_unit_range(monkeypatch, capsys):
    """Out-of-range values clamp rather than propagate an invalid weight into ranking.

    Exercises `_safe_unit_float`, the helper `FTS_LONE_HIT_SCORE` is actually
    built from, so the parse, the clamp, and the warning are all covered by the
    real code path. Reloading `settings` would be the other way to reach the
    constant itself, but it raises ImportError once another test in the suite has
    evicted the module, which is why the clamp lives in a callable helper.
    """
    from marm_mcp_server.config.settings import _safe_unit_float

    monkeypatch.setenv("FTS_LONE_HIT_SCORE", "2.5")
    assert _safe_unit_float("FTS_LONE_HIT_SCORE", 1.0) == 1.0
    assert "out of [0, 1], clamped to 1.0" in capsys.readouterr().err

    monkeypatch.setenv("FTS_LONE_HIT_SCORE", "-1")
    assert _safe_unit_float("FTS_LONE_HIT_SCORE", 1.0) == 0.0
    assert "out of [0, 1], clamped to 0.0" in capsys.readouterr().err

    # Unparseable input falls back to the default and must not be reported as a
    # clamp, which would be a misleading diagnostic.
    monkeypatch.setenv("FTS_LONE_HIT_SCORE", "not-a-number")
    assert _safe_unit_float("FTS_LONE_HIT_SCORE", 1.0) == 1.0
    err = capsys.readouterr().err
    assert "not a valid number" in err
    assert "clamped" not in err

    # In-range values pass through silently.
    monkeypatch.setenv("FTS_LONE_HIT_SCORE", "0.3")
    assert _safe_unit_float("FTS_LONE_HIT_SCORE", 1.0) == 0.3
    assert capsys.readouterr().err == ""

    monkeypatch.delenv("FTS_LONE_HIT_SCORE")
    assert _safe_unit_float("FTS_LONE_HIT_SCORE", 1.0) == 1.0


def test_fts_lone_hit_score_default_is_unchanged_behavior():
    """The swept value is the pre-existing 1.0: the parameter ships as a no-op,
    since an offline diagnostic found one degenerate set across 1,982 FTS calls (a
    call count, not the benchmark's 1,977 scored questions)."""
    from marm_mcp_server.config import settings

    if "FTS_LONE_HIT_SCORE" in os.environ:
        pytest.skip("environment pins FTS_LONE_HIT_SCORE; default not observable")
    assert settings.FTS_LONE_HIT_SCORE == 1.0


def _import_settings_with(env_value: str) -> tuple[str, str]:
    """Import settings.py in a clean process with FTS_LONE_HIT_SCORE set.

    A fresh interpreter is the only way to observe an import-time constant more
    than once per suite: monkeypatching the env after import is too late, and
    importlib.reload raises ImportError once another test has evicted the module.
    """
    import subprocess

    env = dict(os.environ)
    env["FTS_LONE_HIT_SCORE"] = env_value
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from marm_mcp_server.config.settings import FTS_LONE_HIT_SCORE as v;"
            "print(repr(v))",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(pathlib.Path(__file__).resolve().parent.parent),
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip(), proc.stderr


def test_fts_lone_hit_score_env_override_reaches_the_constant():
    """Covers the import-time assignment, not just the helper behind it.

    The helper test above would still pass if settings.py were changed to call
    `_safe_float` directly, silently dropping the clamp from the shipped value.
    This asserts the constant the rest of the code imports, in a real process, for
    a non-default in-range value and for one that must be clamped.
    """
    value, stderr = _import_settings_with("0.3")
    assert value == "0.3"
    assert "FTS_LONE_HIT_SCORE" not in stderr

    value, stderr = _import_settings_with("2.5")
    assert value == "1.0", "out-of-range value reached the constant unclamped"
    assert "FTS_LONE_HIT_SCORE=2.5 out of [0, 1], clamped to 1.0" in stderr


def test_fetch_fts_candidate_ids_returns_normalized_bm25_from_real_index(tmp_path):
    """Exercises the real SQLite bm25() -> normalization path end to end: the
    tighter lexical match must score highest, and every score must land in
    [0, 1] with 1.0 as the best. Guards against an inverted or out-of-range
    normalization that the fusion test's stub cannot catch."""
    from marm_mcp_server.core.memory_scoring import _fetch_fts_candidate_ids

    vec = np.ones(384, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    with memory.get_connection() as conn:
        # Tight match: the query term is essentially the whole document.
        tight_id = _insert_with_embedding(conn, "norm", "python", vec)
        # Diluted match: the query term is buried among many others.
        loose_id = _insert_with_embedding(
            conn,
            "norm",
            "python programming language tutorial guide reference manual notes",
            vec,
        )

    pairs = _fetch_fts_candidate_ids(memory.db_path, "norm", '"python"', 10)
    scores = dict(pairs)

    assert set(scores) == {tight_id, loose_id}
    assert all(0.0 <= s <= 1.0 for s in scores.values())
    assert max(scores.values()) == 1.0
    assert scores[tight_id] > scores[loose_id]


def test_wide_builder_produces_candidates_where_strict_produced_none(tmp_path):
    """The whole point of the fix, against a real FTS5 index.

    A natural-language question returns zero candidates under the strict AND
    builder (no single memory contains every token) and a non-empty pool under
    the widened builder. This is the measured 0-of-400 regression in miniature.
    """
    from marm_mcp_server.core.memory_scoring import _fetch_fts_candidate_ids

    vec = np.ones(384, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    with memory.get_connection() as conn:
        dog_id = _insert_with_embedding(
            conn,
            "nl",
            "The speaker mentioned owning a golden retriever named Max.",
            vec,
        )
        _insert_with_embedding(
            conn, "nl", "Budget review scheduled for the fourth quarter.", vec
        )
        iguana_id = _insert_with_embedding(
            conn, "nl", "Speaker two described their pet iguana in detail.", vec
        )

    question = "What pet does the speaker have?"

    strict = _safe_fts_query(question)
    assert _fetch_fts_candidate_ids(memory.db_path, "nl", strict, 50) == [], (
        "strict AND is expected to match nothing here — if it matches, the "
        "fixture no longer reproduces the bug this fix addresses"
    )

    wide = _wide(question)
    candidate_ids = {
        cid for cid, _ in _fetch_fts_candidate_ids(memory.db_path, "nl", wide, 50)
    }

    assert candidate_ids == {dog_id, iguana_id}, (
        "widened builder must surface both pet/speaker memories and exclude the "
        "unrelated budget row"
    )


def test_wide_builder_respects_session_scope(tmp_path):
    """A wide MATCH must not leak across sessions.

    Session filtering happens inside the FTS query, so broadening the MATCH
    string is exactly where a scoping bug would surface.
    """
    from marm_mcp_server.core.memory_scoring import _fetch_fts_candidate_ids

    vec = np.ones(384, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    with memory.get_connection() as conn:
        mine_id = _insert_with_embedding(conn, "mine", "my pet cat sleeps", vec)
        _insert_with_embedding(conn, "theirs", "their pet dog barks", vec)

    wide = _wide("what pet is that")
    scoped = {
        cid for cid, _ in _fetch_fts_candidate_ids(memory.db_path, "mine", wide, 50)
    }
    unscoped = {
        cid for cid, _ in _fetch_fts_candidate_ids(memory.db_path, None, wide, 50)
    }

    assert scoped == {mine_id}
    assert len(unscoped) == 2
