import asyncio

import pytest

from marm_mcp_server.core.memory import MARMMemory, sanitize_content


def test_sanitize_content_removes_script_tags_and_event_handlers():
    payload = '<div onclick="steal()">safe</div><script >alert("x")< /script>'

    sanitized = sanitize_content(payload)

    assert "&lt;script" not in sanitized.lower()
    assert "onclick" not in sanitized.lower()
    assert "safe" in sanitized
    assert "alert(&quot;x&quot;)" in sanitized
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
async def test_store_memory_queued_disabled_uses_direct_write(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    memory_id = await memory.store_memory_queued(
        "direct queued helper write",
        "queue-disabled",
        queue_enabled=False,
    )

    assert memory._write_queue is None
    with memory.get_connection() as conn:
        row = conn.execute(
            "SELECT content FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()

    assert row[0] == "direct queued helper write"


@pytest.mark.asyncio
async def test_store_memory_queued_skips_startup_when_queue_already_running(
    monkeypatch, tmp_path
):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "WRITE_QUEUE_ENABLED", True)
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True
    await memory.start_write_queue()

    async def fail_if_called():
        raise AssertionError("start_write_queue should not run once queue exists")

    monkeypatch.setattr(memory, "start_write_queue", fail_if_called)

    try:
        memory_id = await memory.store_memory_queued(
            "already running queue write", "queue-hot-path"
        )
    finally:
        await memory.stop_write_queue()

    with memory.get_connection() as conn:
        row = conn.execute(
            "SELECT session_name FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()

    assert row[0] == "queue-hot-path"


@pytest.mark.asyncio
async def test_write_queue_serializes_concurrent_memory_writes(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "WRITE_QUEUE_ENABLED", True)
    monkeypatch.setattr(memory_module, "MAX_QUEUE_SIZE", 20)
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    try:
        memory_ids = await asyncio.gather(
            *[
                memory.store_memory_queued(f"queued write {index}", "queue-enabled")
                for index in range(10)
            ]
        )
    finally:
        await memory.stop_write_queue()

    assert len(set(memory_ids)) == 10
    with memory.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?",
            ("queue-enabled",),
        ).fetchone()[0]

    assert count == 10


@pytest.mark.asyncio
async def test_write_queue_propagates_worker_errors(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "WRITE_QUEUE_ENABLED", True)
    memory = MARMMemory(str(tmp_path / "memory.db"))

    async def failing_store(*args, **kwargs):
        raise RuntimeError("write failed")

    monkeypatch.setattr(memory, "store_memory", failing_store)

    try:
        with pytest.raises(RuntimeError, match="write failed"):
            await memory.store_memory_queued("bad write", "queue-errors")
    finally:
        await memory.stop_write_queue()


@pytest.mark.asyncio
async def test_memory_recall_respects_session_scope_and_search_all(tmp_path):
    db_path = tmp_path / "memory.db"
    memory = MARMMemory(str(db_path))
    memory._encoder_failed = True

    alpha_id = await memory.store_memory(
        "alpha deployment decision uses docker http", "alpha"
    )
    beta_id = await memory.store_memory(
        "beta deployment decision uses stdio transport", "beta"
    )

    alpha_results = await memory.recall_text_search(
        "deployment", session="alpha", limit=10
    )
    all_results = await memory.recall_text_search("deployment", session=None, limit=10)

    assert [result["id"] for result in alpha_results] == [alpha_id]
    assert {result["id"] for result in all_results} == {alpha_id, beta_id}


@pytest.mark.asyncio
async def test_auto_classification_covers_primary_context_types(tmp_path):
    memory = MARMMemory(str(tmp_path / "memory.db"))

    assert (
        await memory.auto_classify_content("fix bug in class implementation") == "code"
    )
    assert (
        await memory.auto_classify_content("project milestone sprint deadline")
        == "project"
    )
    assert await memory.auto_classify_content("chapter plot character arc") == "book"
    assert await memory.auto_classify_content("plain operational note") == "general"


def test_close_all_drains_connection_pool(tmp_path):
    # Regression: graceful_shutdown must close pooled SQLite connections so
    # Docker/HTTP restarts and local dev restarts don't leak open file handles.
    db_path = tmp_path / "memory.db"
    memory = MARMMemory(str(db_path))

    # Acquire then return a connection so the pool has at least one entry
    with memory.get_connection():
        pass

    assert not memory.connection_pool.pool.empty()

    memory.connection_pool.close_all()

    assert memory.connection_pool.pool.empty()


@pytest.mark.asyncio
async def test_mismatched_embedding_dimension_skipped_with_signal_without_breaking_recall(
    tmp_path,
):
    """Vectors stored by a different model (wrong dimension) must not silently poison recall.

    Regression for: old embeddings surviving a model change cause shape-mismatch errors
    swallowed by bare `except Exception: continue`, making memories vanish with no signal.
    """
    import numpy as np
    import uuid

    memory = MARMMemory(str(tmp_path / "memory.db"))
    correct_dim = 384
    wrong_dim = 768

    correct_vec = np.ones(correct_dim, dtype=np.float32)
    correct_vec /= np.linalg.norm(correct_vec)
    wrong_vec = np.ones(wrong_dim, dtype=np.float32)
    wrong_vec /= np.linalg.norm(wrong_vec)

    good_id = str(uuid.uuid4())
    bad_id = str(uuid.uuid4())

    with memory.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata) VALUES (?, ?, ?, ?, ?, datetime('now'), 'general', '{}')",
            (
                good_id,
                "sess",
                "correct dimension memory",
                correct_vec.tobytes(),
                "hash-good",
            ),
        )
        conn.execute(
            "INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata) VALUES (?, ?, ?, ?, ?, datetime('now'), 'general', '{}')",
            (bad_id, "sess", "wrong dimension memory", wrong_vec.tobytes(), "hash-bad"),
        )

    query_vec = np.ones(correct_dim, dtype=np.float32)
    query_vec /= np.linalg.norm(query_vec)

    results = await memory.recall_similar(
        "test query", session="sess", limit=10, query_vec=query_vec
    )

    result_ids = {r["id"] for r in results}
    assert good_id in result_ids, "correct-dimension memory must be returned"
    assert bad_id not in result_ids, (
        "wrong-dimension memory must be skipped, not crash recall"
    )


