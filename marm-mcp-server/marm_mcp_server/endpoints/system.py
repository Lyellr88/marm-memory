import asyncio
import logging
import os
import sqlite3
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..config.settings import (
    CONCEPTS_AVAILABLE,
    SEMANTIC_SEARCH_AVAILABLE,
    SEMANTIC_SEARCH_ENABLED,
    SERVER_VERSION,
)
from ..core import runtime_flags
from ..core.graph_supervisor import graph_supervisor
from ..core.memory import memory
from ..core.rate_limiter import rate_limiter
from ..core.shutdown_manager import shutdown_manager
from ..services.documentation import reload_marm_documentation
from ..services.runtime_status import knowledge_status, maintenance_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["System"])


class RuntimeAutomationRequest(BaseModel):
    scope: Literal["graph", "concept"]
    enabled: bool


class RuntimeProfileRequest(BaseModel):
    profile: Literal["standard", "swarm", "swarm-max", "trusted"]
    rate_limit_rpm: int | None = None


def _model_state() -> str:
    # The encoder loads lazily on first recall, so importability is not the same as loaded.
    if memory.encoder is not None:
        return "loaded"
    if memory._encoder_failed:
        return "failed"
    if memory._encoder_loading:
        return "loading"
    return "not_loaded"


def _rate_limit_status() -> dict:
    # Read the live limiter, not the env default: configure() can change it without a restart.
    limits = rate_limiter.limits["default"]
    requests = limits["requests"]
    return {
        "requests_per_minute": requests,
        "window_seconds": limits["window"],
        "block_seconds": limits["block_duration"],
        "enforced": requests > 0,
        "environment_default": settings.MARM_RATE_LIMIT_RPM_DEFAULT,
    }


def _automation_status() -> dict:
    graph_key = runtime_flags.AUTO_INDEX_GRAPH
    concept_key = runtime_flags.AUTO_INDEX_CONCEPT
    return {
        "graph": {
            "enabled": runtime_flags.get_bool(graph_key, settings.GRAPH_AUTO_INDEX),
            "source": runtime_flags.source(graph_key),
            "environment_default": settings.GRAPH_AUTO_INDEX,
            "suppressed_projects": runtime_flags.suppressed_watches(),
            "unindexable_projects": runtime_flags.unindexable_watches(),
        },
        "concept": {
            "enabled": runtime_flags.get_bool(concept_key, settings.CONCEPT_AUTO_INDEX),
            "source": runtime_flags.source(concept_key),
            "environment_default": settings.CONCEPT_AUTO_INDEX,
        },
    }


@router.get("/health", include_in_schema=False)
async def health_check() -> dict:
    """Health check endpoint for Docker and monitoring"""
    try:
        with memory.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()

        return {
            "status": "healthy",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "connected",
            "semantic_search": (
                "available" if SEMANTIC_SEARCH_AVAILABLE else "text_only"
            ),
            "concept_extraction": "available" if CONCEPTS_AVAILABLE else "unavailable",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e!s}", exc_info=True)

        return {
            "status": "unhealthy",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "Service temporarily unavailable",
        }


@router.get("/ready", include_in_schema=False)
async def readiness_check() -> dict:
    """Readiness check endpoint - service ready to handle requests"""
    try:
        with memory.get_connection() as conn:
            conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            conn.execute("SELECT COUNT(*) FROM sessions").fetchone()

        return {
            "status": "ready",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoints": {
                "mcp": "http://localhost:8001/mcp",
                "docs": "http://localhost:8001/docs",
            },
        }
    except Exception as e:
        logger.error(f"Readiness check failed: {e!s}", exc_info=True)

        return {
            "status": "not_ready",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "Service not ready",
        }


