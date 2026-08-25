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
    """
    if not SCHEDULER_AVAILABLE or not COMPACTION_ENABLED:
        return None
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from ..services.compaction_summarize import process_nudge_exhausted_candidates

    if COMPACTION_AUTO_APPLY_ENABLED:
        from ..endpoints.compaction import auto_apply_staged_summaries

        async def _job() -> None:
            await process_nudge_exhausted_candidates(memory)
            await auto_apply_staged_summaries()
    else:

        async def _job() -> None:
            await process_nudge_exhausted_candidates(memory)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _job,
        "interval",
        minutes=COMPACTION_AUTO_APPLY_INTERVAL_MINUTES,
        id="compaction_auto_apply",
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "Compaction scheduler started",
        interval_minutes=COMPACTION_AUTO_APPLY_INTERVAL_MINUTES,
        auto_apply=COMPACTION_AUTO_APPLY_ENABLED,
    )
    return scheduler
