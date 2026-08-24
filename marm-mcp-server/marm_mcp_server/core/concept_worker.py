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
from . import code_link_queue, concept_queue
from .concept_build_lock import BuildLease, ConceptBuildBusy, concept_build_lock

logger = structlog.get_logger(__name__)

# How long stop() waits for an aborted extraction to actually stop before
# releasing the graph anyway. Short on purpose: teardown must stay bounded.
ABORT_GRACE_SECONDS = 2.0


class ConceptIndexWorker:
    """Lazy singleton, mirroring graph_supervisor's shape for optional
    subsystems. start() and stop() are both idempotent."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._active_lease: Optional[BuildLease] = None
        self._build_finished: Optional[threading.Event] = None
        self._cycles = 0
        self._indexed = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @staticmethod
    def enabled() -> bool:
        """A saved override beats the environment variable, so a
        CONCEPT_AUTO_INDEX baked into a Dockerfile cannot silently re-enable
        something the user turned off."""
        from . import runtime_flags

        return runtime_flags.get_bool(
            runtime_flags.AUTO_INDEX_CONCEPT, CONCEPT_AUTO_INDEX
        )

    def start(self) -> None:
        """Never raises. A worker that cannot run leaves the queue filling,
        which is recoverable; a worker that breaks startup is not."""
        if self.running:
            return
        if not self.enabled():
            # The loop still starts, and each cycle re-checks the flag and does
            # nothing. That costs one indexed SELECT per debounce interval and
            # is what lets `knowledge auto on` take effect without a restart:
            # the switch is written to the database by a separate process, which
            # cannot start a task in this one.
            logger.info("concept_worker.idle", reason="auto_index_off")
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
        in_flight = self._build_finished
        if lease is not None:
            lease.lost.set()
        self._stop.set()

        if in_flight is not None and not in_flight.is_set():
            # Bounded, and it has to be. Cancelling below unwinds the lock and
            # releases it, but the extraction thread cannot be cancelled and
            # keeps writing until it notices the flag above. Releasing the graph
            # while that is true lets another process rebuild underneath it.
            #
            # Waiting the whole extraction out would put spaCy back on the
            # teardown path, which v2.35.0 deliberately bounded, so this waits
            # only for the flag to land and then proceeds regardless. Past the
            # grace period the worst case is stray entities or a logged write
            # failure in a graph another process now owns, not corruption.
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(in_flight.wait, ABORT_GRACE_SECONDS),
                    timeout=ABORT_GRACE_SECONDS + 1,
                )
            except (asyncio.TimeoutError, TimeoutError):
                pass
            if not in_flight.is_set():
                logger.warning(
                    "concept_worker.extraction_still_running",
                    grace_seconds=ABORT_GRACE_SECONDS,
                )

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
            if not self.enabled():
                # Re-read per cycle, not once at start(): the flag can be
                # turned off at runtime and an off switch that needed a restart
                # would not be an off switch. Tasks stay queued and durable.
                continue
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
                    if tasks:
                        # The task leases run on the same clock as the build lock,
                        # so a batch that outlives the TTL would be reclaimed and
                        # extracted a second time by another process.
                        build_finished = threading.Event()
                        self._build_finished = build_finished
                        try:
                            async with concept_queue.keep_claimed(
                                tasks, CONCEPT_INDEX_LEASE_SECONDS
                            ):
                                await self._process(tasks, lease.lost, build_finished)
                        finally:
                            self._active_lease = None
                            self._build_finished = None
                    else:
                        refreshes = await asyncio.to_thread(code_link_queue.claim, 1)
                        if not refreshes:
                            return
                        async with code_link_queue.keep_claimed(
                            refreshes, CONCEPT_INDEX_LEASE_SECONDS
                        ):
                            await self._refresh_code_links(refreshes[0], lease.lost)
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
        finished: Optional[threading.Event] = None,
    ) -> None:
        from ..endpoints.concepts import build_for_memory_ids

        memory_ids = [task.memory_id for task in tasks]
        outcomes = await build_for_memory_ids(
            memory_ids, abort=abort, finished=finished
        )

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

    async def _refresh_code_links(
        self,
        task: code_link_queue.ClaimedRefresh,
        abort: threading.Event,
    ) -> None:
        """Re-resolve one bounded entity page without re-running extraction."""
        from ..services.concept_build_engine import _get_concept_db
        from .code_project_bindings import get_by_graph_project
        from .graph_client import find_code_match

        binding = await asyncio.to_thread(get_by_graph_project, task.graph_project)
        if (
            binding is None
            or binding.memory_project != task.memory_project
            or binding.root_path != task.root_path
        ):
            await asyncio.to_thread(code_link_queue.complete, task)
            return

        concept_db = _get_concept_db()
        retry_reason: str | None = None
        with concept_db.get_connection() as conn:
            entities = concept_db.entities_for_project(
                conn,
                task.memory_project,
                task.cursor_entity_id,
                CONCEPT_INDEX_BATCH_SIZE,
            )
            for entity_id, name in entities:
                if abort.is_set():
                    return
                outcome = await asyncio.to_thread(
                    find_code_match, name, task.graph_project
                )
                if outcome.get("status") in {"unavailable", "ambiguous"}:
                    retry_reason = str(outcome.get("status"))
                    break
                concept_db.reconcile_code_link(
                    conn, entity_id, task.graph_project, outcome
                )

        if abort.is_set():
            return
        if retry_reason is not None:
            await asyncio.to_thread(code_link_queue.fail, task, retry_reason)
        elif len(entities) == CONCEPT_INDEX_BATCH_SIZE:
            await asyncio.to_thread(code_link_queue.advance, task, entities[-1][0])
        else:
            await asyncio.to_thread(code_link_queue.complete, task)

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
        from ..services.concept_build_engine import _get_concept_db

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
            "enabled": self.enabled(),
            "cycles": self._cycles,
            "memories_indexed": self._indexed,
            "code_link_refresh": code_link_queue.counts(),
        }


concept_worker = ConceptIndexWorker()
