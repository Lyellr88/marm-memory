"""Connections hub setup surface: overview, boot-time settings, and runtime restart."""

from __future__ import annotations

import logging
import platform
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...config import settings as marm_settings
from ...config import user_settings
from ...core import runtime_flags, runtime_manager
from ...services import client_config, key_management, skill_install
from .. import mcp_client, runtime_control
from ..terminal.router import _loopback_only

logger = logging.getLogger(__name__)

router = APIRouter()


class SettingsPayload(BaseModel):
    values: dict[str, Any]


def _require_loopback(action: str) -> None:
    if not _loopback_only():
        raise HTTPException(
            status_code=403,
            detail=f"{action} refuses unless the Console is bound to loopback.",
        )


def _runtime_url_and_auth() -> tuple[str, bool]:
    from ...config.settings import MARM_API_KEY, SERVER_PORT

    runtime = runtime_manager.inspect_runtime()
    metadata = runtime.get("metadata") or {}
    port = metadata.get("port") or SERVER_PORT
    return f"http://127.0.0.1:{port}/mcp", bool(MARM_API_KEY)


def _skills_installed() -> int:
    return sum(1 for agent in skill_install.AGENTS if skill_install.is_installed(agent))


def _project_step(runtime_ready: bool) -> dict[str, Any]:
    step: dict[str, Any] = {
        "id": "project",
        "label": "A project indexed",
        "done": False,
        "detail": "Runtime is not running",
    }
    if not runtime_ready:
        return step
    try:
        projects = mcp_client.list_projects()
    except Exception:
        step["detail"] = "Could not read projects"
        return step
    step["done"] = bool(projects)
    step["detail"] = (
        f"{len(projects)} indexed" if projects else "No project indexed yet"
    )
    return step


@router.get("/api/connections/overview")
def get_overview() -> dict:
    url, auth_required = _runtime_url_and_auth()
    runtime = runtime_manager.inspect_runtime()
    state = runtime.get("state", "stopped")
    profile = (runtime.get("metadata") or {}).get("profile")
    agents = client_config.list_agents(url, auth_required)
    detected = [agent for agent in agents if agent["detected"]]
    connected = sum(1 for agent in detected if agent["user"]["state"] == "configured")
    skills = _skills_installed()
    version = marm_settings.SERVER_VERSION
    return {
        "version": version,
        "os": platform.system(),
        "runtime": {
            "state": state,
            "managed": bool(runtime.get("managed")),
            "url": url,
            "profile": profile,
        },
        "auth": {
            "mode": "key" if marm_settings.MARM_API_KEY else "local",
            "key_file_exists": key_management.managed_key_path().exists(),
        },
        "agents": {"connected": connected, "detected": len(detected)},
        "skills_installed": skills,
        "checklist": [
            {
                "id": "installed",
                "label": "MARM installed",
                "done": True,
                "detail": f"Version {version}",
            },
            {
                "id": "runtime",
                "label": "Runtime running",
                "done": state == "ready",
                "detail": url if state == "ready" else f"Runtime is {state}",
            },
            {
                "id": "agents",
                "label": "An agent connected",
                "done": connected > 0,
                "detail": f"{connected} of {len(detected)} detected agents",
            },
            _project_step(state == "ready"),
        ],
    }


def _live() -> dict[str, Any]:
    try:
        profile, rate_limit_rpm = _restart_preset()
        return {
            "profile": profile,
            "rate_limit_rpm": rate_limit_rpm,
            "auto_index_graph": runtime_flags.get_bool(
                runtime_flags.AUTO_INDEX_GRAPH, marm_settings.GRAPH_AUTO_INDEX
            ),
            "auto_index_concept": runtime_flags.get_bool(
                runtime_flags.AUTO_INDEX_CONCEPT, marm_settings.CONCEPT_AUTO_INDEX
            ),
            "llm_enabled": runtime_flags.get_bool(runtime_flags.LLM_ENABLED, False),
        }
    except Exception:
        logger.warning("Could not read live runtime switches", exc_info=True)
        return {
            "profile": None,
            "rate_limit_rpm": None,
            "auto_index_graph": None,
            "auto_index_concept": None,
            "llm_enabled": None,
        }


def _restart_preset() -> tuple[str, int | None]:
    from ...cli import resolve_restart_preset

    return resolve_restart_preset(runtime_manager.read_state() or {})


def _settings_body() -> dict:
    return {**user_settings.describe(), "live": _live()}


@router.get("/api/connections/settings")
def get_settings() -> dict:
    return _settings_body()


@router.put("/api/connections/settings")
def put_settings(payload: SettingsPayload) -> dict:
    _require_loopback("Saving settings")
    try:
        user_settings.validate(payload.values)
        # The key must exist before the setting is saved, or the file claims auth the runtime cannot apply.
        if (
            payload.values.get("auth.require_key") is True
            and not key_management.read_managed_key()
        ):
            try:
                key_management.initialize_managed_key()
            except (OSError, RuntimeError) as exc:
                raise HTTPException(
                    status_code=409,
                    detail="Nothing was saved because a key could not be created.",
                ) from exc
        user_settings.save(payload.values)
    except user_settings.SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=409, detail=f"Could not write settings: {exc.strerror or exc}"
        ) from exc
    return _settings_body()


@router.post("/api/connections/runtime/restart", status_code=202)
def restart_runtime() -> Any:
    _require_loopback("Restart")
    try:
        return {"job_id": runtime_control.start_restart()}
    except runtime_control.NotManaged as exc:
        return JSONResponse(
            status_code=409, content={"detail": str(exc), "command": exc.command}
        )


@router.get("/api/connections/runtime/restart/{job_id}")
def get_restart_job(job_id: str) -> dict:
    job = runtime_control.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown restart job.")
    return job
