import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_dry_run_jobs: dict[str, dict] = {}
_dry_run_jobs_lock = threading.Lock()
_DRY_RUN_JOB_TTL_SECONDS = 3600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prune_dry_run_jobs() -> None:
    cutoff = datetime.now(timezone.utc).timestamp() - _DRY_RUN_JOB_TTL_SECONDS
    with _dry_run_jobs_lock:
        for job_id, job in list(_dry_run_jobs.items()):
            finished_at = job.get("_finished_timestamp")
            if finished_at is not None and finished_at < cutoff:
                _dry_run_jobs.pop(job_id, None)


def _public_job(job: dict) -> dict:
    return {key: value for key, value in job.items() if not key.startswith("_")}


def _update_job(job_id: str, **fields: Any) -> None:
    """Workers run off the event loop, so every mutation takes the same lock as reads."""
    with _dry_run_jobs_lock:
        job = _dry_run_jobs.get(job_id)
        if job is not None:
            job.update(fields)


def _finish_job(job_id: str, **fields: Any) -> None:
    _update_job(
        job_id,
        **fields,
        finished_at=_now_iso(),
        _finished_timestamp=datetime.now(timezone.utc).timestamp(),
    )


def _run_compaction_dry_run_job(job_id: str, session_name: str) -> None:
    from ..cli import DEFAULT_DB_PATH, _ReadOnlyMemory
    from ..core.compaction import run_compaction_dry_run

    with _dry_run_jobs_lock:
        if job_id not in _dry_run_jobs:
            return
    _update_job(job_id, status="running", started_at=_now_iso())
    outcome: dict[str, Any]
    try:
        if not Path(DEFAULT_DB_PATH).exists():
            outcome = {"status": "success", "candidates": [], "report_path": None}
        else:
            result = run_compaction_dry_run(
                _ReadOnlyMemory(DEFAULT_DB_PATH), session_name
            )
            outcome = {
                "status": "success",
                "candidates": result.get("candidates", []),
                "report_path": result.get("report_path"),
            }
    except Exception as exc:
        logger.error("Compaction dry run failed", exc_info=True)
        outcome = {"status": "error", "error": str(exc)}
    _finish_job(job_id, **outcome)
