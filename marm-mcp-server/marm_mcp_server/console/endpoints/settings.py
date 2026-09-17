"""Runtime controls and diagnostics for the local MARM Console."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import mcp_client
from ..models import (
    CompactionDryRunPayload,
    RuntimeAutomationPayload,
    RuntimeLlmPayload,
    RuntimeLlmRootPayload,
    RuntimeProfilePayload,
)

router = APIRouter()


@router.get("/api/settings/runtime")
def get_runtime_settings() -> dict:
    try:
        return mcp_client.get("internal/runtime/settings", timeout=5.0)
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("/api/settings/automation")
def update_runtime_automation(payload: RuntimeAutomationPayload) -> dict:
    try:
        return mcp_client.put(
            "internal/runtime/settings/automation", payload.model_dump(), timeout=5.0
        )
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("/api/settings/profile")
def update_runtime_profile(payload: RuntimeProfilePayload) -> dict:
    try:
        return mcp_client.put(
            "internal/runtime/settings/profile", payload.model_dump(), timeout=10.0
        )
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _proxy(fn: Callable[..., dict], *args: Any, **kwargs: Any) -> dict:
    # McpRequestError subclasses McpUnavailable, so it has to be caught first.
    try:
        return fn(*args, **kwargs)
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/settings/maintenance")
def get_maintenance() -> dict:
    return _proxy(mcp_client.get, "internal/runtime/maintenance", timeout=10.0)


@router.post("/api/settings/maintenance/compaction-dry-run", status_code=202)
def run_compaction_dry_run(payload: CompactionDryRunPayload) -> dict:
    return _proxy(
        mcp_client.post,
        "internal/runtime/maintenance/compaction-dry-run",
        payload.model_dump(),
        timeout=15.0,
    )


@router.get("/api/settings/maintenance/compaction-dry-run/{job_id}")
def get_compaction_dry_run(job_id: str) -> dict:
    return _proxy(
        mcp_client.get,
        f"internal/runtime/maintenance/compaction-dry-run/{job_id}",
        timeout=15.0,
    )


@router.get("/api/settings/doctor")
def get_doctor() -> dict:
    return _proxy(mcp_client.get, "internal/runtime/doctor", timeout=15.0)


@router.get("/api/settings/logs")
def get_logs(lines: int = 200) -> dict:
    return _proxy(
        mcp_client.get, "internal/runtime/logs", query={"lines": lines}, timeout=15.0
    )


@router.get("/api/settings/upgrade-check")
def get_upgrade_check() -> dict:
    return _proxy(mcp_client.get, "internal/runtime/upgrade/check", timeout=20.0)


@router.get("/api/settings/backups")
def get_backups() -> dict:
    return _proxy(mcp_client.get, "internal/runtime/backups", timeout=10.0)


@router.post("/api/settings/backups")
def create_backup() -> dict:
    return _proxy(mcp_client.post, "internal/runtime/backups", {}, timeout=120.0)


@router.delete("/api/settings/backups/{name}")
def delete_backup(name: str) -> dict:
    return _proxy(mcp_client.delete, f"internal/runtime/backups/{name}", timeout=15.0)


@router.post("/api/settings/maintenance/reload-docs", status_code=202)
def reload_docs() -> dict:
    return _proxy(
        mcp_client.post, "internal/runtime/maintenance/reload-docs", {}, timeout=15.0
    )


@router.get("/api/settings/maintenance/reload-docs/{job_id}")
def get_reload_docs(job_id: str) -> dict:
    return _proxy(
        mcp_client.get,
        f"internal/runtime/maintenance/reload-docs/{job_id}",
        timeout=15.0,
    )


@router.get("/api/settings/llm/models")
def get_llm_models(refresh: bool = False) -> dict:
    """What the local runtime serves, and what else is on this machine.

    The scan walks real directories -- 62 GB of LM Studio tree on the machine
    this was built against -- so the timeout is well above the 35 ms a warm
    scan measures, to leave room for a cold cache on a spinning disk.
    """
    return _proxy(
        mcp_client.get,
        "internal/runtime/llm/models",
        query={"refresh": str(refresh).lower()},
        timeout=30.0,
    )


@router.get("/api/settings/llm/browse")
def browse_llm_models(path: str | None = None) -> dict:
    """List one directory inside the known model roots."""
    return _proxy(
        mcp_client.get,
        "internal/runtime/llm/browse",
        query={"path": path} if path else None,
        timeout=15.0,
    )


@router.put("/api/settings/llm")
def update_llm_settings(payload: RuntimeLlmPayload) -> dict:
    """Turn generation on or off, and choose which served model answers."""
    return _proxy(
        mcp_client.put,
        "internal/runtime/settings/llm",
        payload.model_dump(exclude_none=True),
        timeout=15.0,
    )


@router.post("/api/settings/llm/roots")
def update_llm_roots(payload: RuntimeLlmRootPayload) -> dict:
    """Add or remove a directory discovery and Browse may look inside."""
    return _proxy(
        mcp_client.post,
        "internal/runtime/settings/llm/roots",
        payload.model_dump(),
        timeout=30.0,
    )
