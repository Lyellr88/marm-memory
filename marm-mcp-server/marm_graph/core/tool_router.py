from __future__ import annotations

import functools
import json
import os
import re
from typing import Any, Callable, Optional

import structlog

from ..config.settings import MAX_RESPONSE_BYTES
from .cbm_client import CbmClient, CbmError, CbmToolError
from .models import (
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)

logger = structlog.get_logger(__name__)

_QN_RE = re.compile(r"^[\w-]+(?:\.[\w-]+){2,}$")
_REGEX_META = set(".*+?[](){}^$\\|")
_TRIMMABLE_LIST_KEYS = (
    "results",
    "semantic_results",
    "matches",
    "paths",
    "affected",
    "callers",
    "callees",
)


def safe(fn: Callable[..., dict]) -> Callable[..., dict]:
    """Convert upstream failures into status dicts instead of exceptions."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except CbmToolError as e:
            logger.info("router.tool_error", tool=fn.__name__, error=str(e))
            return {
                "status": "error",
                "message": str(e),
                "hint": e.hint,
                "payload": e.payload,
            }
        except CbmError as e:
            logger.warning("router.backend_error", tool=fn.__name__, error=str(e))
            return {
                "status": "error",
                "message": f"graph backend unavailable: {e}",
            }

    return wrapper


_CLIP_MARK = " …[marm-graph clipped]"

_SEARCH_GRAPH_RENAMES = {"qn": "qualified_name", "file": "file_path"}
_SEARCH_CODE_RENAMES = {
    "qn": "qualified_name",
    "matches": "match_lines",
    "in": "in_degree",
    "out": "out_degree",
}
_ARCHITECTURE_RENAMES = {
    "languages": {"files": "file_count"},
    "packages": {"nodes": "node_count"},
    "entry_points": {"qn": "qualified_name"},
    "hotspots": {"qn": "qualified_name"},
    "boundaries": {"calls": "call_count"},
}
_ARCHITECTURE_NAMED = {"entry_points", "hotspots"}

_ARCHITECTURE_ASPECTS = ["all"]


def _split_lines_span(value: Any) -> dict:
    """Expand 0.10.5's "321-347" line span back into start_line / end_line."""
    if isinstance(value, int):
        return {"start_line": value, "end_line": value}
    if not isinstance(value, str) or not value.strip():
        return {}
    start, _, end = value.partition("-")
    try:
        first = int(start)
    except ValueError:
        return {}
    try:
        last = int(end) if end else first
    except ValueError:
        last = first
    return {"start_line": first, "end_line": last}


def _rows_to_dicts(
    block: Any,
    renames: Optional[dict] = None,
    name_key: Optional[str] = None,
) -> Any:
    """Flatten a {"cols": [...], "rows": [[...]]} block into a list of dicts."""
    if isinstance(block, list):
        return block
    if not isinstance(block, dict):
        return []
    cols = block.get("cols")
    rows = block.get("rows")
    if not isinstance(cols, list) or not isinstance(rows, list):
        return []
    renames = renames or {}
    names = [renames.get(col, col) for col in cols]
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            continue
        item = dict(zip(names, row))
        if "lines" in item:
            item.update(_split_lines_span(item.pop("lines")))
        qname = item.get("qualified_name")
        if name_key and isinstance(qname, str) and qname:
            item.setdefault(name_key, qname.rsplit(".", 1)[-1])
        out.append(item)
    return out


def _is_columnar(value: Any) -> bool:
    return isinstance(value, dict) and "cols" in value and "rows" in value


def _groups_to_callers(block: Any, renames: Optional[dict] = None) -> Any:
    """Flatten a grouped trace block, rebuilding each row's qualified_name.

    The prefix lives on the group, not the row, so a row's identity is only
    complete once the two are joined. Two callers can share `name` and differ
    only by prefix, which is why the joined `qualified_name` is not optional.
    """
    if isinstance(block, list):
        return block
    if not isinstance(block, dict):
        return []
    cols = block.get("cols")
    groups = block.get("groups")
    if not isinstance(cols, list) or not isinstance(groups, list):
        return []
    renames = renames or {}
    names = [renames.get(col, col) for col in cols]
    out: list[dict] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        prefix = group.get("qn_prefix") or ""
        file_path = group.get("file")
        for row in group.get("rows") or []:
            if not isinstance(row, (list, tuple)):
                continue
            item = dict(zip(names, row))
            if "lines" in item:
                item.update(_split_lines_span(item.pop("lines")))
            name = item.get("name")
            if name is not None:
                item["qualified_name"] = f"{prefix}.{name}" if prefix else str(name)
            if isinstance(file_path, str) and file_path:
                item["file_path"] = file_path
            out.append(item)
    return out


