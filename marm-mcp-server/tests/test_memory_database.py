import pytest

from marm_mcp_server.core.memory import MARMMemory, sanitize_content


def test_sanitize_content_removes_script_tags_and_event_handlers():
    payload = '<div onclick="steal()">safe</div><script >alert("x")< /script>'

    sanitized = sanitize_content(payload)

    assert "&lt;script" not in sanitized.lower()
    assert "onclick" not in sanitized.lower()
    assert "safe" in sanitized
    assert 'alert(&quot;x&quot;)' in sanitized
    assert "<div" not in sanitized


def test_sanitize_content_preserves_text_after_malformed_script_closers():
    payloads = [
        ("<script>alert(1)</script>ok", "ok", "alert(1)"),
        ("<script>alert(1)</script foo>ok", "ok", "alert(1)"),
        ("<script src=x>alert(1)</script x>ok", "ok", "alert(1)"),
        ("<script>alert(1)< /script>ok", "ok", "alert(1)"),
        ("keep this <script partial note", "keep this", "partial note"),
    ]

    for payload, expected_kept, expected_removed in payloads:
        sanitized = sanitize_content(payload)

        assert "&lt;script" not in sanitized.lower()
        assert expected_kept in sanitized
        if expected_removed and "</script" in payload.lower():
            assert expected_removed not in sanitized


def test_sanitize_content_blocks_javascript_urls_and_caps_regex_input():
    payload = '<a href="javascript:steal()" onload="x()">link</a>' + ("x" * 20_000)

    sanitized = sanitize_content(payload)

    assert len(sanitized) < 11_000
    assert "blocked-protocol:" in sanitized
    assert "javascript:" not in sanitized.lower()
    assert "onload" not in sanitized
    assert "<a" not in sanitized


@pytest.mark.asyncio
async def test_memory_store_writes_sanitized_classified_rows_to_sqlite(tmp_path):
    db_path = tmp_path / "memory.db"
    memory = MARMMemory(str(db_path))
    memory._encoder_failed = True

    memory_id = await memory.store_memory(
        '<script>alert("x")</script> function bug fix for sqlite',
        session="unit-real-db",
    )

    with memory.get_connection() as conn:
        row = conn.execute(
            "SELECT session_name, content, context_type FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()

    assert row is not None
    assert row[0] == "unit-real-db"
    assert "script" not in row[1].lower()
    assert "function bug fix" in row[1]
    assert row[2] == "code"

    results = await memory.recall_text_search("sqlite", session="unit-real-db", limit=3)
    assert len(results) == 1
    assert results[0]["id"] == memory_id


@pytest.mark.asyncio
async def test_memory_recall_respects_session_scope_and_search_all(tmp_path):
    db_path = tmp_path / "memory.db"
    memory = MARMMemory(str(db_path))
    memory._encoder_failed = True

    alpha_id = await memory.store_memory("alpha deployment decision uses docker http", "alpha")
    beta_id = await memory.store_memory("beta deployment decision uses stdio transport", "beta")

    alpha_results = await memory.recall_text_search("deployment", session="alpha", limit=10)
    all_results = await memory.recall_text_search("deployment", session=None, limit=10)

    assert [result["id"] for result in alpha_results] == [alpha_id]
    assert {result["id"] for result in all_results} == {alpha_id, beta_id}


@pytest.mark.asyncio
async def test_auto_classification_covers_primary_context_types(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))

    assert await memory.auto_classify_content("fix bug in class implementation") == "code"
    assert await memory.auto_classify_content("project milestone sprint deadline") == "project"
    assert await memory.auto_classify_content("chapter plot character arc") == "book"
    assert await memory.auto_classify_content("plain operational note") == "general"