@router.get("/internal/runtime/status", include_in_schema=False)
async def runtime_status() -> dict:
    queue = memory._write_queue
    return {
        "status": "ready",
        "service": "marm-memory-runtime",
        "runtime_id": os.environ.get("MARM_RUNTIME_ID"),
        "pid": os.getpid(),
        "version": SERVER_VERSION,
        "profile": os.environ.get("MARM_RUNTIME_PROFILE", "standard"),
        "write_queue": {
            "enabled": settings.WRITE_QUEUE_ENABLED,
            "running": bool(
                queue and queue._worker_task and not queue._worker_task.done()
            ),
            "depth": queue.queue.qsize() if queue else 0,
            "capacity": queue.queue.maxsize if queue else settings.MAX_QUEUE_SIZE,
            "stopping": queue._stopping if queue else False,
        },
        "graph": graph_supervisor.snapshot(),
    }


@router.get("/internal/runtime/settings", include_in_schema=False)
async def runtime_settings() -> dict:
    """Console-only diagnostics and durable automatic-indexing controls.

    The values are deliberately derived from the same database-backed runtime
    flags the workers read every cycle. This is not a second configuration path.
    """
    runtime = await runtime_status()
    knowledge = knowledge_status()
    maintenance = maintenance_status()
    return {
        **runtime,
        "automation": _automation_status(),
        "knowledge": {
            "state": knowledge["state"],
            "schema": knowledge["schema"],
            "index_queue": knowledge["index_queue"],
        },
        "storage": {
            "memory": maintenance["memory_database"],
            "concept": knowledge["database"],
        },
        "embedding": maintenance["embedding"],
        "rate_limit": _rate_limit_status(),
        "search": {
            "semantic_enabled": SEMANTIC_SEARCH_ENABLED,
            "semantic_available": SEMANTIC_SEARCH_AVAILABLE,
            "model_state": _model_state(),
        },
    }


@router.put("/internal/runtime/settings/automation", include_in_schema=False)
async def update_runtime_automation(req: RuntimeAutomationRequest) -> dict:
    key = (
        runtime_flags.AUTO_INDEX_GRAPH
        if req.scope == "graph"
        else runtime_flags.AUTO_INDEX_CONCEPT
    )
    runtime_flags.set_bool(key, req.enabled)
    return {
        "status": "success",
        "scope": req.scope,
        "enabled": req.enabled,
        "effective": "next cycle",
        "automation": _automation_status(),
    }


