import asyncio
import importlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from conftest import load_isolated_server

from marm_mcp_server.core.memory_ops import _update_memory


@pytest.fixture
def queue_env(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    memory_module = sys.modules["marm_mcp_server.core.memory"]
    concept_queue = importlib.import_module("marm_mcp_server.core.concept_queue")
    return memory_module.memory, concept_queue


def _rows(mem):
    with mem.get_connection() as conn:
        return conn.execute(
            "SELECT memory_id, content_hash, state, attempts, last_error, lease_token "
            "FROM concept_index_queue ORDER BY enqueued_at, memory_id"
        ).fetchall()


def _seed_task(mem, queue, memory_id, content_hash="h1"):
    """Insert the memory and its task through enqueue itself."""
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, content_hash) "
            "VALUES (?, 'sess-a', 'content', datetime('now'), ?)",
            (memory_id, content_hash),
        )
        queue.enqueue(conn, memory_id, content_hash)


def test_storing_a_memory_queues_it(queue_env):
    mem, _queue = queue_env
    memory_id = asyncio.run(mem.store_memory("the write queue serializes writes", "s1"))

    rows = _rows(mem)
    assert [row[0] for row in rows] == [memory_id]
    assert rows[0][2] == "pending"
    with mem.get_connection() as conn:
        stored_hash = conn.execute(
            "SELECT content_hash FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()[0]
    assert rows[0][1] == stored_hash


def test_a_rolled_back_write_leaves_no_task(queue_env):
    """The enqueue shares the memory INSERT's transaction, which is the entire
    argument for keeping this table in the memory database."""
    mem, queue = queue_env
    with mem.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, content_hash) "
            "VALUES ('m1', 'sess-a', 'content', datetime('now'), 'h1')"
        )
        queue.enqueue(conn, "m1", "h1")
        conn.execute("ROLLBACK")

    assert _rows(mem) == []
    with mem.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0


def test_merge_requeues_with_the_new_hash_and_resets_attempts(queue_env):
    """A merge reuses the memory_id. Dedup on the id alone would treat the
    merged content as already indexed and never extract it."""
    mem, _queue = queue_env
    memory_id = asyncio.run(mem.store_memory("original content about auth", "s1"))
    with mem.get_connection() as conn:
        original_hash = conn.execute(
            "SELECT content_hash FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE concept_index_queue SET attempts = 2, state = 'parked', "
            "last_error = 'boom' WHERE memory_id = ?",
            (memory_id,),
        )

    assert asyncio.run(_update_memory(mem, memory_id, "additional content")) is True

    rows = _rows(mem)
    assert len(rows) == 1
    memory_id_row, content_hash, state, attempts, last_error, _token = rows[0]
    assert memory_id_row == memory_id
    assert content_hash != original_hash
    assert (state, attempts, last_error) == ("pending", 0, None)


def test_deleting_a_memory_drops_its_task(queue_env):
    """A task pointing at a deleted memory would be claimed until it burned
    the attempt budget."""
    from marm_mcp_server.core.memory_delete import _delete_memories

    mem, _queue = queue_env
    memory_id = asyncio.run(mem.store_memory("content to delete", "s1"))
    assert _rows(mem)

    result = asyncio.run(_delete_memories(mem, [memory_id]))

    assert result["deleted_ids"] == [memory_id]
    assert _rows(mem) == []


def test_claim_leases_rows_and_a_second_claim_gets_nothing(queue_env):
    """Two processes share one memory DB and the in-process build lock cannot
    reach across them. The lease is what keeps them off each other's tasks."""
    mem, queue = queue_env
    _seed_task(mem, queue, "m1")
    _seed_task(mem, queue, "m2")

    first = queue.claim(10)
    second = queue.claim(10)

    assert sorted(task.memory_id for task in first) == ["m1", "m2"]
    assert second == []
    assert {row[2] for row in _rows(mem)} == {"leased"}


def test_claim_respects_the_batch_limit(queue_env):
    mem, queue = queue_env
    for index in range(5):
        _seed_task(mem, queue, f"m{index}")

    assert len(queue.claim(2)) == 2
    assert len(queue.claim(2)) == 2
    assert len(queue.claim(2)) == 1


def test_an_expired_lease_is_reclaimed_without_burning_an_attempt(queue_env):
    """A worker killed mid-extraction must not cost the task an attempt: it
    never failed, its process died."""
    mem, queue = queue_env
    _seed_task(mem, queue, "m1")
    first = queue.claim(1)
    assert len(first) == 1

    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with mem.get_connection() as conn:
        conn.execute("UPDATE concept_index_queue SET leased_until = ?", (expired,))

    reclaimed = queue.claim(1)

    assert len(reclaimed) == 1
    assert reclaimed[0].memory_id == "m1"
    assert reclaimed[0].lease_token != first[0].lease_token
    assert _rows(mem)[0][3] == 0


def test_complete_with_a_stale_token_is_rejected(queue_env):
    """The task was reclaimed by another worker while this one was running.
    Its result belongs to a lease it no longer holds."""
    mem, queue = queue_env
    _seed_task(mem, queue, "m1")
    stale = queue.claim(1)[0]
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with mem.get_connection() as conn:
        conn.execute("UPDATE concept_index_queue SET leased_until = ?", (expired,))
    queue.claim(1)

    assert queue.complete("m1", stale.lease_token, stale.content_hash) is False
    assert len(_rows(mem)) == 1


