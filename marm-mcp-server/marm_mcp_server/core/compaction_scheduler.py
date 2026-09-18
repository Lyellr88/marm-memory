from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog

from ..config.settings import (
    COMPACTION_AUTO_APPLY_ENABLED,
    COMPACTION_AUTO_APPLY_INTERVAL_MINUTES,
    COMPACTION_ENABLED,
    SCHEDULER_AVAILABLE,
)
from .memory import memory

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = structlog.get_logger()


def _maybe_start_compaction_scheduler() -> "AsyncIOScheduler | None":
    """Start the compaction maintenance APScheduler job.

    Runs whenever COMPACTION_ENABLED is true — auto-apply is optional on top.
    nudge_exhausted processing always runs so candidates are never permanently dead-ended.

    The job SCANS before it processes. Until this was added it only ever
    processed rows already in `compaction_staging`, and the only thing that put
    rows there was a write-driven trigger that fires ~24 hours before its own
    candidates are eligible — so on a store whose sessions had gone quiet the
    scheduler ran hourly against an empty table forever while real clusters sat
    unseen. FINDINGS 23. Scanning first also means anything staged this tick is
    nudged and (if enabled) auto-applied in the same tick rather than the next.
    """
    if not SCHEDULER_AVAILABLE or not COMPACTION_ENABLED:
        return None
    import asyncio

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from ..services.compaction_summarize import process_nudge_exhausted_candidates
    from .compaction import run_periodic_compaction_scan

    async def _scan() -> None:
        """Off the event loop, always.

        Finding candidates compares every pair of a session's eligible memories,
        so it is O(n^2) CPU plus synchronous SQLite reads. Running that on the
        loop would stall every request the server is serving for its duration —
        the same mistake as the runtime self-probe in FINDINGS 21, which turned a
        13 ms call into 1.04 s by blocking the loop that had to answer it.
        """
        try:
            result = await asyncio.to_thread(run_periodic_compaction_scan, memory)
        except Exception:
            # An unattended maintenance job must not take the scheduler down with
            # it; APScheduler would keep the job but the traceback would be the
            # only record, and nobody reads those until something else breaks.
            logger.exception("Periodic compaction scan failed")
            return
        if result["scanned"] or result["skipped"]:
            logger.info(
                "Periodic compaction scan",
                scanned=len(result["scanned"]),
                skipped=len(result["skipped"]),
                staged=result["staged"],
            )

    if COMPACTION_AUTO_APPLY_ENABLED:
        from ..endpoints.compaction import auto_apply_staged_summaries

        async def _job() -> None:
            await _scan()
            await process_nudge_exhausted_candidates(memory)
            await auto_apply_staged_summaries()
    else:

        async def _job() -> None:
            await _scan()
            await process_nudge_exhausted_candidates(memory)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _job,
        "interval",
        minutes=COMPACTION_AUTO_APPLY_INTERVAL_MINUTES,
        id="compaction_auto_apply",
        max_instances=1,
        # An interval job's first run is otherwise one whole interval away, so a
        # deployment that just enabled compaction sees nothing for an hour and
        # cannot tell "working" from "broken" -- which is the state this feature
        # was already in. Run once shortly after startup instead. The delay keeps
        # it out of the way of serving the first requests, the scan itself is off
        # the event loop, and the per-session fingerprint means every restart
        # after the first does almost no work.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    scheduler.start()
    logger.info(
        "Compaction scheduler started",
        interval_minutes=COMPACTION_AUTO_APPLY_INTERVAL_MINUTES,
        auto_apply=COMPACTION_AUTO_APPLY_ENABLED,
    )
    return scheduler
