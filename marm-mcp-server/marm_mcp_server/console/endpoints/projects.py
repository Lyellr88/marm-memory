"""Codebase graph (project) endpoints for MARM Console."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import mcp_client
from ..models import (
    ProjectDeletePayload,
    ProjectImpactPayload,
    ProjectIndexPayload,
    ProjectSearchPayload,
    ProjectTracePayload,
)

router = APIRouter()


@router.get("/api/projects")
def get_projects() -> list[dict]:
    try:
        return mcp_client.list_projects()
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/projects/index", status_code=202)
def index_project(payload: ProjectIndexPayload) -> dict:
    return _project_operation("internal/projects/index", payload.model_dump())


@router.get("/api/projects/jobs/{job_id}")
def get_index_job(job_id: str) -> dict:
    try:
        return mcp_client.get(f"internal/projects/jobs/{job_id}")
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/projects/{project}/status")
def get_project_status(project: str) -> dict:
    result = _project_operation("internal/projects/status", {"project": project})
    upstream_status = str(result.get("status", "ready")).lower()
    status = {
        "success": "ready",
        "completed": "ready",
        "running": "indexing",
        "queued": "indexing",
    }.get(upstream_status, upstream_status)
    if status not in {"ready", "indexing", "error", "unknown"}:
        status = "unknown"
    return {
        "name": project,
        "status": status,
        "nodes": result.get("nodes", 0),
        "edges": result.get("edges", 0),
        "last_indexed_at": result.get("last_indexed_at"),
        "error": result.get("error"),
    }


def _type_entries(rows: object, key: str) -> list[dict]:
    """Reduce the graph engine's label aspects to the `{name, count}` the UI declares.

    The engine reports these as counted rows, `{"label": "Function", "count": 2028}`
    for nodes and `{"type": "CALLS", "count": 6632}` for edges, and the
    get_graph_schema fallback adds a `properties` array to each. React raises on an
    object child, so a row that reaches a badge unreduced fails the whole
    Architecture tab on its first badge rather than rendering oddly. Only `name` is
    ever rendered as a child; `count` is rendered separately or not at all.

    The count is carried rather than dropped because it is the only indication of
    the graph's scale the tab has, and the engine already paid to compute it.
    """
    if not isinstance(rows, list):
        return []
    entries: list[dict] = []
    for row in rows:
        count: object = None
        if isinstance(row, str):
            candidate: object = row
        elif isinstance(row, dict):
            candidate = row.get(key) or row.get("label") or row.get("type")
            count = row.get("count")
        else:
            continue
        if isinstance(candidate, str) and candidate:
            entry: dict = {"name": candidate}
            # bool is an int subclass, and a stray True must not render as a count.
            if isinstance(count, int) and not isinstance(count, bool):
                entry["count"] = count
            entries.append(entry)
    return entries


@router.get("/api/projects/{project}/architecture")
def get_project_architecture(project: str) -> dict:
    result = _project_operation("internal/projects/architecture", {"project": project})
    modules = result.get("modules", result.get("module_summary", []))
    schema = result.get("schema", {})
    if not isinstance(schema, dict):
        schema = {}
    return {
        "name": project,
        "modules": modules if isinstance(modules, list) else [],
        "schema": {
            "node_types": _type_entries(
                result.get("node_labels")
                or schema.get("node_labels")
                or schema.get("node_types", []),
                "label",
            ),
            "edge_types": _type_entries(
                result.get("edge_types")
                or schema.get("edge_types")
                or schema.get("edge_labels")
                or schema.get("relationship_types", []),
                "type",
            ),
        },
    }


@router.get("/api/projects/{project}/code-units")
def get_project_code_units(project: str) -> dict:
    """Pass-through. code_graph_view already returns the browser's shape.

    Unlike the architecture endpoint above, no normalization happens here: that
    one has to reshape at the last hop because the shared router cannot change,
    and this one owns its response end to end.
    """
    return _project_operation("internal/projects/code-units", {"project": project})


@router.post("/api/projects/{project}/search")
def search_project_code(project: str, payload: ProjectSearchPayload) -> list[dict]:
    result = _project_operation(
        "internal/projects/search", {"project": project, **payload.model_dump()}
    )
    rows = result.get("results", result.get("matches", []))
    if not isinstance(rows, list):
        rows = [result]
    return [
        {
            "qualified_name": row.get("qualified_name", row.get("name", "")),
            "file_path": row.get("file_path", row.get("path", "")),
            "line": row.get("line", row.get("line_number")),
            "snippet": row.get("snippet", row.get("content", row.get("code"))),
            "kind": row.get("kind", row.get("type", "result")),
        }
        for row in rows
        if isinstance(row, dict)
    ]


@router.post("/api/projects/{project}/trace")
def trace_project(project: str, payload: ProjectTracePayload) -> dict:
    result = _project_operation(
        "internal/projects/trace", {"project": project, **payload.model_dump()}
    )
    steps = []
    for relation, rows in (
        ("caller", result.get("callers", [])),
        ("callee", result.get("callees", [])),
    ):
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                steps.append(
                    {
                        "qualified_name": row.get(
                            "qualified_name", row.get("name", "")
                        ),
                        "file_path": row.get("file_path", row.get("path", "")),
                        "relation": relation,
                    }
                )
    return {
        "root": result.get("function", payload.symbol),
        "steps": steps,
        "truncated": bool(result.get("_marm_graph_truncated", False)),
    }


@router.post("/api/projects/{project}/impact")
def project_impact(project: str, payload: ProjectImpactPayload) -> dict:
    result = _project_operation(
        "internal/projects/impact", {"project": project, **payload.model_dump()}
    )
    affected = result.get("affected_symbols", result.get("affected", []))
    return {
        "changed_files": result.get("changed_files", []),
        "affected_symbols": [
            {
                "qualified_name": row.get("qualified_name", row.get("name", "")),
                "file_path": row.get("file_path", row.get("path", "")),
                "risk": str(row.get("risk", "low")).lower(),
            }
            for row in affected
            if isinstance(row, dict)
        ],
    }


@router.delete("/api/projects/{project}")
def delete_project(project: str, payload: ProjectDeletePayload) -> dict:
    return _project_operation(
        "internal/projects/delete", {"project": project, **payload.model_dump()}
    )


def _project_operation(operation: str, payload: dict) -> dict:
    try:
        result = mcp_client.post(operation, payload, timeout=30.0)
    except mcp_client.McpRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except mcp_client.McpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result.get("status") == "error":
        raise HTTPException(
            status_code=503, detail=result.get("message", "Graph operation failed.")
        )
    return result
