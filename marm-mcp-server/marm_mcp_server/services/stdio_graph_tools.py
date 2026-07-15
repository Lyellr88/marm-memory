"""STDIO graph/concept-graph MCP tool registrations: marm_graph_index,
marm_code_lookup, marm_graph_trace, marm_graph_architecture,
marm_graph_impact, marm_concept_build, marm_concept_recall.

Registers onto the shared `mcp` instance from core/stdio_mcp_app.py at
import time -- server_stdio.py imports this module for that side effect.
"""

import asyncio
from typing import Literal, Optional

from pydantic import ValidationError

from ..core.stdio_mcp_app import mcp
from ..core.stdio_tool_lifecycle import _log_tool_call
from marm_mcp_server.core.graph_supervisor import graph_supervisor
from marm_mcp_server.endpoints.concepts import (
    marm_concept_build as _marm_concept_build_endpoint,
    _run_recall,
)
from marm_mcp_server.core.models import (
    ConceptBuildRequest,
    ConceptRecallRequest,
)
from marm_graph.core import tool_router as graph_router
from marm_graph.core.models import (
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)


def _graph_unavailable() -> dict:
    """Fresh dict per call -- _log_tool_call mutates result in place (protocol
    injection, compaction blocks), so a shared constant here would leak state
    (e.g. marm_protocol) into every subsequent unavailable response."""
    return {"status": "error", "message": "graph backend unavailable"}


async def _graph_available() -> bool:
    return await asyncio.to_thread(graph_supervisor.is_available)


