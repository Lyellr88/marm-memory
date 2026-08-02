"""Tests for the background concept indexing worker.

The worker's job is to settle durable queue rows correctly. Most of these
tests therefore assert on what is left in the queue and in the graph after a
cycle, not on how many times something was called. Real SQLite throughout;
extract_entities is monkeypatched at the endpoints module boundary, the same
convention the other concept tests use, because spaCy's model is not
installable in this sandbox.
"""

import asyncio
import importlib
import sys

import pytest
from conftest import load_isolated_server


@pytest.fixture
def worker_env(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(tmp_path / "marm_index.db"))
    concepts = importlib.import_module("marm_mcp_server.endpoints.concepts")
    worker_module = importlib.import_module("marm_mcp_server.core.concept_worker")
    queue = importlib.import_module("marm_mcp_server.core.concept_queue")
    memory_module = sys.modules["marm_mcp_server.core.memory"]

    monkeypatch.setattr(concepts, "CONCEPTS_AVAILABLE", True)
    monkeypatch.setattr(concepts, "is_graph_available", lambda: False)
    monkeypatch.setattr(worker_module, "CONCEPTS_AVAILABLE", True)
    monkeypatch.setattr(worker_module, "CONCEPT_AUTO_INDEX", True)
    monkeypatch.setattr(worker_module, "CONCEPT_INDEX_DEBOUNCE_SECONDS", 0.01)

    worker = worker_module.ConceptIndexWorker()
    return worker, worker_module, concepts, queue, memory_module.memory


def _extract_named_after_content(monkeypatch, concepts, failing=()):
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    def fake(content):
        if content in failing:
            raise RuntimeError("extraction failed")
        if not content.strip():
            return ExtractionResult(entities=[], relationship_pairs=[])
        return ExtractionResult(
            entities=[Entity(content, "concept")], relationship_pairs=[]
        )

    monkeypatch.setattr(concepts, "extract_entities", fake)


def _queue_rows(mem):
    with mem.get_connection() as conn:
        return conn.execute(
            "SELECT memory_id, state, attempts FROM concept_index_queue"
        ).fetchall()


def _entity_names(concepts):
    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        return {row[0] for row in conn.execute("SELECT name FROM entities").fetchall()}


def test_a_stored_memory_becomes_a_node_without_anyone_asking(worker_env, monkeypatch):
    """The whole feature in one test: store, wait, the node exists and the
    task is gone."""
    worker, _module, concepts, _queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)

    async def scenario():
        await mem.store_memory("the write queue serializes writes", "s1")
        worker.start()
        for _ in range(200):
            await asyncio.sleep(0.01)
            if not _queue_rows(mem):
                break
        await worker.stop()

    asyncio.run(scenario())

    assert _queue_rows(mem) == []
    assert "the write queue serializes writes" in _entity_names(concepts)


def test_a_backlog_drains_continuously_instead_of_one_batch_per_interval(
    worker_env, monkeypatch
):
    """Claiming one batch then waiting again would cap throughput at
    CONCEPT_INDEX_BATCH_SIZE per debounce interval. With the shipped defaults
    that is 40 memories a minute and a backlog never catches up."""
    worker, module, concepts, _queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)
    monkeypatch.setattr(module, "CONCEPT_INDEX_BATCH_SIZE", 5)
    monkeypatch.setattr(module, "CONCEPT_INDEX_DEBOUNCE_SECONDS", 30)

    async def scenario():
        for index in range(50):
            await mem.store_memory(f"memory number {index}", "s1")
        # One cycle only. Reaching all 50 proves the drain loops rather than
        # returning to the (30 second) wait after its first batch.
        await worker._drain()

    asyncio.run(scenario())

    assert _queue_rows(mem) == []
    assert len(_entity_names(concepts)) == 50


def test_a_failed_extraction_keeps_the_task_and_records_the_error(
    worker_env, monkeypatch
):
    worker, _module, concepts, _queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts, failing={"poison content"})

    async def scenario():
        good = await mem.store_memory("healthy content", "s1")
        bad = await mem.store_memory("poison content", "s1")
        await worker._drain()
        return good, bad

    _good, bad = asyncio.run(scenario())

    rows = {row[0]: row for row in _queue_rows(mem)}
    assert list(rows) == [bad]
    assert rows[bad][1] == "pending"
    assert rows[bad][2] == 1
    assert "healthy content" in _entity_names(concepts)


def test_a_memory_deleted_mid_extraction_leaves_nothing_in_the_graph(
    worker_env, monkeypatch
):
    """Dequeue-on-delete cannot cover this on its own. The build reads the
    memory DB and then writes the concept DB, and a delete can commit and run
    its own cleanup inside that gap, so the entities the user asked to remove
    would reappear behind it."""
    from marm_mcp_server.core.memory_delete import _delete_memories

    worker, _module, concepts, queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)

    async def scenario():
        memory_id = await mem.store_memory("doomed content", "s1")
        real_build = concepts.build_for_memory_ids

        async def build_then_delete(memory_ids, abort=None):
            outcomes = await real_build(memory_ids, abort=abort)
            await _delete_memories(mem, [memory_id])
            return outcomes

        monkeypatch.setattr(concepts, "build_for_memory_ids", build_then_delete)
        tasks = await asyncio.to_thread(queue.claim, 10)
        await worker._process(tasks)

    asyncio.run(scenario())

    assert _queue_rows(mem) == []
    assert _entity_names(concepts) == set()


