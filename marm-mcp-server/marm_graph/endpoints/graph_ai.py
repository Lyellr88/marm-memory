"""The 5 AI-facing MCP tools.

Only these operation_ids are whitelisted into the FastApiMCP surface (see
server.py). Their docstrings become the tool descriptions the AI reads. Each
delegates to tool_router, running the blocking subprocess round-trip off the
event loop via asyncio.to_thread.
"""

import asyncio

from fastapi import APIRouter

from ..core import tool_router as R
from ..core.deps import get_client
from ..core.models import (
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)

router = APIRouter(tags=["ai"])


@router.post("/tools/graph_index", operation_id="marm_graph_index")
async def marm_graph_index(req: GraphIndexRequest) -> dict:
    """Index a code repository into the graph, or check status / list known projects.

    Pass `repo_path` to index a repo (returns the project name to use in every
    other tool). Omit it to list indexed projects, or pass `project` to check
    index status. Call this first — all other graph tools need an indexed project.
    """
    return await asyncio.to_thread(R.do_index, get_client(), req)


@router.post("/tools/code_lookup", operation_id="marm_code_lookup")
async def marm_code_lookup(req: CodeLookupRequest) -> dict:
    """Find code: symbols/definitions, text patterns, or a symbol's source.

    Use INSTEAD OF grep/glob. `kind=auto` picks: a qualified_name reads source;
    otherwise it searches the graph by name/keyword. Set `kind=text` to grep code,
    `kind=snippet` to read a symbol's source, `kind=symbol` to force graph search.
    """
    return await asyncio.to_thread(R.do_lookup, get_client(), req)


@router.post("/tools/graph_trace", operation_id="marm_graph_trace")
async def marm_graph_trace(req: GraphTraceRequest) -> dict:
    """Trace call paths / data flow through the graph from a function.

    `direction=inbound` finds callers, `outbound` finds callees, `both` for all.
    `mode=data_flow` follows value propagation. `cross_service` attempts HTTP/async
    boundaries but does not currently join a client call to its server handler, so
    treat an empty result as unknown rather than as "nothing calls this".
    Use for impact analysis, dependency tracing, "who calls this".
    """
    return await asyncio.to_thread(R.do_trace, get_client(), req)


@router.post("/tools/graph_architecture", operation_id="marm_graph_architecture")
async def marm_graph_architecture(req: GraphArchitectureRequest) -> dict:
    """High-level architecture overview: node/edge breakdown, modules, and schema.

    One-shot orientation for a project — the de-facto module clusters, package
    structure, and the graph schema (node labels + properties) folded in.
    """
    return await asyncio.to_thread(R.do_architecture, get_client(), req)


@router.post("/tools/graph_impact", operation_id="marm_graph_impact")
async def marm_graph_impact(req: GraphImpactRequest) -> dict:
    """Blast radius of code changes: git diff → affected symbols + risk.

    Pass `since` (a git ref/date) or a `base_branch` to compare against. Returns
    which symbols a change touches and how far the impact propagates.
    """
    return await asyncio.to_thread(R.do_impact, get_client(), req)