@mcp.tool()
@_log_tool_call
async def marm_graph_index(
    repo_path: Optional[str] = None,
    project: Optional[str] = None,
    mode: Literal["full", "moderate", "fast"] = "moderate",
    action: Literal["auto", "index", "status", "list"] = "auto",
) -> dict:
    """
    🕸️ Index a code repository into the graph, or check status / list known projects.

    Pass `repo_path` to index a repo (returns the project name to use in every
    other tool). Omit it to list indexed projects, or pass `project` to check
    index status. Call this first — all other graph tools need an indexed project.

    Parameters:
    - repo_path: path to the repository to index; omit to list/status only
    - project: existing project name for a status check; omit to auto-resolve
    - mode: index depth — full | moderate | fast (default moderate)
    - action: auto | index | status | list (default auto; infers from repo_path presence)

    Returns: graph index/status/list response, or a graph-unavailable error if the
    graph backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = GraphIndexRequest(
        repo_path=repo_path, project=project, mode=mode, action=action
    )
    return await asyncio.to_thread(
        graph_router.do_index, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_code_lookup(
    query: str,
    project: Optional[str] = None,
    kind: Literal["auto", "symbol", "text", "snippet"] = "auto",
    regex: bool = False,
    file_pattern: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    🔎 Find code: symbols/definitions, text patterns, or a symbol's source.

    Use INSTEAD OF grep/glob. `kind=auto` picks: a qualified_name reads source;
    otherwise it searches the graph by name/keyword. Set `kind=text` to grep code,
    `kind=snippet` to read a symbol's source, `kind=symbol` to force graph search.

    Parameters:
    - query: symbol name, natural-language phrase, code/text pattern, or a qualified_name
    - project: project name; omit to auto-resolve
    - kind: auto | symbol | text | snippet (default auto)
    - regex: for text search, treat query as a regex (default False)
    - file_pattern: glob to scope search, e.g. "*.py" (optional)
    - limit: max results, 1-200 (default 20)

    Returns: graph lookup response, or a graph-unavailable error if the graph
    backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = CodeLookupRequest(
        query=query,
        project=project,
        kind=kind,
        regex=regex,
        file_pattern=file_pattern,
        limit=limit,
    )
    return await asyncio.to_thread(
        graph_router.do_lookup, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_graph_trace(
    function_name: str,
    project: Optional[str] = None,
    direction: Literal["inbound", "outbound", "both"] = "both",
    depth: int = 3,
    mode: Literal["calls", "data_flow", "cross_service"] = "calls",
    risk_labels: bool = True,
) -> dict:
    """
    🧭 Trace call paths / data flow through the graph from a function.

    `direction=inbound` finds callers, `outbound` finds callees, `both` for all.
    `mode=data_flow` follows value propagation; `cross_service` crosses HTTP/async
    boundaries. Use for impact analysis, dependency tracing, "who calls this".

    Parameters:
    - function_name: function or method to trace from
    - project: project name; omit to auto-resolve
    - direction: inbound | outbound | both (default both)
    - depth: max hops, 1-5 (default 3)
    - mode: calls | data_flow | cross_service (default calls)
    - risk_labels: add CRITICAL/HIGH/MEDIUM/LOW risk tiers by hop distance (default True)

    Returns: graph trace response, or a graph-unavailable error if the graph
    backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = GraphTraceRequest(
        function_name=function_name,
        project=project,
        direction=direction,
        depth=depth,
        mode=mode,
        risk_labels=risk_labels,
    )
    return await asyncio.to_thread(
        graph_router.do_trace, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_graph_architecture(
    project: Optional[str] = None,
) -> dict:
    """
    🏛️ High-level architecture overview: node/edge breakdown, modules, and schema.

    One-shot orientation for a project — the de-facto module clusters, package
    structure, and the graph schema (node labels + properties) folded in.

    Parameters:
    - project: project name; omit to auto-resolve

    Returns: graph architecture response, or a graph-unavailable error if the
    graph backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = GraphArchitectureRequest(project=project)
    return await asyncio.to_thread(
        graph_router.do_architecture, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_graph_impact(
    project: Optional[str] = None,
    since: Optional[str] = None,
    base_branch: str = "main",
    depth: int = 2,
) -> dict:
    """
    💥 Blast radius of code changes: git diff → affected symbols + risk.

    Pass `since` (a git ref/date) or a `base_branch` to compare against. Returns
    which symbols a change touches and how far the impact propagates.

    Parameters:
    - project: project name; omit to auto-resolve
    - since: git ref or date to compare from, e.g. HEAD~5, v0.5.0 (optional)
    - base_branch: base branch to diff against (default "main")
    - depth: impact propagation depth, 1-5 (default 2)

    Returns: graph impact response, or a graph-unavailable error if the graph
    backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = GraphImpactRequest(
        project=project, since=since, base_branch=base_branch, depth=depth
    )
    return await asyncio.to_thread(
        graph_router.do_impact, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_concept_build(
    session_name: Optional[str] = None,
    search_all: bool = False,
    project: Optional[str] = None,
    run_id: Optional[str] = None,
) -> dict:
    """
    🕸️ Extract entities/relationships from memory content into the concept graph.

    Scope with session_name or project for a targeted build, or pass
    search_all=True for everything (row-capped). Links extracted entities to
    marm-graph code symbols when available. Call this before marm_concept_recall
    — there's no data until a build has run at least once.

    Parameters:
    - session_name: scope extraction to this session; omit with search_all=True
    - search_all: extract across all sessions, row-capped (default False)
    - project: scope extraction to this project (optional)
    - run_id: optional Console build-run ID for status polling

    Returns: entities_extracted, relationships_created, code_links_created, duration_ms
    """
    try:
        req = ConceptBuildRequest(
            session_name=session_name,
            search_all=search_all,
            project=project,
            run_id=run_id,
        )
        return await _marm_concept_build_endpoint(req)
    except ValidationError:
        return {
            "status": "error",
            "message": "Concept build requires session_name, project, or search_all=True.",
        }
    except Exception:
        return {"status": "error", "message": "Concept build failed."}


@mcp.tool()
@_log_tool_call
async def marm_concept_recall(
    query: str,
    session_name: Optional[str] = None,
    limit: int = 10,
    depth: int = 1,
    direction: Literal["outgoing", "incoming", "both"] = "both",
    project: Optional[str] = None,
) -> dict:
    """
    🔎 Search the concept graph: entities, their relationships, and linked code.

    Query as a bare concept name for a lookup, or phrase it as "related to X"
    to emphasize traversal — both route from query shape alone. Returns empty
    lists (not an error) when marm_concept_build hasn't run yet or marm-graph
    has no matching code symbols.

    Parameters:
    - query: concept name, or a "related to X" style ask
    - session_name: scope to this session; omit to search across all (optional)
    - limit: max entities/relationships returned, 1-100 (default 10)
    - depth: max hop distance to traverse, 1-5 (default 1 = direct neighbors only)
    - direction: outgoing | incoming | both (default both)
    - project: scope to this project; entities with the same name in
      different projects are distinct nodes; omit to search across all (optional)

    Returns: entities, related_entities, linked_code
    """
    try:
        # Validate through the same pydantic model the HTTP endpoint uses --
        # limit (1-100) and depth (1-5) are plain ints on this signature, so
        # without this, an out-of-range STDIO call (e.g. limit=-1) would reach
        # SQLite as a raw LIMIT/BFS bound instead of being rejected.
        req = ConceptRecallRequest(
            query=query,
            session_name=session_name,
            limit=limit,
            depth=depth,
            direction=direction,
            project=project,
        )
        return await asyncio.to_thread(
            _run_recall,
            req.query,
            req.session_name,
            req.limit,
            req.depth,
            req.direction,
            req.project,
        )
    except Exception as e:
        return {"status": "error", "message": f"Concept recall failed: {e!s}"}
