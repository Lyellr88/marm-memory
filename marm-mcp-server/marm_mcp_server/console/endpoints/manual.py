"""Manual tab API: read-only generation of client snippets, agent commands, the CLI catalog, endpoints, and env reference."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...config import user_settings
from ...middleware.auth import PUBLIC_PATHS, PUBLIC_PREFIXES
from ...services import cli_catalog, client_config, client_snippets
from .. import mcp_client
from .agents import Target, _target_url_and_auth

router = APIRouter()

_METHODS = ("get", "post", "put", "patch", "delete")
_OPENAPI_TIMEOUT = 3.0


def _tag(target: Target) -> str:
    return user_settings.load_docker()["tag"] if target == "docker" else "latest"


def _humanize(text: str) -> str:
    return text.replace("_", " ").strip().capitalize()


@router.get("/api/connections/manual/snippet")
def get_snippet(
    client: str,
    transport: str = "http",
    scope: str = "user",
    target: Target = "local",
    os_name: str = Query(default_factory=client_snippets.host_os, alias="os"),
) -> dict:
    url, auth_required = _target_url_and_auth(target)
    try:
        return client_snippets.snippet(
            client,
            os_name,
            transport,
            scope,
            url,
            auth_required,
            docker_tag=_tag(target),
        )
    except client_config.ClientNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown client id: {exc}"
        ) from exc
    except client_config.InvalidRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/connections/manual/agent-commands")
def get_agent_commands(
    transport: str = "http",
    scope: str = "user",
    target: Target = "local",
    os_name: str = Query(default_factory=client_snippets.host_os, alias="os"),
) -> dict:
    url, auth_required = _target_url_and_auth(target)
    try:
        commands = client_snippets.agent_commands(
            transport,
            scope,
            url,
            auth_required,
            os_name=os_name,
            docker_tag=_tag(target),
        )
    except client_config.InvalidRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"commands": commands}


@router.get("/api/connections/manual/cli")
def get_cli() -> dict:
    return {"commands": cli_catalog.catalog()}


def _route_auth(path: str, auth_required: bool) -> str:
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return "public"
    return "key" if auth_required else "local"


def _operations(schema: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    for path, item in sorted((schema.get("paths") or {}).items()):
        if not isinstance(item, dict):
            continue
        for method in _METHODS:
            operation = item.get(method)
            if isinstance(operation, dict):
                summary = operation.get("summary") or _humanize(
                    operation.get("operationId") or ""
                )
                yield path, method.upper(), summary


def _runtime_groups(schema: dict[str, Any], auth_required: bool) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for path, method, summary in _operations(schema):
        name = path.strip("/").split("/", 1)[0] or "root"
        groups.setdefault(name, []).append(
            {
                "method": method,
                "path": path,
                "summary": summary,
                "auth": _route_auth(path, auth_required),
            }
        )
    return [{"name": name, "routes": routes} for name, routes in groups.items()]


def _console_routes() -> list[dict]:
    from ..app import app

    return [
        {"method": method, "path": path, "summary": summary}
        for path, method, summary in _operations(app.openapi())
        if path.startswith("/api")
    ]


@router.get("/api/connections/manual/endpoints")
def get_endpoints() -> dict:
    url, auth_required = _target_url_and_auth("local")
    body: dict[str, Any] = {
        "mcp_url": url,
        "runtime_available": False,
        "reason": None,
        "groups": [],
        "console": _console_routes(),
    }
    try:
        schema = mcp_client.get("openapi.json", timeout=_OPENAPI_TIMEOUT)
    except mcp_client.McpUnavailable as exc:
        body["reason"] = str(exc)
        return body
    body["runtime_available"] = True
    body["groups"] = _runtime_groups(schema, auth_required)
    return body


@router.get("/api/connections/manual/env")
def get_env() -> dict:
    return {"items": user_settings.env_reference()}