def _converted_search(res: Any) -> Any:
    """Restore `results` on a search_graph reply, whichever shape it arrived in."""
    if isinstance(res, dict) and isinstance(res.get("groups"), list):
        out = {k: v for k, v in res.items() if k not in ("cols", "groups")}
        out["results"] = _groups_to_callers(res, _SEARCH_GRAPH_RENAMES)
        return out
    if not _is_columnar(res):
        return res
    out = {k: v for k, v in res.items() if k not in ("cols", "rows")}
    out["results"] = _rows_to_dicts(res, _SEARCH_GRAPH_RENAMES, name_key="name")
    return out


def _converted_code_search(res: Any) -> Any:
    """Restore `results` on a search_code reply, including its nested raw_matches."""
    if not isinstance(res, dict):
        return res
    if _is_columnar(res):
        out = {k: v for k, v in res.items() if k not in ("cols", "rows")}
        out["results"] = _rows_to_dicts(res, _SEARCH_CODE_RENAMES, name_key="node")
    else:
        out = dict(res)
    if _is_columnar(out.get("raw_matches")):
        out["raw_matches"] = _rows_to_dicts(out["raw_matches"])
    return out


def _converted_architecture(arch: Any) -> Any:
    """Flatten every columnar aspect block get_architecture returns."""
    if not isinstance(arch, dict):
        return arch
    out = {}
    for key, value in arch.items():
        if _is_columnar(value):
            out[key] = _rows_to_dicts(
                value,
                _ARCHITECTURE_RENAMES.get(key),
                name_key="name" if key in _ARCHITECTURE_NAMED else None,
            )
        else:
            out[key] = value
    return out


def _converted_trace(res: Any) -> Any:
    """Restore `callers`/`callees` as lists of dicts on a trace_path reply."""
    if not isinstance(res, dict):
        return res
    for key in ("callers", "callees"):
        if key in res:
            res[key] = _groups_to_callers(res[key])
    return res


def _converted_impact(res: Any) -> Any:
    """Restore `impacted_symbols`, keeping 0.10.5's added totals alongside."""
    if not isinstance(res, dict) or "impacted" not in res:
        return res
    out = dict(res)
    out["impacted_symbols"] = out.pop("impacted")
    return out