def test_a_memory_merged_mid_extraction_is_reindexed_not_settled(
    worker_env, monkeypatch
):
    """Settling on the old hash would leave the graph describing text that is
    only part of the memory, with nothing queued to correct it."""
    worker, _module, concepts, queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)

    async def scenario():
        memory_id = await mem.store_memory("original content", "s1")
        real_build = concepts.build_for_memory_ids

        async def build_then_merge(memory_ids, abort=None):
            outcomes = await real_build(memory_ids, abort=abort)
            await mem.update_memory(memory_id, "appended content")
            return outcomes

        monkeypatch.setattr(concepts, "build_for_memory_ids", build_then_merge)
        # One batch, not a full drain: the assertion is about what the worker
        # does with a result that arrived after the memory moved on.
        tasks = await asyncio.to_thread(queue.claim, 10)
        await worker._process(tasks)
        return memory_id

    memory_id = asyncio.run(scenario())

    rows = _queue_rows(mem)
    assert [row[0] for row in rows] == [memory_id]
    assert rows[0][1] == "pending"
    assert rows[0][2] == 0


def test_a_superseded_result_does_not_wipe_another_workers_fresh_provenance(
    worker_env, monkeypatch
):
    """Two processes, one memory. Worker A is extracting the old content when
    the memory is rewritten; worker B indexes the new content and finishes
    first. cleanup_deleted_memory_provenance removes ALL provenance for a
    memory id, so if A retracted on finding the hash changed it would erase
    B's current graph data, with A's queue row already gone and nothing left
    to repair it."""
    worker, _module, concepts, queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)

    async def scenario():
        memory_id = await mem.store_memory("original content", "s1")
        stale = await asyncio.to_thread(queue.claim, 10)

        # Stand in for the rewrite plus worker B: the memory now holds new
        # content and its entities are already in the graph.
        await mem.update_memory(memory_id, "appended content")
        fresh = await asyncio.to_thread(queue.claim, 10)
        await worker._process(fresh)

        # Worker A only now returns, holding a result for text that is gone.
        await worker._process(stale)
        return memory_id

    asyncio.run(scenario())

    names = _entity_names(concepts)
    assert any("appended content" in name for name in names), (
        f"the current content's entities were erased by a stale result: {names}"
    )


def test_losing_the_graph_lock_stops_the_build_at_the_next_memory(
    worker_env, monkeypatch
):
    """A process stalled past its whole lease loses the lock to someone else.
    The running thread cannot be killed from outside, so the build has to stop
    cooperatively instead of writing alongside the new owner for however long
    it had left."""
    import threading

    _worker, _module, concepts, _queue, mem = worker_env
    lost = threading.Event()
    seen = []

    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    def fake(content):
        seen.append(content)
        lost.set()  # the lock goes at the first memory
        return ExtractionResult(
            entities=[Entity(content, "concept")], relationship_pairs=[]
        )

    monkeypatch.setattr(concepts, "extract_entities", fake)

    async def scenario():
        for index in range(5):
            await mem.store_memory(f"memory number {index}", "s1")
        pages = concepts._fetch_memory_pages(None, None, True)
        return await asyncio.to_thread(concepts._run_build, pages, None, lost)

    result = asyncio.run(scenario())

    assert result["aborted"] is True
    assert len(seen) == 1, f"the build kept going after losing the lock: {seen}"
    assert result["memories_processed"] == 1


def test_an_abandoned_batch_settles_nothing(worker_env, monkeypatch):
    """Settling part of an abandoned batch would either delete a task whose
    extraction never ran, or spend an attempt on a memory that never failed."""
    import threading

    worker, _module, concepts, queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)
    lost = threading.Event()

    async def scenario():
        for index in range(3):
            await mem.store_memory(f"memory number {index}", "s1")
        tasks = await asyncio.to_thread(queue.claim, 10)

        real_build = concepts.build_for_memory_ids

        async def build_then_lose(memory_ids, abort=None):
            lost.set()
            return await real_build(memory_ids, abort=abort)

        monkeypatch.setattr(concepts, "build_for_memory_ids", build_then_lose)
        await worker._process(tasks, lost)
        return tasks

    tasks = asyncio.run(scenario())

    rows = {row[0]: row for row in _queue_rows(mem)}
    assert len(rows) == len(tasks), "an abandoned batch settled some of its tasks"
    assert all(row[2] == 0 for row in rows.values()), (
        "an abandoned batch spent attempts on memories that never failed"
    )


