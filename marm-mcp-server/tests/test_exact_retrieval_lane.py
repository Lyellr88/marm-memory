"""Tests for the exact retrieval lane (issue #65).

Covers:
- _is_exact_query detection heuristics
- _recall_exact path (pure FTS, no semantic re-ranking)
- exact_mode parameter on recall_similar: "auto", "exact", "semantic"
- Config keys, CLI commands, API names, file paths, short code snippets
"""

import uuid as _uuid_module
from datetime import datetime, timezone as _timezone

import numpy as np
import pytest

from marm_mcp_server.core.memory import MARMMemory, _is_exact_query


# ---------------------------------------------------------------------------
# _is_exact_query  — detection heuristics
# ---------------------------------------------------------------------------


class TestIsExactQuery:
    # --- should return True ---

    def test_upper_snake_case_env_var(self):
        assert _is_exact_query("RECALL_SCAN_LIMIT") is True

    def test_upper_snake_case_config_key(self):
        assert _is_exact_query("FTS_CANDIDATE_LIMIT") is True

    def test_python_file_path(self):
        assert _is_exact_query("marm_mcp_server/core/memory.py") is True

    def test_yaml_config_file(self):
        assert _is_exact_query("config/settings.yaml") is True

    def test_json_file(self):
        assert _is_exact_query("package.json") is True

    def test_cli_flag(self):
        assert _is_exact_query("--workers=4") is True

    def test_cli_flag_no_value(self):
        assert _is_exact_query("--generate-key") is True

    def test_unix_absolute_path(self):
        assert _is_exact_query("/home/user/.marm/memory.db") is True

    def test_function_call_syntax(self):
        assert _is_exact_query("recall_similar(") is True

    def test_dotted_namespace(self):
        assert _is_exact_query("marm_mcp_server.core.memory") is True

    def test_http_verb_with_path(self):
        assert _is_exact_query("GET /api/v1/memories") is True

    def test_post_verb(self):
        assert _is_exact_query("POST /marm_smart_recall") is True

    def test_url(self):
        assert _is_exact_query("https://api.anthropic.com/v1/messages") is True

    def test_quoted_string(self):
        assert _is_exact_query('`docker run --rm`') is True

    def test_mixed_case_config_key(self):
        assert _is_exact_query("server_HOST") is True

    def test_shell_command_with_flag(self):
        assert _is_exact_query("docker run --rm marm") is True

    # --- should return False ---

    def test_natural_language_sentence(self):
        assert _is_exact_query("what was the decision we made about the database") is False

    def test_long_sentence_exceeds_word_limit(self):
        long = " ".join(["word"] * 13)
        assert _is_exact_query(long) is False

    def test_project_milestone_query(self):
        assert _is_exact_query("sprint goals for this quarter") is False

    def test_short_generic_word(self):
        assert _is_exact_query("deployment") is False

    def test_empty_string(self):
        assert _is_exact_query("") is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_with_embedding(conn, session: str, content: str, vec: np.ndarray) -> str:
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


def _insert_no_embedding(conn, session: str, content: str) -> str:
    mem_id = str(_uuid_module.uuid4())
    content_hash = f"{hash(content + mem_id)}"
    ts = datetime.now(_timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO memories"
        " (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata)"
        " VALUES (?, ?, ?, NULL, ?, ?, 'general', '{}')",
        (mem_id, session, content, content_hash, ts),
    )
    return mem_id


# ---------------------------------------------------------------------------
# exact_mode="exact"  — always uses lexical lane
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_mode_explicit_returns_fts_result_for_config_key(tmp_path):
    """exact_mode='exact' must surface a config-key memory via FTS."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    mem_id = await mem.store_memory(
        "RECALL_SCAN_LIMIT default is 10000", session="cfg"
    )

    results = await mem.recall_similar(
        "RECALL_SCAN_LIMIT", session="cfg", limit=5, exact_mode="exact"
    )

    assert any(r["id"] == mem_id for r in results)


@pytest.mark.asyncio
async def test_exact_mode_explicit_returns_fts_result_for_cli_command(tmp_path):
    """exact_mode='exact' must surface a CLI command memory via FTS."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    mem_id = await mem.store_memory(
        "python -m marm_mcp_server --generate-key", session="cmds"
    )

    results = await mem.recall_similar(
        "--generate-key", session="cmds", limit=5, exact_mode="exact"
    )

    assert any(r["id"] == mem_id for r in results)


