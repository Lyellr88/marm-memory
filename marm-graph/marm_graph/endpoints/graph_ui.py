"""UI-only REST endpoints for MARMIS.

These are NOT whitelisted into the FastApiMCP surface (server.py), so no AI
tools/list ever shows them — the boundary is a whitelist, not a filter. They are
still HTTP-facing, so the auth middleware gates them like everything else.

Extra guards on the higher-risk actions:
  - delete_project requires an explicit confirm=true
  - query_graph (Cypher) is read-only in v0.1 — write clauses are rejected
"""

import asyncio
import re

from fastapi import APIRouter
from pydantic import BaseModel

from ..core import cbm_client
from ..core.deps import get_client
from ..core.models import (
    DeleteProjectRequest,
    IngestTracesRequest,
    ManageAdrRequest,
    QueryGraphRequest,
)

router = APIRouter(tags=["ui"])

# Cypher write clauses rejected in v0.1 (read-only console).
_WRITE_CLAUSE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|FOREACH)\b",
    re.IGNORECASE,
)


class ProjectRequest(BaseModel):
    project: str


async def _call(tool: str, args: dict) -> dict:
    """Passthrough to the binary, translating failures into status dicts."""
    try:
        payload = await asyncio.to_thread(get_client().call_tool, tool, args)
    except cbm_client.CbmToolError as e:
        return {"status": "error", "message": str(e), "hint": e.hint, "payload": e.payload}
    except cbm_client.CbmError as e:
        return {"status": "error", "message": f"graph backend unavailable: {e}"}
    return payload if isinstance(payload, dict) else {"result": payload}


@router.post("/ui/projects", operation_id="ui_list_projects")
async def ui_list_projects() -> dict:
    return await _call("list_projects", {})


@router.post("/ui/index_status", operation_id="ui_index_status")
async def ui_index_status(req: ProjectRequest) -> dict:
    return await _call("index_status", {"project": req.project})


@router.post("/ui/graph_schema", operation_id="ui_graph_schema")
async def ui_graph_schema(req: ProjectRequest) -> dict:
    return await _call("get_graph_schema", {"project": req.project})


@router.post("/ui/query_graph", operation_id="ui_query_graph")
async def ui_query_graph(req: QueryGraphRequest) -> dict:
    if _WRITE_CLAUSE.search(req.query):
        return {
            "status": "rejected",
            "message": "query_graph is read-only in v0.1. Write clauses "
            "(CREATE/MERGE/DELETE/SET/REMOVE/DROP/...) are not permitted.",
        }
    return await _call(
        "query_graph",
        {"query": req.query, "project": req.project, "max_rows": req.max_rows},
    )


@router.post("/ui/delete_project", operation_id="ui_delete_project")
async def ui_delete_project(req: DeleteProjectRequest) -> dict:
    if not req.confirm:
        return {
            "status": "confirmation_required",
            "message": f"Deleting '{req.project}' is irreversible. Resend with confirm=true.",
        }
    return await _call("delete_project", {"project": req.project})


@router.post("/ui/manage_adr", operation_id="ui_manage_adr")
async def ui_manage_adr(req: ManageAdrRequest) -> dict:
    args = {"project": req.project, "mode": req.mode}
    if req.content is not None:
        args["content"] = req.content
    if req.sections is not None:
        args["sections"] = req.sections
    return await _call("manage_adr", args)


@router.post("/ui/ingest_traces", operation_id="ui_ingest_traces")
async def ui_ingest_traces(req: IngestTracesRequest) -> dict:
    return await _call("ingest_traces", {"project": req.project, "traces": req.traces})
