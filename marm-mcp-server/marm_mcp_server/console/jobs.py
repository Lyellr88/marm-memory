"""Small in-process job registry: one running job per group, finished jobs pruned after a TTL."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 3600


class JobRegistry:
    def __init__(self, thread_name: str, ttl_seconds: float = JOB_TTL_SECONDS) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._thread_name = thread_name
        self._ttl = ttl_seconds

    def _prune(self) -> None:
        cutoff = time.time() - self._ttl
        for job_id, job in list(self.jobs.items()):
            finished = job.get("_finished")
            if finished is not None and finished < cutoff:
                del self.jobs[job_id]

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is not None:
                job.update(fields)

    def _run(self, job_id: str, work: Callable[[], str | None]) -> None:
        self._update(job_id, status="running")
        started = time.monotonic()
        try:
            detail = work()
        except Exception as exc:
            logger.error("Job %s failed", job_id, exc_info=True)
            self._update(job_id, status="error", detail=str(exc), _finished=time.time())
            return
        fields: dict[str, Any] = {
            "status": "done",
            "seconds": round(time.monotonic() - started, 1),
            "_finished": time.time(),
        }
        if detail:
            fields["detail"] = detail
        self._update(job_id, **fields)

    def start(self, kind: str, group: str, work: Callable[[], str | None]) -> str:
        """Run work on a thread; a running job in the same group is returned instead."""
        with self._lock:
            self._prune()
            for existing in self.jobs.values():
                if existing["_group"] == group and existing["status"] in (
                    "queued",
                    "running",
                ):
                    return str(existing["job_id"])
            job_id = str(uuid.uuid4())
            self.jobs[job_id] = {
                "job_id": job_id,
                "kind": kind,
                "status": "queued",
                "_group": group,
            }
        threading.Thread(
            target=self._run, args=(job_id, work), name=self._thread_name, daemon=True
        ).start()
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            return {k: v for k, v in job.items() if not k.startswith("_")}
