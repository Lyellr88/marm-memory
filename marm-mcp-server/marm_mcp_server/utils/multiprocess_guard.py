"""Detects unsupported multi-process HTTP launches and warns."""

import os

import structlog

logger = structlog.get_logger()


def _detect_requested_worker_count() -> int | None:
    """Best-effort detection for unsupported multi-process HTTP launches."""
    for key in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        value = os.environ.get(key)
        if value and value.isdigit():
            return int(value)

    gunicorn_args = os.environ.get("GUNICORN_CMD_ARGS", "")
    parts = gunicorn_args.split()
    for index, part in enumerate(parts):
        if part in ("--workers", "-w") and index + 1 < len(parts):
            value = parts[index + 1]
            if value.isdigit():
                return int(value)
        if part.startswith("--workers="):
            value = part.split("=", 1)[1]
            if value.isdigit():
                return int(value)
    return None


def _warn_if_multi_process_requested() -> None:
    workers = _detect_requested_worker_count()
    if workers and workers > 1:
        logger.warning(
            "Unsupported multi-process HTTP deployment requested",
            workers=workers,
            supported_workers=1,
            reason=(
                "MARM coordinates write queue, compaction counters, scheduler, "
                "and protocol delivery in process-local state"
            ),
            recommendation=(
                "Run one MARM process per SQLite database. Use --swarm/--swarm-max "
                "inside a single process for shared HTTP agent load."
            ),
        )
