import asyncio
import importlib
import sys
import time

import pytest
from conftest import load_isolated_server

from marm_mcp_server.core.memory_ops import _update_memory


@pytest.fixture
def worker_env(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(tmp_path / "marm_index.db"))
    concepts = importlib.import_module("marm_mcp_server.endpoints.concepts")
    worker_module = importlib.import_module("marm_mcp_server.core.concept_worker")
    queue = importlib.import_module("marm_mcp_server.core.concept_queue")
    memory_module = sys.modules["marm_mcp_server.core.memory"]

    monkeypatch.setattr(concepts, "CONCEPTS_AVAILABLE", True)
    monkeypatch.setattr(worker_module, "CONCEPTS_AVAILABLE", True)
    monkeypatch.setattr(worker_module, "CONCEPT_AUTO_INDEX", True)
    monkeypatch.setattr(worker_module, "CONCEPT_INDEX_DEBOUNCE_SECONDS", 0.01)
    monkeypatch.setattr(worker_module, "CONCEPT_INDEX_BATCH_PAUSE_MS", 0)

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

    concept_build_engine = importlib.import_module(
        "marm_mcp_server.services.concept_build_engine"
    )
    monkeypatch.setattr(concept_build_engine, "extract_entities", fake)


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

        async def build_then_delete(memory_ids, abort=None, finished=None):
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

        async def build_then_merge(memory_ids, abort=None, finished=None):
            outcomes = await real_build(memory_ids, abort=abort)
            await _update_memory(mem, memory_id, "appended content")
            return outcomes

        monkeypatch.setattr(concepts, "build_for_memory_ids", build_then_merge)
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

        await _update_memory(mem, memory_id, "appended content")
        fresh = await asyncio.to_thread(queue.claim, 10)
        await worker._process(fresh)

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
        lost.set()
        return ExtractionResult(
            entities=[Entity(content, "concept")], relationship_pairs=[]
        )

    concept_build_engine = importlib.import_module(
        "marm_mcp_server.services.concept_build_engine"
    )
    monkeypatch.setattr(concept_build_engine, "extract_entities", fake)

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

        async def build_then_lose(memory_ids, abort=None, finished=None):
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
    row and the next run picks it up.

    stop() does give an aborted extraction a short grace period to stop
    writing before the graph lock is released, so this asserts the bound rather
    than an instant return: it must not wait out a build that ignores the
    abort, which here sleeps far longer than the grace."""
    worker, module, concepts, _queue, mem = worker_env
    monkeypatch.setattr(module, "ABORT_GRACE_SECONDS", 0.3)
    entered = asyncio.Event()

    async def slow_build(memory_ids, abort=None, finished=None):
        entered.set()
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr(concepts, "build_for_memory_ids", slow_build)

    async def scenario():
        await mem.store_memory("content", "s1")
        worker.start()
        await asyncio.wait_for(entered.wait(), timeout=5)
        started = asyncio.get_running_loop().time()
        await asyncio.wait_for(worker.stop(), timeout=5)
        return worker.running, asyncio.get_running_loop().time() - started

    running, elapsed = asyncio.run(scenario())

    assert running is False
    assert elapsed < 3, f"stop() waited {elapsed:.1f}s on a build that ignored abort"
    assert len(_queue_rows(mem)) == 1


def test_stop_signals_the_running_build_before_releasing_the_graph(
    worker_env, monkeypatch
):
    """Cancelling the task only cancels the await around asyncio.to_thread. The
    extraction thread keeps writing while unwinding releases the cross-process
    lock, so another transport could reset the concept database underneath it.
    stop() has to raise the abort flag first."""
    worker, _module, concepts, _queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)
    seen = {}

    async def slow_build(memory_ids, abort=None, finished=None):
        seen["abort"] = abort
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr(concepts, "build_for_memory_ids", slow_build)

    async def scenario():
        await mem.store_memory("content being indexed", "s1")
        worker.start()
        for _ in range(200):
            await asyncio.sleep(0.01)
            if "abort" in seen:
                break
        await worker.stop()

    asyncio.run(scenario())

    assert seen.get("abort") is not None, "the build was given no way to stop"
    assert seen["abort"].is_set(), "stop() released the graph without signalling"


def test_stop_holds_the_graph_until_the_extraction_thread_stops(
    worker_env, monkeypatch
):
    """The abort flag alone is not enough. Cancelling unwinds the lock and
    releases it, so without waiting for the thread to acknowledge, another
    process can take the graph while this one is still writing."""
    import threading

    worker, module, concepts, _queue, mem = worker_env
    monkeypatch.setattr(module, "ABORT_GRACE_SECONDS", 3.0)
    released_while_running = []
    still_running = threading.Event()
    still_running.set()

    async def slow_build(memory_ids, abort=None, finished=None):
        def work():
            abort.wait(5)
            time.sleep(0.4)
            still_running.clear()
            if finished is not None:
                finished.set()

        await asyncio.to_thread(work)
        return {}

    monkeypatch.setattr(concepts, "build_for_memory_ids", slow_build)

    from marm_mcp_server.core import concept_build_lock

    real_release = concept_build_lock.release

    def watching_release(holder):
        if still_running.is_set():
            released_while_running.append(holder)
        return real_release(holder)

    monkeypatch.setattr(concept_build_lock, "release", watching_release)

    async def scenario():
        await mem.store_memory("content being indexed", "s1")
        worker.start()
        for _ in range(300):
            await asyncio.sleep(0.01)
            if worker._build_finished is not None:
                break
        await worker.stop()

    asyncio.run(scenario())

    assert released_while_running == [], (
        "the graph lock was released while extraction was still writing"
    )


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
        worker.start()
        await asyncio.sleep(0.1)
        await worker.stop()

    asyncio.run(scenario())

    assert len(_queue_rows(mem)) == 1
    assert _entity_names(concepts) == set()


def test_the_inter_batch_pause_actually_pauses(worker_env, monkeypatch):
    """Measured, not assumed: at the shipped batch size the pause cuts the
    worst-case recall during a drain from roughly 270ms to 80ms, and it can
    only do that if it is really yielding between batches."""
    worker, module, concepts, _queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)
    monkeypatch.setattr(module, "CONCEPT_INDEX_BATCH_SIZE", 1)
    monkeypatch.setattr(module, "CONCEPT_INDEX_BATCH_PAUSE_MS", 120)

    async def scenario():
        for index in range(4):
            await mem.store_memory(f"memory number {index}", "s1")
        start = asyncio.get_running_loop().time()
        await worker._drain()
        return asyncio.get_running_loop().time() - start

    elapsed = asyncio.run(scenario())

    assert _queue_rows(mem) == []
    assert elapsed >= 0.36, f"drain took {elapsed:.3f}s, the pause did not apply"


def test_a_stop_during_the_pause_is_not_ignored(worker_env, monkeypatch):
    """Shutdown must not wait out a pause it could skip."""
    worker, module, concepts, _queue, mem = worker_env
    _extract_named_after_content(monkeypatch, concepts)
    monkeypatch.setattr(module, "CONCEPT_INDEX_BATCH_SIZE", 1)
    monkeypatch.setattr(module, "CONCEPT_INDEX_BATCH_PAUSE_MS", 30_000)

    async def scenario():
        for index in range(3):
            await mem.store_memory(f"memory number {index}", "s1")
        drain = asyncio.create_task(worker._drain())
        await asyncio.sleep(0.2)
        worker._stop.set()
        await asyncio.wait_for(drain, timeout=5)

    asyncio.run(scenario())


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
