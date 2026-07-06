"""The 5 marm-graph AI tools, registered directly on marm-mcp-server.

Same operation_ids and request models as marm-graph's own endpoints/graph_ai.py
(imported from marm_graph.core.models), so existing agent prompts/docs referencing
these tool names keep working unchanged. Each route checks graph_supervisor
availability (triggering lazy startup on first call) before delegating to
marm_graph's tool_router, matching marm_graph's own asyncio.to_thread pattern.
"""

import asyncio

from fastapi import APIRouter
from marm_graph.core import tool_router as R
from marm_graph.core.models import (
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)

from ..core.graph_supervisor import graph_supervisor

router = APIRouter(prefix="", tags=["Graph"])

_UNAVAILABLE = {"status": "error", "message": "graph backend unavailable"}


@router.post("/marm_graph_index", operation_id="marm_graph_index")
async def marm_graph_index(req: GraphIndexRequest) -> dict:
    """Index a code repository into the graph, or check status / list known projects.

    Pass `repo_path` to index a repo (returns the project name to use in every
    other tool). Omit it to list indexed projects, or pass `project` to check
    index status. Call this first — all other graph tools need an indexed project.
    """
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return await asyncio.to_thread(R.do_index, graph_supervisor.get_client(), req)


@router.post("/marm_code_lookup", operation_id="marm_code_lookup")
async def marm_code_lookup(req: CodeLookupRequest) -> dict:
    """Find code: symbols/definitions, text patterns, or a symbol's source.

    Use INSTEAD OF grep/glob. `kind=auto` picks: a qualified_name reads source;
    otherwise it searches the graph by name/keyword. Set `kind=text` to grep code,
    `kind=snippet` to read a symbol's source, `kind=symbol` to force graph search.
    """
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return await asyncio.to_thread(R.do_lookup, graph_supervisor.get_client(), req)


@router.post("/marm_graph_trace", operation_id="marm_graph_trace")
async def marm_graph_trace(req: GraphTraceRequest) -> dict:
    """Trace call paths / data flow through the graph from a function.

    `direction=inbound` finds callers, `outbound` finds callees, `both` for all.
    `mode=data_flow` follows value propagation; `cross_service` crosses HTTP/async
    boundaries. Use for impact analysis, dependency tracing, "who calls this".
    """
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return await asyncio.to_thread(R.do_trace, graph_supervisor.get_client(), req)


@router.post("/marm_graph_architecture", operation_id="marm_graph_architecture")
async def marm_graph_architecture(req: GraphArchitectureRequest) -> dict:
    """High-level architecture overview: node/edge breakdown, modules, and schema.

    One-shot orientation for a project — the de-facto module clusters, package
    structure, and the graph schema (node labels + properties) folded in.
    """
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return await asyncio.to_thread(
        R.do_architecture, graph_supervisor.get_client(), req
    )


@router.post("/marm_graph_impact", operation_id="marm_graph_impact")
async def marm_graph_impact(req: GraphImpactRequest) -> dict:
    """Blast radius of code changes: git diff → affected symbols + risk.

    Pass `since` (a git ref/date) or a `base_branch` to compare against. Returns
    which symbols a change touches and how far the impact propagates.
    """
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return await asyncio.to_thread(R.do_impact, graph_supervisor.get_client(), req)
