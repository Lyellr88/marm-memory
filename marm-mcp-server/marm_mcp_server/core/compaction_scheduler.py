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

    The job SCANS before it processes, so a session that has gone quiet is
    still reached — the write-driven trigger fires before its own candidates
    are eligible — and anything staged this tick is handled in the same tick.
    """
    if not SCHEDULER_AVAILABLE or not COMPACTION_ENABLED:
        return None
    import asyncio

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from ..services.compaction_summarize import process_nudge_exhausted_candidates
    from .compaction import run_periodic_compaction_scan

    async def _scan() -> None:
        """Off the event loop, always: the candidate search is O(n^2) CPU plus
        synchronous SQLite reads, and would stall every request alongside it."""
        try:
            result = await asyncio.to_thread(run_periodic_compaction_scan, memory)
        except Exception:
            # An unattended maintenance job must not take the scheduler down.
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
        # An interval job's first run is otherwise a whole interval away, so a
        # deployment that just enabled compaction cannot tell working from
        # broken for an hour. The delay keeps it clear of the first requests.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    scheduler.start()
    logger.info(
        "Compaction scheduler started",
        interval_minutes=COMPACTION_AUTO_APPLY_INTERVAL_MINUTES,
        auto_apply=COMPACTION_AUTO_APPLY_ENABLED,
    )
    return scheduler