@pytest.mark.asyncio
async def test_recall_similar_scan_truncated_fires_when_scan_limit_exceeded(
    monkeypatch, tmp_path
):
    """Regression: recall_similar must report recall_scan_truncated=True when the DB
    holds more rows than RECALL_SCAN_LIMIT so callers know recall was bounded.

    Uses direct DB inserts + query_vec to bypass the encoder path, which would
    short-circuit to text search before the scan query runs.
    """
    import numpy as np
    import uuid as uuid_module

    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "RECALL_SCAN_LIMIT", 5)
    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with mem.get_connection() as conn:
        for i in range(7):
            conn.execute(
                "INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata)"
                " VALUES (?, ?, ?, ?, ?, datetime('now'), 'general', '{}')",
                (
                    str(uuid_module.uuid4()),
                    "trunc-test",
                    f"test entry {i}",
                    vec.tobytes(),
                    f"hash-trunc-{i}",
                ),
            )

    query_vec = np.ones(dim, dtype=np.float32)
    query_vec /= np.linalg.norm(query_vec)

    results, meta = await mem.recall_similar(
        "test entry",
        session="trunc-test",
        limit=3,
        query_vec=query_vec,
        include_scan_metadata=True,
    )

    assert meta["recall_scan_truncated"] is True
    assert meta["recall_scan_limit"] == 5
    assert len(results) <= 3


@pytest.mark.asyncio
async def test_recall_similar_scan_not_truncated_when_under_limit(
    monkeypatch, tmp_path
):
    """recall_scan_truncated must be False when total rows are within RECALL_SCAN_LIMIT."""
    import numpy as np
    import uuid as uuid_module

    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "RECALL_SCAN_LIMIT", 10)
    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))

    dim = 384
    vec = np.ones(dim, dtype=np.float32)
    vec /= np.linalg.norm(vec)

    with mem.get_connection() as conn:
        for i in range(4):
            conn.execute(
                "INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata)"
                " VALUES (?, ?, ?, ?, ?, datetime('now'), 'general', '{}')",
                (
                    str(uuid_module.uuid4()),
                    "no-trunc-test",
                    f"entry {i}",
                    vec.tobytes(),
                    f"hash-notrunc-{i}",
                ),
            )

    query_vec = np.ones(dim, dtype=np.float32)
    query_vec /= np.linalg.norm(query_vec)

    _results, meta = await mem.recall_similar(
        "entry",
        session="no-trunc-test",
        limit=3,
        query_vec=query_vec,
        include_scan_metadata=True,
    )

    assert meta["recall_scan_truncated"] is False


