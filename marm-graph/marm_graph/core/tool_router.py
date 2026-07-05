"""Intent routing for the 5 AI super-tools.

Each `do_*` function maps one marm-graph tool onto one or more upstream
codebase-memory-mcp tools, resolving the project name and bounding response size.
Upstream tool/transport failures are converted to `{"status": "error", ...}`
dicts so tools return clean JSON rather than raising through the MCP layer.

Grounded in observed payloads (see protocol-proof.md §5 and scratchpad probes):
  - index_repository returns the auto-derived project name
  - list_projects entries carry .name / .root_path / .nodes / .edges
  - search_graph(query=) is BM25; search_graph(name_pattern=) is regex
  - search_code(pattern=) is grep + graph enrichment
"""

from __future__ import annotations

import functools
import json
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

# A dotted identifier path with >=3 segments (>=2 dots) and no spaces reads as a
# qualified_name. Segments allow '-' because the auto-derived project prefix is
# hyphenated (e.g. C-Users-...-marm-graph.marm_graph.core.Cls.method).
_QN_RE = re.compile(r"^[\w-]+(?:\.[\w-]+){2,}$")
_REGEX_META = set(".*+?[](){}^$\\|")
_TRIMMABLE_LIST_KEYS = ("results", "semantic_results", "matches", "paths", "affected")


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

    # 1) structural trim first — keeps the response shape the caller expects.
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
            trimmed_key = key  # only credit a key that was actually shortened
        if _size(data) <= MAX_RESPONSE_BYTES:
            break

    # Mark + reason are set BEFORE the size checks below so their own bytes are
    # inside the budget being fit (otherwise they can push a just-fit payload
    # back over the cap).
    data["_marm_graph_truncated"] = True
    if trimmed_key:
        data["_truncation_reason"] = (
            f"Response exceeded {MAX_RESPONSE_BYTES} bytes; '{trimmed_key}' "
            f"trimmed. Narrow the query or use pagination."
        )
    if _size(data) <= MAX_RESPONSE_BYTES:
        return data

    # 2) no trimmable list got us under the cap (e.g. one huge snippet or
    #    schema). Clip the largest string leaves until the envelope fits.
    data["_truncation_reason"] = (
        f"Response exceeded {MAX_RESPONSE_BYTES} bytes; oversized text was "
        f"clipped. Request a narrower slice."
    )
    if _clip_to_fit(data):
        return data

    # 3) still over (deep non-string bloat): drop the body for a bounded notice.
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
        items = node.items() if isinstance(node, dict) else (
            enumerate(node) if isinstance(node, list) else ()
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


@safe
def do_index(client: CbmClient, req: GraphIndexRequest) -> dict:
    action = req.action
    if action == "auto":
        action = "index" if req.repo_path else ("status" if req.project else "list")

    if action == "list":
        return _bound(client.call_tool("list_projects", {}))

    if action == "status":
        proj, err = resolve_project(client, req.project)
        if err:
            return err
        return _bound(client.call_tool("index_status", {"project": proj}))

    # index
    if not req.repo_path:
        return {"status": "error", "message": "repo_path is required to index a repository."}
    return _bound(
        client.call_tool(
            "index_repository", {"repo_path": req.repo_path, "mode": req.mode}
        )
    )


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
        return _bound(client.call_tool("search_code", args))

    # symbol (default): BM25 discovery, or regex name match if the query looks like one
    if any(ch in _REGEX_META for ch in req.query):
        args = {"project": proj, "name_pattern": req.query, "limit": req.limit}
    else:
        args = {"project": proj, "query": req.query, "limit": req.limit}
    if req.file_pattern:
        args["file_pattern"] = req.file_pattern
    return _bound(client.call_tool("search_graph", args))


# ── marm_graph_trace ────────────────────────────────────────────────


@safe
def do_trace(client: CbmClient, req: GraphTraceRequest) -> dict:
    proj, err = resolve_project(client, req.project)
    if err:
        return err
    return _bound(
        client.call_tool(
            "trace_path",
            {
                "function_name": req.function_name,
                "project": proj,
                "direction": req.direction,
                "depth": req.depth,
                "mode": req.mode,
                "risk_labels": req.risk_labels,
            },
        )
    )


# ── marm_graph_architecture ─────────────────────────────────────────


@safe
def do_architecture(client: CbmClient, req: GraphArchitectureRequest) -> dict:
    proj, err = resolve_project(client, req.project)
    if err:
        return err
    arch = client.call_tool("get_architecture", {"project": proj})
    if isinstance(arch, dict):
        try:
            arch["schema"] = client.call_tool("get_graph_schema", {"project": proj})
        except CbmToolError:
            pass  # schema is a nice-to-have fold-in, not essential
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
    }
    if req.since:
        args["since"] = req.since
    return _bound(client.call_tool("detect_changes", args))
