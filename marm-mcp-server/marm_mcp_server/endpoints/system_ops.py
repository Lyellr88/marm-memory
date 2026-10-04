import asyncio
import logging
import sqlite3
from collections import deque

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["System"])


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