@router.put("/internal/runtime/settings/profile", include_in_schema=False)
async def update_runtime_profile(req: RuntimeProfileRequest) -> dict:
    from ..cli import _profile_flags, apply_runtime_preset, reconcile_profile_and_rpm

    if req.rate_limit_rpm is not None and req.rate_limit_rpm < 0:
        raise HTTPException(
            status_code=422, detail="rate_limit_rpm must be 0 or greater"
        )
    profile, rate_limit_rpm = reconcile_profile_and_rpm(req.profile, req.rate_limit_rpm)
    try:
        applied = apply_runtime_preset(
            **_profile_flags(profile), rate_limit_rpm=rate_limit_rpm
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # runtime_status reads the profile back out of the environment, so it has to move too.
    os.environ["MARM_RUNTIME_PROFILE"] = profile
    persistence = "saved"
    try:
        runtime_flags.save_runtime_preset(profile, rate_limit_rpm)
    except Exception:
        logger.warning("Could not persist the runtime preset", exc_info=True)
        persistence = "until_restart"
    return {
        "status": "success",
        "profile": profile,
        "requested_profile": req.profile,
        "mode": applied["mode"],
        "persistence": persistence,
        "rate_limit": _rate_limit_status(),
        "write_queue_enabled": applied["write_queue_enabled"],
    }


@router.post("/internal/runtime/shutdown", include_in_schema=False)
async def runtime_shutdown() -> dict:
    shutdown_manager.request_shutdown()
    return {"status": "stopping"}


@router.post(
    "/marm_reload_docs", operation_id="marm_reload_docs", include_in_schema=False
)
async def marm_reload_docs() -> dict:
    """
    📚 Reload MARM documentation into memory system

    Refreshes all documentation files and core knowledge in the database
    """
    try:
        await reload_marm_documentation()
        return {
            "status": "success",
            "message": "📚 MARM documentation reloaded successfully",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to reload documentation: {e!s}"
        ) from e


class CompactionDryRunRequest(BaseModel):
    session_name: str


@router.get("/internal/runtime/maintenance", include_in_schema=False)
async def runtime_maintenance() -> dict:
    """Which maintenance work the Console may run, and which the CLI must own."""
    from ..cli import _http_server_is_running

    # migrate and rechunk rewrite rows the live pool holds open, so they refuse
    # while an HTTP server answers, which is exactly the case when the Console asks.
    server_live = _http_server_is_running()
    blocked = {
        "runnable": False,
        "reason": (
            "Requires every MARM HTTP and STDIO process to be stopped first."
            if server_live
            else "Runs from the CLI so it can confirm no STDIO process is attached."
        ),
    }
    return {
        "status": "success",
        "http_server_running": server_live,
        "actions": {
            "compaction_dry_run": {
                "runnable": True,
                "command": "marm-memory maintenance compaction dry-run --session <name>",
            },
            "reload_docs": {"runnable": True, "command": None},
            "embeddings_migrate": {
                **blocked,
                "command": "marm-memory maintenance embeddings migrate",
            },
            "chunks_rechunk": {
                **blocked,
                "command": "marm-memory maintenance chunks rechunk",
            },
        },
    }


_dry_run_jobs: dict[str, dict] = {}
_dry_run_jobs_lock = threading.Lock()
_DRY_RUN_JOB_TTL_SECONDS = 3600
_reload_docs_tasks: set[asyncio.Task] = set()


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


def _run_compaction_dry_run_job(job_id: str, session_name: str) -> None:
    from ..cli import DEFAULT_DB_PATH, _ReadOnlyMemory
    from ..core.compaction import run_compaction_dry_run

    with _dry_run_jobs_lock:
        job = _dry_run_jobs.get(job_id)
    if job is None:
        return
    job.update(status="running", started_at=_now_iso())
    try:
        if not Path(DEFAULT_DB_PATH).exists():
            job.update(status="success", candidates=[], report_path=None)
        else:
            result = run_compaction_dry_run(
                _ReadOnlyMemory(DEFAULT_DB_PATH), session_name
            )
            job.update(
                status="success",
                candidates=result.get("candidates", []),
                report_path=result.get("report_path"),
            )
    except Exception as exc:
        logger.error("Compaction dry run failed", exc_info=True)
        job.update(status="error", error=str(exc))
    finally:
        job["finished_at"] = _now_iso()
        job["_finished_timestamp"] = datetime.now(timezone.utc).timestamp()


async def _run_reload_docs_job(job_id: str) -> None:
    """Must stay on the server loop: the write queue resolves its futures there."""
    with _dry_run_jobs_lock:
        job = _dry_run_jobs.get(job_id)
    if job is None:
        return
    job.update(status="running", started_at=_now_iso())
    try:
        await reload_marm_documentation()
        job.update(status="success", message="Documentation reloaded.")
    except Exception as exc:
        logger.error("Documentation reload failed", exc_info=True)
        job.update(status="error", error=str(exc))
    finally:
        job["finished_at"] = _now_iso()
        job["_finished_timestamp"] = datetime.now(timezone.utc).timestamp()


@router.post(
    "/internal/runtime/maintenance/reload-docs",
    include_in_schema=False,
    status_code=202,
)
async def runtime_reload_docs() -> dict:
    _prune_dry_run_jobs()
    job_id = str(uuid.uuid4())
    with _dry_run_jobs_lock:
        _dry_run_jobs[job_id] = {
            "job_id": job_id,
            "kind": "reload_docs",
            "status": "queued",
            "message": None,
            "error": None,
            "created_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
        }
    try:
        task = asyncio.create_task(_run_reload_docs_job(job_id))
    except RuntimeError as exc:
        with _dry_run_jobs_lock:
            _dry_run_jobs.pop(job_id, None)
        raise HTTPException(
            status_code=500, detail="Could not start the reload."
        ) from exc
    # asyncio holds only a weak reference to a running task.
    _reload_docs_tasks.add(task)
    task.add_done_callback(_reload_docs_tasks.discard)
    with _dry_run_jobs_lock:
        return _public_job(_dry_run_jobs[job_id])


@router.get(
    "/internal/runtime/maintenance/reload-docs/{job_id}", include_in_schema=False
)
async def runtime_reload_docs_status(job_id: str) -> dict:
    _prune_dry_run_jobs()
    with _dry_run_jobs_lock:
        job = _dry_run_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="No such reload.")
        return _public_job(job)