@pytest.mark.asyncio
async def test_recall_similar_vectorized_scores_preserve_ranking(tmp_path):
    """Vectorized scoring must preserve cosine ranking order."""
    import numpy as np
    import uuid as uuid_module

    mem = MARMMemory(str(tmp_path / "memory.db"))
    dim = 384

    def unit(first: float, second: float = 0.0):
        vec = np.zeros(dim, dtype=np.float32)
        vec[0] = first
        vec[1] = second
        vec /= np.linalg.norm(vec)
        return vec

    rows = [
        ("best", unit(1.0, 0.0), "2026-01-01T00:00:01Z"),
        ("middle", unit(0.75, 0.25), "2026-01-01T00:00:02Z"),
        ("worst", unit(0.0, 1.0), "2026-01-01T00:00:03Z"),
    ]
    with mem.get_connection() as conn:
        for label, vec, timestamp in rows:
            conn.execute(
                "INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata)"
                " VALUES (?, ?, ?, ?, ?, ?, 'general', '{}')",
                (
                    str(uuid_module.uuid4()),
                    "rank-test",
                    label,
                    vec.tobytes(),
                    f"hash-rank-{label}",
                    timestamp,
                ),
            )

    results = await mem.recall_similar(
        "rank", session="rank-test", limit=3, query_vec=unit(1.0, 0.0)
    )

    assert [result["content"] for result in results] == ["best", "middle", "worst"]


@pytest.mark.asyncio
async def test_recall_similar_finds_match_past_old_1000_row_cliff(
    monkeypatch, tmp_path
):
    """Regression: a best match older than the old 1000-row window remains reachable."""
    import numpy as np
    import uuid as uuid_module

    from marm_mcp_server.core import memory as memory_module

    monkeypatch.setattr(memory_module, "RECALL_SCAN_LIMIT", 1500)
    mem = memory_module.MARMMemory(str(tmp_path / "memory.db"))
    dim = 384

    query_vec = np.zeros(dim, dtype=np.float32)
    query_vec[0] = 1.0
    filler_vec = np.zeros(dim, dtype=np.float32)
    filler_vec[1] = 1.0

    with mem.get_connection() as conn:
        for i in range(1205):
            is_old_best = i == 100
            content = "old best semantic match" if is_old_best else f"filler {i}"
            vec = query_vec if is_old_best else filler_vec
            conn.execute(
                "INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata)"
                " VALUES (?, ?, ?, ?, ?, ?, 'general', '{}')",
                (
                    str(uuid_module.uuid4()),
                    "old-cliff-test",
                    content,
                    vec.tobytes(),
                    f"hash-old-cliff-{i}",
                    f"2026-01-01T00:00:{i:04d}Z",
                ),
            )

    results, meta = await mem.recall_similar(
        "old match",
        session="old-cliff-test",
        limit=1,
        query_vec=query_vec,
        include_scan_metadata=True,
    )

    assert meta["recall_scan_truncated"] is False
    assert meta["recall_scan_limit"] == 1500
    assert results[0]["content"] == "old best semantic match"


@pytest.mark.asyncio
async def test_update_memory_merge_cap_never_exceeds_10000_chars(tmp_path):
    """Regression: merging two 10,000-char contents must not produce a blob > 10,000 chars."""
    memory = MARMMemory(str(tmp_path / "memory.db"))
    memory._encoder_failed = True

    memory_id = await memory.store_memory("seed", session="cap-test")

    big_existing = "A" * 10000
    with memory.get_connection() as conn:
        conn.execute(
            "UPDATE memories SET content = ? WHERE id = ?",
            (big_existing, memory_id),
        )

    big_new = "B" * 10000
    await memory.update_memory(memory_id, big_new)

    with memory.get_connection() as conn:
        row = conn.execute(
            "SELECT content FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()

    stored = row[0]
    merge_marker = "\n[merged] "
    expected_new_len = 10000 - len(merge_marker)
    assert len(stored) == 10000
    assert stored.startswith(merge_marker)
    assert stored.endswith("B" * expected_new_len)
    assert "A" not in stored