def _bound(data: Any) -> Any:
    """Guarantee a response stays under MAX_RESPONSE_BYTES.

    Three stages, escalating only as needed:
      1. structural trim of known result lists (preserves response shape)
      2. clip the largest string leaves (for single huge snippet/schema bodies
         that have no trimmable list)
      3. last-resort bounded notice if the payload still cannot be fit
    """
    if not isinstance(data, dict):
        data = {"result": data}
    if _size(data) <= MAX_RESPONSE_BYTES:
        return data

    trimmed_key = None
    for key in _TRIMMABLE_LIST_KEYS:
        lst = data.get(key)
        if not isinstance(lst, list) or not lst:
            continue
        original_len = len(lst)
        while len(lst) > 1 and _size(data) > MAX_RESPONSE_BYTES:
            lst = lst[: max(1, len(lst) // 2)]
            data[key] = lst
        if len(lst) < original_len:
            trimmed_key = key
        if _size(data) <= MAX_RESPONSE_BYTES:
            break

    data["_marm_graph_truncated"] = True
    if trimmed_key:
        data["_truncation_reason"] = (
            f"Response exceeded {MAX_RESPONSE_BYTES} bytes; '{trimmed_key}' "
            f"trimmed. Narrow the query or use pagination."
        )
    if _size(data) <= MAX_RESPONSE_BYTES:
        return data

    data["_truncation_reason"] = (
        f"Response exceeded {MAX_RESPONSE_BYTES} bytes; oversized text was "
        f"clipped. Request a narrower slice."
    )
    if _clip_to_fit(data):
        return data

    return {
        "status": "too_large",
        "_marm_graph_truncated": True,
        "message": (
            f"Response exceeded {MAX_RESPONSE_BYTES} bytes and could not be "
            f"bounded structurally. Narrow the query."
        ),
        "keys": list(data.keys()),
    }


def _largest_string_ref(root: Any) -> Optional[tuple]:
    """Return (container, key_or_index, length) for the longest str leaf, or None."""
    best: Optional[tuple] = None

    def walk(node: Any) -> None:
        nonlocal best
        items = (
            node.items()
            if isinstance(node, dict)
            else (enumerate(node) if isinstance(node, list) else ())
        )
        for k, v in items:
            if isinstance(v, str):
                if best is None or len(v) > best[2]:
                    best = (node, k, len(v))
            else:
                walk(v)

    walk(root)
    return best


def _clip_to_fit(data: dict) -> bool:
    """Best-effort: clip the largest string leaves until `data` fits the cap."""
    for _ in range(32):
        over = _size(data) - MAX_RESPONSE_BYTES
        if over <= 0:
            return True
        ref = _largest_string_ref(data)
        if ref is None:
            return False
        container, key, length = ref
        keep = max(0, length - over - len(_CLIP_MARK) - 8)
        container[key] = container[key][:keep] + _CLIP_MARK
    return _size(data) <= MAX_RESPONSE_BYTES


def _size(data: dict) -> int:
    try:
        return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


def resolve_project(
    client: CbmClient, project: Optional[str]
) -> tuple[Optional[str], Optional[dict]]:
    """Return (project_name, None) or (None, guidance_dict)."""
    if project:
        return project, None
    projects = client.call_tool("list_projects", {}).get("projects", [])
    names = [p.get("name") if isinstance(p, dict) else p for p in projects]
    if len(names) == 1:
        return names[0], None
    if not names:
        return None, {
            "status": "no_project",
            "message": "No projects indexed. Call marm_graph_index(repo_path=...) first.",
        }
    return None, {
        "status": "ambiguous_project",
        "message": "Multiple projects indexed. Pass `project` to choose one.",
        "projects": names,
    }


# ── marm_graph_index ────────────────────────────────────────────────
_WINDOWS_PATH_LIMIT = 260
_WINDOWS_PATH_MARGIN = 12


def _predicted_store_path_length(repo_path: str) -> int:
    """Length of the database path the engine will derive from `repo_path`.

    The engine names each project's database after the repository's full path
    with the drive colon dropped and separators replaced, inside its own cache
    directory. That is an internal which can change on a version bump, which is
    why this is only ever used to improve an error message and never to refuse a
    call: a wrong guess here costs a hint, not an index.

    Measured against the -wal suffix rather than .db, because the write-ahead log
    is the longest of the sibling files and so the first one to cross the limit.
    """
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    store = os.path.join(home, ".cache", "codebase-memory-mcp")
    project = repo_path.replace(":", "").replace("\\", "-").replace("/", "-")
    return len(os.path.join(store, project + ".db-wal"))


def _windows_path_limit_error(repo_path: str, exc: CbmToolError) -> Optional[dict]:
    """Recognize a Win32 path-length failure behind the engine's generic message.

    The engine reports this as a contained per-file worker crash and advises
    re-running, which can never succeed: nothing about the path changes between
    attempts. Users follow that hint into hunting for a corrupt source file that
    does not exist.
    """
    if os.name != "nt":
        return None
    payload = exc.payload if isinstance(exc.payload, dict) else {}
    if payload.get("outcome") != "exit_nonzero":
        return None
    predicted = _predicted_store_path_length(repo_path)
    if predicted < _WINDOWS_PATH_LIMIT - _WINDOWS_PATH_MARGIN:
        return None
    return {
        "status": "error",
        "error_code": "windows_path_too_long",
        "message": str(exc),
        "hint": (
            f"The repository path is {len(repo_path)} characters long, which makes "
            f"the graph engine's database path about {predicted} characters against "
            f"Windows' {_WINDOWS_PATH_LIMIT}-character limit, so its indexing worker "
            "cannot open it. Re-running will not help. Index the repository from a "
            "shallower path, or enable Win32 long paths."
        ),
        "payload": payload,
    }


@safe
def do_index(client: CbmClient, req: GraphIndexRequest) -> dict:
    action = req.action
    if action == "auto":
        action = "index" if req.repo_path else ("status" if req.project else "list")

    if action in ("auto_on", "auto_off", "auto_status"):
        return {
            "status": "error",
            "error_code": "unsupported_action",
            "message": (
                f"'{action}' is only available on marm-mcp-server, which owns the "
                "auto-index poller. Standalone marm-graph indexes on request only."
            ),
        }

    if action == "list":
        return _bound(client.call_tool("list_projects", {}))

    if action == "status":
        proj, err = resolve_project(client, req.project)
        if err:
            return err
        return _bound(client.call_tool("index_status", {"project": proj}))

    if not req.repo_path:
        return {
            "status": "error",
            "message": "repo_path is required to index a repository.",
        }
    try:
        return _bound(
            client.call_tool(
                "index_repository", {"repo_path": req.repo_path, "mode": req.mode}
            )
        )
    except CbmToolError as exc:
        diagnosed = _windows_path_limit_error(req.repo_path, exc)
        if diagnosed is not None:
            return diagnosed
        raise


# ── marm_code_lookup ────────────────────────────────────────────────
@safe
def do_lookup(client: CbmClient, req: CodeLookupRequest) -> dict:
    proj, err = resolve_project(client, req.project)
    if err:
        return err

    kind = req.kind
    if kind == "auto":
        kind = "snippet" if _QN_RE.match(req.query.strip()) else "symbol"

    if kind == "snippet":
        return _bound(
            client.call_tool(
                "get_code_snippet", {"qualified_name": req.query, "project": proj}
            )
        )

    if kind == "text":
        args = {
            "pattern": req.query,
            "project": proj,
            "regex": req.regex,
            "limit": req.limit,
        }
        if req.file_pattern:
            args["file_pattern"] = req.file_pattern
        args["format"] = "json"
        return _bound(_converted_code_search(client.call_tool("search_code", args)))

    if any(ch in _REGEX_META for ch in req.query):
        args = {"project": proj, "name_pattern": req.query, "limit": req.limit}
    else:
        args = {"project": proj, "query": req.query, "limit": req.limit}
    if req.file_pattern:
        args["file_pattern"] = req.file_pattern
    args["format"] = "json"
    return _bound(_converted_search(client.call_tool("search_graph", args)))


# ── marm_graph_trace ────────────────────────────────────────────────
@safe
def do_trace(client: CbmClient, req: GraphTraceRequest) -> dict:
    proj, err = resolve_project(client, req.project)
    if err:
        return err
    return _bound(
        _converted_trace(
            client.call_tool(
                "trace_path",
                {
                    "function_name": req.function_name,
                    "project": proj,
                    "direction": req.direction,
                    "depth": req.depth,
                    "mode": req.mode,
                    "risk_labels": req.risk_labels,
                    "include_tests": req.include_tests,
                    "include_evidence": req.include_evidence,
                    "format": "json",
                },
            )
        )
    )


# ── marm_graph_architecture ─────────────────────────────────────────
@safe
def do_architecture(client: CbmClient, req: GraphArchitectureRequest) -> dict:
    proj, err = resolve_project(client, req.project)
    if err:
        return err
    arch = _converted_architecture(
        client.call_tool(
            "get_architecture",
            {"project": proj, "format": "json", "aspects": _ARCHITECTURE_ASPECTS},
        )
    )
    if isinstance(arch, dict):
        try:
            arch["schema"] = client.call_tool("get_graph_schema", {"project": proj})
        except (CbmToolError, CbmError):
            pass
        return _bound(arch)
    return _bound({"architecture": arch})


# ── marm_graph_impact ───────────────────────────────────────────────
@safe
def do_impact(client: CbmClient, req: GraphImpactRequest) -> dict:
    proj, err = resolve_project(client, req.project)
    if err:
        return err
    args: dict[str, Any] = {
        "project": proj,
        "depth": req.depth,
        "base_branch": req.base_branch,
        "format": "json",
    }
    if req.since:
        args["since"] = req.since
    return _bound(_converted_impact(client.call_tool("detect_changes", args)))
