"""Background worker that turns stored memories into concept graph nodes.

Runs in-process on both transports. It owns no state that matters: every task
is a durable row in concept_index_queue, so a killed worker loses nothing and
teardown only has to stop it, never wait for it. That is the opposite of the
chunk drain in memory_utils, which must finish because its work exists only
in RAM.

Failure here degrades the graph and never the memory. Extraction problems
retry, a poison memory parks after CONCEPT_INDEX_MAX_ATTEMPTS, and no path
from this module can block a write or a recall.
"""

import asyncio
import threading
from typing import Optional

import structlog

from ..config.settings import (
    CONCEPT_AUTO_INDEX,
    CONCEPT_INDEX_BATCH_PAUSE_MS,
    CONCEPT_INDEX_BATCH_SIZE,
    CONCEPT_INDEX_DEBOUNCE_SECONDS,
    CONCEPT_INDEX_LEASE_SECONDS,
    CONCEPTS_AVAILABLE,
)
from . import concept_queue
from .concept_build_lock import BuildLease, ConceptBuildBusy, concept_build_lock

logger = structlog.get_logger(__name__)


class ConceptIndexWorker:
    """Lazy singleton, mirroring graph_supervisor's shape for optional
    subsystems. start() and stop() are both idempotent."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._active_lease: Optional[BuildLease] = None
        self._cycles = 0
        self._indexed = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Never raises. A worker that cannot run leaves the queue filling,
        which is recoverable; a worker that breaks startup is not."""
        if self.running:
            return
        if not CONCEPT_AUTO_INDEX:
            logger.info("concept_worker.disabled", reason="CONCEPT_AUTO_INDEX=false")
            return
        if not CONCEPTS_AVAILABLE:
            # Dormant, not spinning. Claiming tasks we cannot extract would
            # burn the attempt budget and park every memory written while the
            # extraction runtime is missing.
            logger.info("concept_worker.dormant", reason="concepts_unavailable")
            return
        try:
            self._stop.clear()
            self._task = asyncio.get_running_loop().create_task(self._run())
            logger.info(
                "concept_worker.started",
                debounce_seconds=CONCEPT_INDEX_DEBOUNCE_SECONDS,
                batch_size=CONCEPT_INDEX_BATCH_SIZE,
            )
        except RuntimeError as exc:
            logger.warning("concept_worker.start_failed", error=str(exc))

    async def stop(self) -> None:
        """Signal and return. Deliberately does not wait for an in-flight
        extraction: the task is a durable row and the next run picks it up,
        so waiting would only reintroduce the shutdown delay v2.35.0 bounded.

        Signals the in-flight build first. Cancelling the task only cancels
        the await around asyncio.to_thread; the extraction thread keeps
        running and keeps writing, while unwinding releases the cross-process
        graph lock. Another transport could then take the lock and reset the
        concept database underneath that thread. Raising the flag first makes
        the thread stop at its next memory instead, which costs no shutdown
        time because it is not awaited."""
        lease = self._active_lease
        if lease is not None:
            lease.lost.set()
        self._stop.set()
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("concept_worker.stop_error", error=str(exc))
        logger.info("concept_worker.stopped", cycles=self._cycles)

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self._wait(CONCEPT_INDEX_DEBOUNCE_SECONDS)
            if self._stop.is_set():
                return
            self._cycles += 1
            try:
                await self._drain()
            except Exception as exc:
                # One bad cycle must never end the loop. The queue is durable,
                # so the next cycle retries whatever was left.
                logger.warning("concept_worker.cycle_failed", error=str(exc))

    async def _wait(self, seconds: float) -> bool:
        """Sleep unless stopped first. Returns whether a stop arrived."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            return True
        except (asyncio.TimeoutError, TimeoutError):
            return False

    async def _drain(self) -> None:
        """Claim and process back to back until the queue is empty.

        Waiting between batches instead would cap throughput at one batch per
        debounce interval, which on the defaults is 40 memories a minute: a
        backlog would never catch up.

        The cross-process lock is taken per batch rather than around the whole
        drain, so a manual build can get in between batches instead of waiting
        out a long backlog. Taking it before claiming means a busy cycle leaves
        nothing claimed and nothing stranded behind an unused lease.
        """
        while not self._stop.is_set():
            try:
                async with concept_build_lock(
                    "auto_index", CONCEPT_INDEX_LEASE_SECONDS
                ) as lease:
                    # Published so stop() can signal a build that is already
                    # running in a thread it cannot cancel.
                    self._active_lease = lease
                    tasks = await asyncio.to_thread(
                        concept_queue.claim, CONCEPT_INDEX_BATCH_SIZE
                    )
                    if not tasks:
                        return
                    # The task leases run on the same clock as the build lock,
                    # so a batch that outlives the TTL would be reclaimed and
                    # extracted a second time by another process.
                    try:
                        async with concept_queue.keep_claimed(
                            tasks, CONCEPT_INDEX_LEASE_SECONDS
                        ):
                            await self._process(tasks, lease.lost)
                    finally:
                        self._active_lease = None
                    if lease.lost.is_set():
                        return
            except ConceptBuildBusy:
                logger.info("concept_worker.deferred", reason="graph_busy")
                return

            # After the lock is released, so the pause also hands a waiting
            # manual build a clean window rather than only yielding CPU.
            if CONCEPT_INDEX_BATCH_PAUSE_MS and await self._wait(
                CONCEPT_INDEX_BATCH_PAUSE_MS / 1000
            ):
                return

    async def _process(
        self,
        tasks: list[concept_queue.ClaimedTask],
        abort: Optional[threading.Event] = None,
    ) -> None:
        from ..endpoints.concepts import build_for_memory_ids

        memory_ids = [task.memory_id for task in tasks]
        outcomes = await build_for_memory_ids(memory_ids, abort=abort)

        if abort is not None and abort.is_set():
            # The graph belongs to another process now and this batch stopped
            # partway. Settling any of it would either delete a task whose
            # extraction never ran or spend an attempt on a memory that never
            # failed. Leave every lease to expire and be retried.
            logger.error("concept_worker.batch_abandoned", tasks=len(tasks))
            return

        live = await asyncio.to_thread(concept_queue.current_hashes, memory_ids)

        for task in tasks:
            if task.memory_id not in live:
                await self._retract(task, "deleted")
                await asyncio.to_thread(
                    concept_queue.drop, task.memory_id, task.lease_token
                )
                continue
            # A NULL stored hash cannot be compared, and treating it as a
            # mismatch is worse than not checking: the task is never settled
            # and never counted as a failure, so the worker re-extracts that
            # memory forever without ever writing it or giving up. Rows
            # predating the content_hash column are exactly this case.
            if live[task.memory_id] is not None and (
                live[task.memory_id] != task.content_hash
            ):
                # Content changed under us. The write that changed it already
                # re-queued the memory, so leave that row alone and let the
                # next cycle index the current content.
                #
                # Deliberately no retraction here. cleanup_deleted_memory_
                # provenance removes ALL provenance for a memory id, not just
                # what this build wrote, so retracting would also erase what a
                # worker in the other process may have already written for the
                # new content, leaving the graph empty for this memory with no
                # queue row left to repair it. The cost of not retracting is
                # entities from the previous text lingering, which is the
                # staleness this feature already documents.
                logger.info("concept_worker.superseded", memory_id=task.memory_id)
                continue

            outcome = outcomes.get(task.memory_id, "failed")
            if outcome in ("indexed", "no_entities"):
                await asyncio.to_thread(
                    concept_queue.complete,
                    task.memory_id,
                    task.lease_token,
                    task.content_hash,
                )
                if outcome == "indexed":
                    self._indexed += 1
            elif outcome == "vanished":
                await asyncio.to_thread(
                    concept_queue.drop, task.memory_id, task.lease_token
                )
            else:
                await asyncio.to_thread(
                    concept_queue.fail,
                    task.memory_id,
                    task.lease_token,
                    "extraction_failed",
                )

    async def _retract(self, task: concept_queue.ClaimedTask, reason: str) -> None:
        """Undo provenance for a memory that was deleted while its extraction
        was in flight.

        Dequeue-on-delete alone cannot cover this. The build reads the memory
        DB and then writes the concept DB, and a delete can commit and run its
        own concept cleanup inside that gap, so without this the entities the
        user asked to be gone reappear after the cleanup that was supposed to
        remove them.

        Only for deletes. The memory is gone, so no other worker can be
        indexing it and there is nothing here worth keeping.
        """
        from ..endpoints.concepts import _get_concept_db

        try:
            await asyncio.to_thread(
                lambda: _get_concept_db().cleanup_deleted_memory_provenance(
                    [task.memory_id]
                )
            )
            logger.info(
                "concept_worker.retracted", memory_id=task.memory_id, reason=reason
            )
        except Exception as exc:
            logger.warning("concept_worker.retract_failed", error=str(exc))

    def status(self) -> dict:
        return {
            "running": self.running,
            "enabled": CONCEPT_AUTO_INDEX,
            "cycles": self._cycles,
            "memories_indexed": self._indexed,
        }


concept_worker = ConceptIndexWorker()
