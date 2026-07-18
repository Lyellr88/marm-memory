"""Thread-safety test for the in-memory concept-build job tracker.

FastAPI routes defined with plain `def` run in a thread pool, so
_launching_concept_builds can be read/pruned/written by multiple
requests at once. Without a lock, mutating the dict during another
thread's iteration raises RuntimeError.
"""

import threading
import time

from server.endpoints import concepts as concepts_endpoint


def test_launching_concept_builds_survives_concurrent_insert_and_prune():
    with concepts_endpoint._launching_concept_builds_lock:
        concepts_endpoint._launching_concept_builds.clear()
    errors: list[Exception] = []

    def insert_jobs(worker_id: int) -> None:
        for i in range(300):
            job_id = f"job-{worker_id}-{i}"
            try:
                with concepts_endpoint._launching_concept_builds_lock:
                    concepts_endpoint._launching_concept_builds[job_id] = (
                        {"id": job_id, "status": "queued"},
                        time.monotonic(),
                    )
            except Exception as exc:  # noqa: BLE001 - capturing for the assertion
                errors.append(exc)

    def prune_repeatedly() -> None:
        for _ in range(300):
            try:
                concepts_endpoint._prune_launching_concept_builds()
            except Exception as exc:  # noqa: BLE001 - capturing for the assertion
                errors.append(exc)

    def read_repeatedly() -> None:
        for i in range(300):
            try:
                with concepts_endpoint._launching_concept_builds_lock:
                    concepts_endpoint._launching_concept_builds.get(f"job-0-{i}")
            except Exception as exc:  # noqa: BLE001 - capturing for the assertion
                errors.append(exc)

    threads = (
        [threading.Thread(target=insert_jobs, args=(w,)) for w in range(4)]
        + [threading.Thread(target=prune_repeatedly) for _ in range(4)]
        + [threading.Thread(target=read_repeatedly) for _ in range(2)]
    )
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
    finally:
        with concepts_endpoint._launching_concept_builds_lock:
            concepts_endpoint._launching_concept_builds.clear()