def test_a_manual_build_that_loses_the_lock_reports_it_rather_than_success(
    worker_env, monkeypatch
):
    """Reporting success would also retire the queue rows for memories this
    build never reached."""
    import threading

    from marm_mcp_server.core.models import ConceptBuildRequest

    _worker, _module, concepts, _queue, mem = worker_env
    lost = threading.Event()
    _extract_named_after_content(monkeypatch, concepts)

    async def scenario():
        await mem.store_memory("some content to index", "s1")
        lost.set()
        return await concepts._marm_concept_build(
            ConceptBuildRequest(search_all=True), lost
        )

    result = asyncio.run(scenario())

    assert result["error_code"] == "lock_lost"
    assert len(_queue_rows(mem)) == 1, "an aborted build retired a queue row"


def test_a_memory_with_no_entities_is_finished_not_retried(worker_env, monkeypatch):
    worker, _module, concepts, _queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)

    async def scenario():
        memory_id = await mem.store_memory("some content", "s1")
        with mem.get_connection() as conn:
            conn.execute(
                "UPDATE memories SET content = '   ' WHERE id = ?", (memory_id,)
            )
        await worker._drain()

    asyncio.run(scenario())

    assert _queue_rows(mem) == []


def test_one_bad_cycle_does_not_kill_the_loop(worker_env, monkeypatch):
    worker, _module, concepts, _queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)
    calls = {"n": 0}
    real_drain = worker._drain

    async def flaky_drain():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("cycle exploded")
        await real_drain()

    monkeypatch.setattr(worker, "_drain", flaky_drain)

    async def scenario():
        await mem.store_memory("content that must still be indexed", "s1")
        worker.start()
        for _ in range(300):
            await asyncio.sleep(0.01)
            if calls["n"] >= 2 and not _queue_rows(mem):
                break
        await worker.stop()

    asyncio.run(scenario())

    assert calls["n"] >= 2
    assert _queue_rows(mem) == []


def test_stop_returns_without_waiting_for_an_in_flight_extraction(
    worker_env, monkeypatch
):
    """Teardown must not put spaCy on the shutdown path. The task is a durable
    row and the next run picks it up."""
    worker, _module, concepts, _queue, mem = worker_env
    entered = asyncio.Event()

    async def slow_build(memory_ids, abort=None):
        entered.set()
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr(concepts, "build_for_memory_ids", slow_build)

    async def scenario():
        await mem.store_memory("content", "s1")
        worker.start()
        await asyncio.wait_for(entered.wait(), timeout=5)
        await asyncio.wait_for(worker.stop(), timeout=2)
        return worker.running

    assert asyncio.run(scenario()) is False
    assert len(_queue_rows(mem)) == 1


def test_disabled_worker_leaves_the_queue_filling(worker_env, monkeypatch):
    worker, module, _concepts, _queue, mem = worker_env
    monkeypatch.setattr(module, "CONCEPT_AUTO_INDEX", False)

    async def scenario():
        await mem.store_memory("content", "s1")
        worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()

    asyncio.run(scenario())

    assert worker.running is False
    assert len(_queue_rows(mem)) == 1


def test_worker_stays_dormant_when_extraction_is_unavailable(worker_env, monkeypatch):
    """Claiming tasks it cannot extract would burn the attempt budget and park
    every memory written while the runtime is missing."""
    worker, module, _concepts, _queue, mem = worker_env
    monkeypatch.setattr(module, "CONCEPTS_AVAILABLE", False)

    async def scenario():
        await mem.store_memory("content", "s1")
        worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()

    asyncio.run(scenario())

    assert worker.running is False
    rows = _queue_rows(mem)
    assert len(rows) == 1
    assert rows[0][2] == 0


def test_a_graph_awaiting_rebuild_does_not_get_incremental_writes(
    worker_env, monkeypatch
):
    """On upgrade every install starts in rebuild_required, so this is the
    normal state until the user runs a full build, not a rare edge."""
    worker, _module, concepts, _queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)

    async def scenario():
        await mem.store_memory("content", "s1")
        concept_db = concepts._get_concept_db()
        with concept_db.get_connection() as conn:
            conn.execute(
                "UPDATE concept_schema_metadata SET value = '1' "
                "WHERE key = 'schema_version'"
            )
        # The loop swallows the refusal so it can retry after a rebuild.
        worker.start()
        await asyncio.sleep(0.1)
        await worker.stop()

    asyncio.run(scenario())

    assert len(_queue_rows(mem)) == 1
    assert _entity_names(concepts) == set()


def test_start_is_idempotent(worker_env):
    worker, _module, _concepts, _queue, _mem = worker_env

    async def scenario():
        worker.start()
        first = worker._task
        worker.start()
        same = worker._task is first
        await worker.stop()
        return same

    assert asyncio.run(scenario()) is True


def test_stop_is_safe_when_never_started(worker_env):
    worker, _module, _concepts, _queue, _mem = worker_env
    asyncio.run(worker.stop())
    assert worker.running is False
