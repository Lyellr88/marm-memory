"""Agents grid API: per-client status, configure, remove, test, and skill install."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import settings as marm_settings
from ...config import user_settings
from ...services import client_config, key_management, mcp_probe, skill_install
from ..terminal.router import _loopback_only
from .docker import docker_url
from .setup import _require_loopback, _runtime_url_and_auth

router = APIRouter()

T = TypeVar("T")

_KEY_REFS = (
    "${MARM_API_KEY}",
    "${env:MARM_API_KEY}",
    "{env:MARM_API_KEY}",
    "${input:marm-api-key}",
)


Target = Literal["local", "docker"]


class ConfigurePayload(BaseModel):
    target: Target = "local"
    transport: str = "http"
    scope: str = "user"
    project: str | None = None
    dry_run: bool = False


class RemovePayload(BaseModel):
    target: Target = "local"
    scope: str = "user"
    project: str | None = None
    dry_run: bool = False


class ProbePayload(BaseModel):
    target: Target = "local"
    scope: str = "user"
    project: str | None = None


def _is_loopback_host(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def _guarded(call: Callable[[], T]) -> T:
    try:
        return call()
    except client_config.ClientNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown client id: {exc}"
        ) from exc
    except client_config.InvalidRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except client_config.ClientNotConfigurable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _target_url_and_auth(target: Target) -> tuple[str, bool]:
    if target == "docker":
        return docker_url(user_settings.load_docker()), True
    return _runtime_url_and_auth()


def _docker_entry_options(target: Target) -> dict[str, Any]:
    if target != "docker":
        return {}
    config = user_settings.load_docker()
    return {
        "docker_tag": config["tag"],
        "docker_data_dir": Path(config["data_dir"]),
    }


def _require_known(client_id: str) -> None:
    if client_id not in client_config.CLIENT_IDS:
        raise HTTPException(status_code=404, detail=f"Unknown client id: {client_id}")


@router.get("/api/connections/agents")
def list_agents(target: Target = "local") -> dict:
    url, auth_required = _target_url_and_auth(target)
    allowed = _loopback_only()
    return {
        "auth_required": auth_required,
        "configure_allowed": allowed,
        "configure_blocked_reason": None
        if allowed
        else "The Console is not bound to loopback.",
        "clients": client_config.list_agents(url, auth_required),
    }


@router.get("/api/connections/agents/{client_id}/scope")
def get_scope(
    client_id: str,
    scope: str = "user",
    project: str | None = None,
    target: Target = "local",
) -> dict:
    _require_known(client_id)
    url, auth_required = _target_url_and_auth(target)
    return _guarded(
        lambda: client_config.status(client_id, scope, project, url, auth_required)
    )


@router.post("/api/connections/agents/{client_id}/configure")
def configure_agent(client_id: str, payload: ConfigurePayload) -> dict:
    _require_loopback("Configure")
    _require_known(client_id)
    url, auth_required = _target_url_and_auth(payload.target)
    return _guarded(
        lambda: client_config.configure(
            client_id,
            url,
            auth_required,
            transport=payload.transport,
            scope=payload.scope,
            project=payload.project,
            dry_run=payload.dry_run,
            **_docker_entry_options(payload.target),
        )
    )


@router.post("/api/connections/agents/{client_id}/remove")
def remove_agent(client_id: str, payload: RemovePayload) -> dict:
    _require_loopback("Remove")
    _require_known(client_id)
    return _guarded(
        lambda: client_config.remove(
            client_id, payload.scope, payload.project, payload.dry_run
        )
    )


def _resolve_key_refs(headers: dict[str, str], docker: bool = False) -> dict[str, str]:
    key = key_management.read_managed_key() or (
        "" if docker else marm_settings.MARM_API_KEY
    )
    if not key:
        return headers
    resolved = {}
    for name, value in headers.items():
        for ref in _KEY_REFS:
            value = value.replace(ref, key)
        resolved[name] = value
    return resolved


def _probe_http(entry: dict, docker: bool = False) -> dict:
    url = next(
        (
            entry[k]
            for k in ("url", "httpUrl", "serverUrl")
            if isinstance(entry.get(k), str)
        ),
        "",
    )
    if urlparse(url).scheme not in {"http", "https"}:
        return _unsupported("http", "The entry has no http or https URL.")
    raw = entry.get("headers")
    headers = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    if entry.get("bearer_token_env_var") == "MARM_API_KEY":
        headers["Authorization"] = "Bearer ${MARM_API_KEY}"
    withheld = not _is_loopback_host(urlparse(url).hostname)
    result = mcp_probe.probe_http(
        url, headers if withheld else _resolve_key_refs(headers, docker)
    )
    if withheld and result["error"] and result["error"]["kind"] == "unauthorized":
        result["error"]["detail"] += " The key is only sent to a local address."
    return result


def _probe_stdio(entry: dict, transport: str) -> dict:
    command = entry.get("command")
    args = entry.get("args") or []
    if not isinstance(command, str) or not isinstance(args, list):
        return _unsupported(transport, "The entry has no command to run.")
    env = dict(os.environ)
    if isinstance(entry.get("env"), dict):
        env.update({str(k): str(v) for k, v in entry["env"].items()})
    return mcp_probe.probe_stdio([command, *[str(a) for a in args]], env)


def _unsupported(transport: str, detail: str) -> dict:
    return {
        "ok": False,
        "transport": transport,
        "tools": 0,
        "latency_ms": 0,
        "error": {"kind": "unsupported", "detail": detail},
    }


@router.post("/api/connections/agents/{client_id}/test")
def test_agent(client_id: str, payload: ProbePayload) -> dict:
    _require_loopback("Test")
    _require_known(client_id)
    try:
        entry = client_config.read_entry(client_id, payload.scope, payload.project)
    except client_config.ClientNotConfigurable as exc:
        return _missing_entry(str(exc))
    except client_config.ClientNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown client id: {exc}"
        ) from exc
    except client_config.InvalidRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if entry is None:
        return _missing_entry("MARM is not in this config file yet.")
    transport = client_config.detect_transport(entry)
    if transport == "http":
        return _probe_http(entry, payload.target == "docker")
    if transport in {"stdio", "docker-stdio"}:
        return _probe_stdio(entry, transport)
    return _unsupported("http", "The entry is not a shape MARM can test.")


def _missing_entry(detail: str) -> dict:
    return {
        "ok": False,
        "transport": "http",
        "tools": 0,
        "latency_ms": 0,
        "error": {"kind": "missing_entry", "detail": detail},
    }


@router.post("/api/connections/agents/{client_id}/skill")
def install_agent_skill(client_id: str) -> dict:
    _require_loopback("Skill install")
    _require_known(client_id)
    if client_id not in skill_install.AGENTS:
        raise HTTPException(
            status_code=409, detail="This agent has no MARM skill support."
        )
    return skill_install.install_for_agent(client_id)
