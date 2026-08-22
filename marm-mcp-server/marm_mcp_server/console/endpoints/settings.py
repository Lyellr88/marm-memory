"""Runtime controls and diagnostics for the local MARM Console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import mcp_client
from ..models import RuntimeAutomationPayload

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