@pytest.mark.asyncio
async def test_exact_mode_explicit_returns_fts_result_for_file_path(tmp_path):
    """exact_mode='exact' must surface a file-path memory via FTS."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    mem_id = await mem.store_memory(
        "config lives in marm_mcp_server/config/settings.py", session="paths"
    )

    results = await mem.recall_similar(
        "settings.py", session="paths", limit=5, exact_mode="exact"
    )

    assert any(r["id"] == mem_id for r in results)


@pytest.mark.asyncio
async def test_exact_mode_explicit_returns_fts_result_for_api_name(tmp_path):
    """exact_mode='exact' must surface an API-name memory via FTS."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    mem_id = await mem.store_memory(
        "marm_smart_recall accepts session_name and limit", session="api"
    )

    results = await mem.recall_similar(
        "marm_smart_recall", session="api", limit=5, exact_mode="exact"
    )

    assert any(r["id"] == mem_id for r in results)


@pytest.mark.asyncio
async def test_exact_mode_explicit_returns_fts_result_for_code_snippet(tmp_path):
    """exact_mode='exact' must surface a short code-snippet memory via FTS."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    mem_id = await mem.store_memory(
        "recall_similar(query, session=None, limit=5)", session="code"
    )

    results = await mem.recall_similar(
        "recall_similar(", session="code", limit=5, exact_mode="exact"
    )

    assert any(r["id"] == mem_id for r in results)


# ---------------------------------------------------------------------------
# exact_mode="auto"  — switches lane based on query shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_mode_uses_exact_lane_for_upper_snake_config_key(
    monkeypatch, tmp_path
):
    """auto mode must route UPPER_SNAKE_CASE to the exact lane."""
    from marm_mcp_server.core import memory_ops as ops

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("FTS_CANDIDATE_LIMIT controls filter size", session="s")

    exact_calls: list[str] = []
    original = ops._recall_exact

    async def spy(*args, **kwargs):
        exact_calls.append(args[1])  # query arg
        return await original(*args, **kwargs)

    monkeypatch.setattr(ops, "_recall_exact", spy)

    await mem.recall_similar("FTS_CANDIDATE_LIMIT", session="s", limit=5)

    assert exact_calls, "exact lane was not called for a config-key query"


@pytest.mark.asyncio
async def test_auto_mode_uses_semantic_lane_for_natural_language(
    monkeypatch, tmp_path
):
    """auto mode must NOT route a plain natural-language query to the exact lane."""
    from marm_mcp_server.core import memory_ops as ops

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        _insert_with_embedding(conn, "nl", "what was the sprint goal", vec)

    exact_calls: list[str] = []
    original = ops._recall_exact

    async def spy(*args, **kwargs):
        exact_calls.append(args[1])
        return await original(*args, **kwargs)

    monkeypatch.setattr(ops, "_recall_exact", spy)

    await mem.recall_similar(
        "what was the sprint goal", session="nl", limit=5, query_vec=vec.copy()
    )

    assert not exact_calls, "exact lane must not fire for a natural-language query"


# ---------------------------------------------------------------------------
# exact_mode="semantic"  — always semantic, even for syntax-heavy query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_mode_bypasses_exact_lane_for_config_key(
    monkeypatch, tmp_path
):
    """exact_mode='semantic' must skip the exact lane even for UPPER_SNAKE_CASE."""
    from marm_mcp_server.core import memory_ops as ops

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        _insert_with_embedding(
            conn, "sem", "RECALL_SCAN_LIMIT controls scan size", vec
        )

    exact_calls: list[str] = []
    original = ops._recall_exact

    async def spy(*args, **kwargs):
        exact_calls.append(args[1])
        return await original(*args, **kwargs)

    monkeypatch.setattr(ops, "_recall_exact", spy)

    await mem.recall_similar(
        "RECALL_SCAN_LIMIT", session="sem", limit=5,
        query_vec=vec.copy(), exact_mode="semantic"
    )

    assert not exact_calls, "exact lane must not run when exact_mode='semantic'"


# ---------------------------------------------------------------------------
# Exact lane result quality — config key beats unrelated semantic neighbor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_mode_ranks_config_key_match_above_semantic_neighbor(tmp_path):
    """The exact lane must surface the config-key memory even when a semantically
    'closer' but keyword-unrelated memory is stored with a strong embedding.
    """
    dim = 384
    strong_vec = np.ones(dim, dtype=np.float32)
    strong_vec /= np.linalg.norm(strong_vec)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    # Semantically-strong neighbor (no embedding on config-key row since encoder failed)
    with mem.get_connection() as conn:
        _insert_with_embedding(
            conn, "rank", "general semantic content unrelated to config", strong_vec
        )

    config_id = await mem.store_memory(
        "CONSOLIDATION_THRESHOLD is set to 0.85", session="rank"
    )

    results = await mem.recall_similar(
        "CONSOLIDATION_THRESHOLD", session="rank", limit=5, exact_mode="exact"
    )

    assert results, "exact lane returned no results"
    assert results[0]["id"] == config_id, (
        "config-key memory must rank first on the exact lane"
    )


# ---------------------------------------------------------------------------
# Exact lane response shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_mode_response_shape(tmp_path):
    """Results from the exact lane must have all required fields."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("TEMPORAL_WEIGHT default value is 0.3", session="shape")

    results = await mem.recall_similar(
        "TEMPORAL_WEIGHT", session="shape", limit=5, exact_mode="exact"
    )

    assert results
    required = {"id", "session_name", "content", "timestamp", "context_type",
                "metadata", "similarity"}
    assert required.issubset(results[0].keys())