def test_complete_with_a_superseded_hash_is_rejected(queue_env):
    """The memory was merged while the extraction ran, so this result covers
    text that is no longer the whole memory."""
    mem, queue = queue_env
    _seed_task(mem, queue, "m1", "old-hash")
    task = queue.claim(1)[0]
    with mem.get_connection() as conn:
        queue.enqueue(conn, "m1", "new-hash")

    assert queue.complete("m1", task.lease_token, "old-hash") is False
    rows = _rows(mem)
    assert rows[0][1] == "new-hash"
    assert rows[0][2] == "pending"


def test_complete_retires_the_task(queue_env):
    mem, queue = queue_env
    _seed_task(mem, queue, "m1", "h1")
    task = queue.claim(1)[0]

    assert queue.complete("m1", task.lease_token, "h1") is True
    assert _rows(mem) == []


def test_fail_records_the_error_and_returns_the_task_to_pending(queue_env):
    mem, queue = queue_env
    _seed_task(mem, queue, "m1")
    task = queue.claim(1)[0]

    assert queue.fail("m1", task.lease_token, "extraction_failed") is True

    row = _rows(mem)[0]
    assert row[2] == "pending"
    assert row[3] == 1
    assert row[4] == "extraction_failed"
    assert row[5] is None


def test_a_failed_task_backs_off_before_it_can_be_claimed_again(queue_env):
    """The worker drains until the queue is empty, so a task returned straight
    to pending would be re-claimed by the next loop iteration and burn every
    attempt in milliseconds."""
    mem, queue = queue_env
    _seed_task(mem, queue, "m1")
    task = queue.claim(1)[0]

    queue.fail("m1", task.lease_token, "boom")

    assert queue.claim(1) == []
    with mem.get_connection() as conn:
        state, leased_until = conn.execute(
            "SELECT state, leased_until FROM concept_index_queue"
        ).fetchone()
    assert state == "pending"
    assert leased_until is not None


def test_a_task_is_parked_at_the_attempt_cap_and_never_claimed_again(
    queue_env, monkeypatch
):
    """One poison memory must not sit at the head of the queue forever."""
    mem, queue = queue_env
    from marm_mcp_server.config.settings import CONCEPT_INDEX_MAX_ATTEMPTS

    monkeypatch.setattr(queue, "CONCEPT_INDEX_DEBOUNCE_SECONDS", 0)
    _seed_task(mem, queue, "poison")
    _seed_task(mem, queue, "healthy")

    for _ in range(CONCEPT_INDEX_MAX_ATTEMPTS):
        tasks = {task.memory_id: task for task in queue.claim(10)}
        queue.fail("poison", tasks["poison"].lease_token, "boom")
        if "healthy" in tasks:
            queue.complete("healthy", tasks["healthy"].lease_token, "h1")

    states = {row[0]: row[2] for row in _rows(mem)}
    assert states == {"poison": "parked"}
    assert queue.claim(10) == []


def test_retire_indexed_clears_covered_tasks_only(queue_env):
    """After a full build: rows it settled go, rows queued during it stay."""
    mem, queue = queue_env
    cutoff = datetime.now(timezone.utc).isoformat()
    _seed_task(mem, queue, "before-1")
    _seed_task(mem, queue, "before-2")
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE concept_index_queue SET enqueued_at = ? WHERE memory_id LIKE 'before%'",
            ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),),
        )
    _seed_task(mem, queue, "during")

    retired = queue.retire_indexed(["before-1", "before-2", "during"], cutoff)

    assert retired == 2
    assert [row[0] for row in _rows(mem)] == ["during"]


def test_retire_indexed_leaves_a_task_another_worker_holds(queue_env):
    mem, queue = queue_env
    _seed_task(mem, queue, "m1")
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE concept_index_queue SET enqueued_at = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),),
        )
    queue.claim(1)

    assert queue.retire_indexed(["m1"], datetime.now(timezone.utc).isoformat()) == 0
    assert len(_rows(mem)) == 1


def test_retire_indexed_handles_more_ids_than_sqlite_takes_parameters(queue_env):
    """A full-corpus build settles far more ids than SQLite's 999-parameter
    ceiling allows in one statement."""
    mem, queue = queue_env
    ids = [f"m{index:05d}" for index in range(1500)]
    with mem.get_connection() as conn:
        for memory_id in ids:
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp, content_hash) "
                "VALUES (?, 'sess-a', 'content', datetime('now'), 'h1')",
                (memory_id,),
            )
            queue.enqueue(conn, memory_id, "h1")
        conn.execute(
            "UPDATE concept_index_queue SET enqueued_at = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),),
        )

    retired = queue.retire_indexed(ids, datetime.now(timezone.utc).isoformat())

    assert retired == 1500
    assert _rows(mem) == []


def test_current_hashes_reports_a_missing_memory_by_omission(queue_env):
    mem, queue = queue_env
    _seed_task(mem, queue, "m1", "h1")

    assert queue.current_hashes(["m1", "gone"]) == {"m1": "h1"}