@router.post(
    "/internal/runtime/maintenance/compaction-dry-run",
    include_in_schema=False,
    status_code=202,
)
async def runtime_compaction_dry_run(req: CompactionDryRunRequest) -> dict:
    """Queued rather than inline: the scan cost grows with the square of session size."""
    _prune_dry_run_jobs()
    job_id = str(uuid.uuid4())
    with _dry_run_jobs_lock:
        _dry_run_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "session_name": req.session_name,
            "candidates": [],
            "report_path": None,
            "error": None,
            "created_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
        }
    worker = threading.Thread(
        target=_run_compaction_dry_run_job,
        args=(job_id, req.session_name),
        daemon=True,
    )
    try:
        worker.start()
    except Exception as exc:
        with _dry_run_jobs_lock:
            _dry_run_jobs.pop(job_id, None)
        raise HTTPException(
            status_code=500, detail="Could not start the scan."
        ) from exc
    with _dry_run_jobs_lock:
        return _public_job(_dry_run_jobs[job_id])


@router.get(
    "/internal/runtime/maintenance/compaction-dry-run/{job_id}",
    include_in_schema=False,
)
async def runtime_compaction_dry_run_status(job_id: str) -> dict:
    _prune_dry_run_jobs()
    with _dry_run_jobs_lock:
        job = _dry_run_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="No such scan.")
        return _public_job(job)


@router.get("/internal/runtime/doctor", include_in_schema=False)
async def runtime_doctor() -> dict:
    from ..services.runtime_status import doctor_status

    return {"status": "success", **doctor_status()}


@router.get("/internal/runtime/logs", include_in_schema=False)
async def runtime_logs(lines: int = 200) -> dict:
    from ..core.runtime_manager import log_path

    capped = max(1, min(lines, 2000))
    path = log_path()
    if not path.exists():
        return {"status": "success", "path": str(path), "lines": [], "exists": False}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        tail = deque(handle, maxlen=capped)
    return {
        "status": "success",
        "path": str(path),
        "exists": True,
        "lines": [line.rstrip("\n") for line in tail],
    }


@router.get("/internal/runtime/upgrade/check", include_in_schema=False)
async def runtime_upgrade_check() -> dict:
    from ..services.package_management import (
        check_latest_release,
        inspect_installation,
        manual_upgrade_command,
    )

    installation = inspect_installation()
    try:
        release = check_latest_release()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "success",
        "installed_version": release["installed_version"],
        "latest_version": release["latest_version"],
        "state": release["state"],
        "installer": release["installer"],
        "editable": release["editable"] == "true",
        "command": manual_upgrade_command(installation),
    }


@router.get("/internal/runtime/backups", include_in_schema=False)
async def runtime_backups() -> dict:
    from ..services import backup

    return {
        "status": "success",
        "directory": str(backup.backup_dir()),
        "items": backup.list_backups(),
    }


@router.post("/internal/runtime/backups", include_in_schema=False)
async def runtime_create_backup() -> dict:
    from ..services import backup

    try:
        created = await asyncio.to_thread(backup.create_backup)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except sqlite3.Error as exc:
        logger.error("Snapshot failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "success", "backup": created}


@router.delete("/internal/runtime/backups/{name}", include_in_schema=False)
async def runtime_delete_backup(name: str) -> dict:
    from ..services import backup

    try:
        removed = backup.delete_backup(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No such snapshot.")
    return {"status": "success", "deleted": name}
