from __future__ import annotations

import json
import os
import time
from pathlib import PurePath, PureWindowsPath
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


def _usable_project(item: object) -> bool:
    """Accept only an engine row this module can safely normalise.

    `_with_display_names` calls `.rstrip("/")` on `root_path`, so a malformed
    engine response -- `root_path: 123`, or a non-empty list -- would raise and
    turn the whole Console project list into a 500. A row that cannot be
    described is dropped rather than allowed to fail the request.
    """
    if not isinstance(item, dict):
        return False
    name, root = item.get("name"), item.get("root_path")
    return (
        isinstance(name, str)
        and bool(name.strip())
        and isinstance(root, str)
        and bool(root.strip())
    )


def _root_parts(root_path: str) -> tuple[str, ...]:
    """Path components of a repository root, on either host's separators.

    `root_path` comes from the engine that owns the index, which may be a
    Windows host, so `C:\\work\\repo\\` has to yield ("C:\\", "work", "repo")
    rather than one opaque string. Mirrors core.code_project_bindings.
    """
    normalized = root_path.strip().rstrip("/\\")
    path = PureWindowsPath(normalized) if "\\" in normalized else PurePath(normalized)
    return tuple(part for part in path.parts if part not in ("/", "\\"))


def _with_display_names(projects: list[dict]) -> list[dict]:
    """Attach a short, human-readable ``display_name`` to each project.

    The engine's project id is derived from the repository's absolute path, and
    the Console prints that path directly beneath the id -- so a card states the
    same thing twice, and two projects under one parent truncate to an identical
    title.

    This is display only. ``name`` stays the engine id because it is the graph
    database's filename and the ``/explorer/<name>`` routing key.

    A basename is not unique: the same repository can be checked out under two
    parents. Colliding labels therefore take one more ancestor at a time until
    they are distinct -- one ancestor is not always enough, because
    ``/a/Team/repo`` and ``/b/Team/repo`` both shorten to ``Team/repo``. A label
    that cannot be made unique even at full path depth falls back to the id,
    which is unique by construction.
    """
    parts = {id(p): _root_parts(p.get("root_path") or "") for p in projects}
    depth = {id(p): 1 for p in projects}

    def label(p: dict) -> str:
        pieces = parts[id(p)]
        if not pieces:
            return p["name"]
        return "/".join(pieces[-min(depth[id(p)], len(pieces)) :])

    # Deepen only the groups that still collide, so an unambiguous project keeps
    # its short label however deep an unrelated collision has to go.
    for _ in range(max((len(v) for v in parts.values()), default=1)):
        groups: dict[str, list[dict]] = {}
        for p in projects:
            groups.setdefault(label(p), []).append(p)
        clashing = [g for g in groups.values() if len(g) > 1]
        if not clashing:
            break
        progressed = False
        for group in clashing:
            for p in group:
                if depth[id(p)] < len(parts[id(p)]):
                    depth[id(p)] += 1
                    progressed = True
        if not progressed:
            break

    seen: dict[str, int] = {}
    for p in projects:
        text = label(p)
        seen[text] = seen.get(text, 0) + 1
    for p in projects:
        text = label(p)
        p["display_name"] = text if seen[text] == 1 else p["name"]
    return projects


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
        if _usable_project(item)
    ]
    projects = _with_display_names(projects)
    _projects_cache = (time.monotonic(), projects)
    return projects


def cached_projects() -> list[dict] | None:
    if _projects_cache is None:
        return None
    return _projects_cache[1]
