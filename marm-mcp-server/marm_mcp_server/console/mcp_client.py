from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class McpUnavailable(RuntimeError):
    """The running MARM MCP server could not complete a Console request."""


class McpRequestError(McpUnavailable):
    """MARM MCP received the request but rejected it."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


_projects_cache: tuple[float, list[dict]] | None = None


def _api_key() -> str:
    explicit = os.environ.get("MARM_API_KEY", "")
    if explicit:
        return explicit
    from ..config.settings import MARM_API_KEY

    if MARM_API_KEY:
        return MARM_API_KEY
    from ..services.key_management import read_managed_key

    return read_managed_key()


def _http_error(exc: HTTPError) -> McpRequestError:
    detail = "MARM MCP server rejected this request."
    try:
        payload = json.load(exc)
        if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
            detail = payload["detail"]
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return McpRequestError(exc.code, detail)


def request(
    operation: str,
    payload: dict | None = None,
    *,
    method: str = "POST",
    timeout: float = 10.0,
) -> dict:
    base_url = os.environ.get("MARM_MCP_URL", "http://127.0.0.1:8001").rstrip("/")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = _api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        f"{base_url}/{operation.lstrip('/')}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise _http_error(exc) from exc
    except (URLError, OSError, ValueError) as exc:
        raise McpUnavailable(
            "MARM MCP server is unavailable for this request."
        ) from exc
    if not isinstance(result, dict):
        raise McpUnavailable("MARM MCP server returned an invalid response.")
    return result


def post(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
    return request(operation, payload, timeout=timeout)


def put(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
    return request(operation, payload, method="PUT", timeout=timeout)


def delete(
    operation: str, payload: dict | None = None, *, timeout: float = 10.0
) -> dict:
    return request(operation, payload, method="DELETE", timeout=timeout)


def get(operation: str, *, query: dict | None = None, timeout: float = 10.0) -> dict:
    base_url = os.environ.get("MARM_MCP_URL", "http://127.0.0.1:8001").rstrip("/")
    headers = {"Accept": "application/json"}
    api_key = _api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = f"{base_url}/{operation.lstrip('/')}"
    if query:
        url = f"{url}?{urlencode(query)}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise _http_error(exc) from exc
    except (URLError, OSError, ValueError) as exc:
        raise McpUnavailable(
            "MARM MCP server is unavailable for this request."
        ) from exc
    if not isinstance(result, dict):
        raise McpUnavailable("MARM MCP server returned an invalid response.")
    return result


def list_projects() -> list[dict]:
    global _projects_cache
    if _projects_cache and time.monotonic() - _projects_cache[0] < 15:
        return _projects_cache[1]
    result = post("internal/projects/list", {})
    if result.get("status") == "error":
        raise McpUnavailable(
            result.get("message", "MARM graph backend is unavailable.")
        )
    projects = result.get("projects", [])
    projects = [
        {
            "name": item["name"],
            "root_path": item["root_path"],
            "nodes": item.get("nodes", 0),
            "edges": item.get("edges", 0),
            "status": "ready",
        }
        for item in projects
        if isinstance(item, dict) and item.get("name") and item.get("root_path")
    ]
    _projects_cache = (time.monotonic(), projects)
    return projects


def cached_projects() -> list[dict] | None:
    if _projects_cache is None:
        return None
    return _projects_cache[1]