@pytest.mark.asyncio
async def test_exact_mode_include_scan_metadata_returns_tuple(tmp_path):
    """include_scan_metadata=True must still work correctly with exact_mode='exact'."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("TEMPORAL_HALF_LIFE_DAYS config", session="meta")

    results, meta = await mem.recall_similar(
        "TEMPORAL_HALF_LIFE_DAYS", session="meta", limit=5,
        exact_mode="exact", include_scan_metadata=True
    )

    assert isinstance(results, list)
    assert "recall_scan_truncated" in meta
    assert "recall_scan_limit" in meta
    assert meta["recall_scan_truncated"] is False


# ---------------------------------------------------------------------------
# Session scoping on exact lane
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_lane_session_filter_excludes_other_sessions(tmp_path):
    """Exact lane must respect session scoping."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    id_a = await mem.store_memory("WRITE_QUEUE_SIZE=100", session="session-a")
    await mem.store_memory("WRITE_QUEUE_SIZE=100", session="session-b")

    results = await mem.recall_similar(
        "WRITE_QUEUE_SIZE", session="session-a", limit=5, exact_mode="exact"
    )

    assert all(r["session_name"] == "session-a" for r in results)
    assert any(r["id"] == id_a for r in results)


# ---------------------------------------------------------------------------
# Default (backward-compat): exact_mode="auto" is the default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_exact_mode_is_auto(tmp_path):
    """Calling recall_similar without exact_mode must default to auto behaviour."""
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    mem_id = await mem.store_memory(
        "COMPACTION_TRIGGER_COUNT is 10 by default", session="default-test"
    )

    # COMPACTION_TRIGGER_COUNT is UPPER_SNAKE → auto should pick exact lane
    results = await mem.recall_similar(
        "COMPACTION_TRIGGER_COUNT", session="default-test", limit=5
    )

    assert any(r["id"] == mem_id for r in results)
