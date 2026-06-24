"""Tests for the one-time email signup prompt injection feature."""

import uuid
from datetime import datetime, timezone

import pytest

from marm_mcp_server.core.memory import MARMMemory
from marm_mcp_server.core.response_limiter import MCPResponseLimiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_user_memories(mem: MARMMemory, count: int, session: str = "main"):
    with mem.get_connection() as conn:
        for i in range(count):
            conn.execute(
                """
                INSERT INTO memories
                    (id, session_name, content, embedding, content_hash, timestamp,
                     context_type, metadata)
                VALUES (?, ?, ?, NULL, ?, ?, 'general', '{}')
                """,
                (
                    str(uuid.uuid4()),
                    session,
                    f"user memory content {i}",
                    f"user memory content {i}",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


# ---------------------------------------------------------------------------
# 1. Returns False below threshold
# ---------------------------------------------------------------------------


def test_check_returns_false_below_threshold(tmp_path, monkeypatch):
    import marm_mcp_server.core.memory as mem_module

    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_THRESHOLD", 25)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    _insert_user_memories(mem, 10)

    assert mem.check_and_mark_signup_prompt() is False


# ---------------------------------------------------------------------------
# 2. Ignores marm_system memories and compaction source rows in count
# ---------------------------------------------------------------------------


def test_check_ignores_system_and_compaction_source_rows(tmp_path, monkeypatch):
    import marm_mcp_server.core.memory as mem_module

    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_THRESHOLD", 5)

    mem = MARMMemory(str(tmp_path / "memory.db"))

    with mem.get_connection() as conn:
        # System session — must not count
        for i in range(10):
            conn.execute(
                """
                INSERT INTO memories
                    (id, session_name, content, embedding, content_hash, timestamp,
                     context_type, metadata)
                VALUES (?, ?, ?, NULL, ?, ?, 'general', '{}')
                """,
                (
                    str(uuid.uuid4()),
                    "marm_system",
                    f"system doc {i}",
                    f"system doc {i}",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        # Compaction source rows — must not count
        for i in range(10):
            conn.execute(
                """
                INSERT INTO memories
                    (id, session_name, content, embedding, content_hash, timestamp,
                     context_type, metadata, compaction_role)
                VALUES (?, ?, ?, NULL, ?, ?, 'general', '{}', 'source')
                """,
                (
                    str(uuid.uuid4()),
                    "main",
                    f"compaction source {i}",
                    f"compaction source {i}",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    # 20 rows exist but zero count toward threshold
    assert mem.check_and_mark_signup_prompt() is False


# ---------------------------------------------------------------------------
# 3. Returns True at threshold and writes the DB flag
# ---------------------------------------------------------------------------


def test_check_returns_true_at_threshold_and_writes_flag(tmp_path, monkeypatch):
    import marm_mcp_server.core.memory as mem_module

    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_THRESHOLD", 5)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    _insert_user_memories(mem, 5)

    result = mem.check_and_mark_signup_prompt()
    assert result is True

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE key = 'signup_prompted'"
        ).fetchone()
    assert row is not None
    assert row[0] == "1"


# ---------------------------------------------------------------------------
# 4. Returns False on every subsequent call once flag is written
# ---------------------------------------------------------------------------


def test_check_returns_false_after_flag_set(tmp_path, monkeypatch):
    import marm_mcp_server.core.memory as mem_module

    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_THRESHOLD", 3)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    _insert_user_memories(mem, 5)

    first = mem.check_and_mark_signup_prompt()
    second = mem.check_and_mark_signup_prompt()
    third = mem.check_and_mark_signup_prompt()

    assert first is True
    assert second is False
    assert third is False


# ---------------------------------------------------------------------------
# 5. smart_recall injects _signup_prompt exactly once across multiple calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_injects_signup_prompt_exactly_once(tmp_path, monkeypatch):
    import marm_mcp_server.core.memory as mem_module
    from marm_mcp_server.services import recall as recall_module

    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_THRESHOLD", 3)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(recall_module, "memory", mem)

    _insert_user_memories(mem, 5)

    result1 = await recall_module.smart_recall(
        "user memory content", session_name="main", search_all=True, detail=3
    )
    result2 = await recall_module.smart_recall(
        "user memory content", session_name="main", search_all=True, detail=3
    )

    assert result1["status"] == "success"
    assert "_signup_prompt" in result1

    assert result2["status"] == "success"
    assert "_signup_prompt" not in result2


# ---------------------------------------------------------------------------
# 6. no_results path never injects _signup_prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_no_results_never_injects_signup_prompt(tmp_path, monkeypatch):
    import marm_mcp_server.core.memory as mem_module
    from marm_mcp_server.services import recall as recall_module

    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_THRESHOLD", 3)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(recall_module, "memory", mem)

    # Enough user memories to clear the threshold, but in a different session
    _insert_user_memories(mem, 5, session="other-session")

    # Query a session with no memories — triggers the no_results early return
    result = await recall_module.smart_recall(
        "xyzzy nothing here", session_name="empty-session", search_all=False, detail=3
    )

    assert result["status"] == "no_results"
    assert "_signup_prompt" not in result

    # check_and_mark_signup_prompt() must never be called on the no_results path
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE key = 'signup_prompted'"
        ).fetchone()
    assert row is None


# ---------------------------------------------------------------------------
# 7. _signup_prompt is skipped when adding it would exceed the 1MB limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_skips_signup_prompt_when_over_size_limit(tmp_path, monkeypatch):
    import marm_mcp_server.core.memory as mem_module
    from marm_mcp_server.services import recall as recall_module

    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_THRESHOLD", 3)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(recall_module, "memory", mem)

    _insert_user_memories(mem, 5)

    # Return over-limit only when the dict already contains _signup_prompt,
    # so limit_memory_response still works normally.
    original_estimate = MCPResponseLimiter.estimate_response_size

    def _oversize_if_signup(data):
        if "_signup_prompt" in data:
            return MCPResponseLimiter.CONTENT_LIMIT + 1
        return original_estimate(data)

    monkeypatch.setattr(
        MCPResponseLimiter, "estimate_response_size", staticmethod(_oversize_if_signup)
    )

    result = await recall_module.smart_recall(
        "user memory content", session_name="main", search_all=True, detail=3
    )

    # Prompt omitted from response
    assert result["status"] == "success"
    assert "_signup_prompt" not in result

    # Flag must still be written (set at check time, before size guard)
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE key = 'signup_prompted'"
        ).fetchone()
    assert row is not None
    assert row[0] == "1"


# ---------------------------------------------------------------------------
# 8. MARM_SIGNUP_PROMPT_ENABLED=False disables injection entirely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_disabled_by_env_flag(tmp_path, monkeypatch):
    import marm_mcp_server.core.memory as mem_module
    from marm_mcp_server.services import recall as recall_module

    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_ENABLED", False)
    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_THRESHOLD", 3)

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(recall_module, "memory", mem)

    _insert_user_memories(mem, 5)

    result = await recall_module.smart_recall(
        "user memory content", session_name="main", search_all=True, detail=3
    )

    assert result["status"] == "success"
    assert "_signup_prompt" not in result

    # DB flag must NOT be written when disabled
    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE key = 'signup_prompted'"
        ).fetchone()
    assert row is None


# ---------------------------------------------------------------------------
# 9. user_settings flag persists across MARMMemory instances (server restart)
# ---------------------------------------------------------------------------


def test_signup_flag_persists_across_instances(tmp_path, monkeypatch):
    import marm_mcp_server.core.memory as mem_module

    monkeypatch.setattr(mem_module, "SIGNUP_PROMPT_THRESHOLD", 3)

    db = str(tmp_path / "memory.db")
    mem1 = MARMMemory(db)
    _insert_user_memories(mem1, 5)

    first = mem1.check_and_mark_signup_prompt()
    assert first is True

    # New instance pointing at the same DB file simulates a server restart
    mem2 = MARMMemory(db)
    second = mem2.check_and_mark_signup_prompt()
    assert second is False
