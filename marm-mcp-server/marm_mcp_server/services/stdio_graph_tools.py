"""STDIO graph/concept-graph MCP tool bodies: marm_graph_index,
marm_code_lookup, marm_graph_trace, marm_graph_architecture,
marm_graph_impact, marm_concept_build, marm_concept_recall.

Deliberately not decorated with @mcp.tool() here -- registration is import
order-dependent by construction (whichever module's decorators execute
first wins), so importing this module anywhere before server_stdio.py
(e.g. a future test's top-level import, a script, a REPL session) would
silently register these 7 tools ahead of the 7 core ones defined in
server_stdio.py, reversing tools/list order. register_graph_tools() below
is called explicitly from server_stdio.py's own bootstrap instead, after
the core tools are already registered, so order is deterministic
regardless of import order.
"""

import asyncio
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from marm_graph.core.cbm_client import CbmClient

from pydantic import ValidationError

from marm_graph.core import tool_router as graph_router
from marm_graph.core.models import (
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)
from marm_mcp_server.core.graph_index_lock import GraphIndexBusy, run_exclusive
from marm_mcp_server.core.graph_index_worker import (
    AUTO_ACTIONS,
    auto_action,
    index_repository,
)
from marm_mcp_server.core.graph_supervisor import graph_supervisor
from marm_mcp_server.core.models import (
    ConceptBuildRequest,
    ConceptRecallRequest,
)
from marm_mcp_server.endpoints.concepts import (
    _run_recall,
)
from marm_mcp_server.endpoints.concepts import (
    marm_concept_build as _marm_concept_build_endpoint,
)

from ..core.stdio_logging import _stdio_log
from ..core.stdio_tool_lifecycle import _log_tool_call


def _graph_unavailable() -> dict:
    """Fresh dict per call -- _log_tool_call mutates result in place (protocol
    injection, compaction blocks), so a shared constant here would leak state
    (e.g. marm_protocol) into every subsequent unavailable response."""
    return {"status": "error", "message": "graph backend unavailable"}


async def _acquire_client() -> Optional["CbmClient"]:
    """The supervisor's client, or None when the backend is unusable.

    One read rather than an availability check followed by a separate fetch:
    stop() can complete between the two, and the fetch then returns None to code
    that has already decided the backend is up.
    """
    return await asyncio.to_thread(graph_supervisor.get_client)


@_log_tool_call
async def marm_graph_index(
    repo_path: Optional[str] = None,
    project: Optional[str] = None,
    mode: Literal["full", "moderate", "fast"] = "moderate",
    action: Literal[
        "auto", "index", "status", "list", "auto_on", "auto_off", "auto_status"
    ] = "auto",
) -> dict:
    """
    🕸️ Index a code repository into the graph, or check status / list known projects.

    Pass `repo_path` to index a repo (returns the project name to use in every
    other tool). Omit it to list indexed projects, or pass `project` to check
    index status. Call this first — all other graph tools need an indexed project.

    Indexed repos are re-indexed automatically in the background. Use
    `action="auto_off"` to stop that, `auto_on` to resume, `auto_status` to check.

    Parameters:
    - repo_path: path to the repository to index; omit to list/status only
    - project: existing project name for a status check; omit to auto-resolve
    - mode: index depth — full | moderate | fast (default moderate)
    - action: auto | index | status | list (default auto; infers from repo_path
      presence), or auto_on | auto_off | auto_status to control automatic
      re-indexing

    Returns: graph index/status/list response, or a graph-unavailable error if the
    graph backend is disabled or failed to start
    """
    # Ahead of _acquire_client(), which refuses when the engine is down and
    # starts it as a side effect. The off switch must work in either state.
    if action in AUTO_ACTIONS:
        return await asyncio.to_thread(auto_action, action)
    client = await _acquire_client()
    if client is None:
        return _graph_unavailable()
    req = GraphIndexRequest(
        repo_path=repo_path, project=project, mode=mode, action=action
    )
    if action == "index" or (action == "auto" and repo_path):
        try:
            # index_repository, not do_index: the tombstone and the path-limit
            # marker are settled inside the gate, where they cannot race the
            # other transport's poller writing the opposite answer.
            return await run_exclusive(
                "manual_index:stdio",
                index_repository,
                client,
                req,
            )
        except GraphIndexBusy as busy:
            return {
                "status": "error",
                "error_code": "index_in_progress",
                "message": str(busy),
            }
    return await asyncio.to_thread(graph_router.do_index, client, req)


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
    client = await _acquire_client()
    if client is None:
        return _graph_unavailable()
    req = CodeLookupRequest(
        query=query,
        project=project,
        kind=kind,
        regex=regex,
        file_pattern=file_pattern,
        limit=limit,
    )
    return await asyncio.to_thread(graph_router.do_lookup, client, req)


@_log_tool_call
async def marm_graph_trace(
    function_name: str,
    project: Optional[str] = None,
    direction: Literal["inbound", "outbound", "both"] = "both",
    depth: int = 3,
    mode: Literal["calls", "data_flow", "cross_service"] = "calls",
    risk_labels: bool = True,
    include_tests: bool = False,
    include_evidence: bool = True,
) -> dict:
    """
    🧭 Trace call paths / data flow through the graph from a function.

    `direction=inbound` finds callers, `outbound` finds callees, `both` for all.
    `mode=data_flow` follows value propagation. `cross_service` attempts HTTP/async
    boundaries but does not currently join a client call to its server handler, so
    treat an empty result as unknown rather than as "nothing calls this".
    Use for impact analysis, dependency tracing, "who calls this".

    Parameters:
    - function_name: function or method to trace from
    - project: project name; omit to auto-resolve
    - direction: inbound | outbound | both (default both)
    - depth: max hops, 1-5 (default 3)
    - mode: calls | data_flow | cross_service (default calls)
    - risk_labels: add CRITICAL/HIGH/MEDIUM/LOW risk tiers by hop distance (default True)
    - include_tests: also return callers in test files (default False)
    - include_evidence: per-hop `strategy` (lsp | language_rule | heuristic | unresolved)
      and `confidence`, so a guessed edge is distinguishable from a resolved one
      (default True). Test callers typically come back heuristic at low confidence

    Returns: graph trace response, or a graph-unavailable error if the graph
    backend is disabled or failed to start
    """
    client = await _acquire_client()
    if client is None:
        return _graph_unavailable()
    req = GraphTraceRequest(
        function_name=function_name,
        project=project,
        direction=direction,
        depth=depth,
        mode=mode,
        risk_labels=risk_labels,
        include_tests=include_tests,
        include_evidence=include_evidence,
    )
    return await asyncio.to_thread(graph_router.do_trace, client, req)


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
    client = await _acquire_client()
    if client is None:
        return _graph_unavailable()
    req = GraphArchitectureRequest(project=project)
    return await asyncio.to_thread(graph_router.do_architecture, client, req)


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
    client = await _acquire_client()
    if client is None:
        return _graph_unavailable()
    req = GraphImpactRequest(
        project=project, since=since, base_branch=base_branch, depth=depth
    )
    return await asyncio.to_thread(graph_router.do_impact, client, req)


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


@_log_tool_call
async def marm_concept_recall(
    query: str,
    session_name: Optional[str] = None,
    limit: int = 10,
    depth: int = 1,
    direction: Literal["outgoing", "incoming", "both"] = "both",
    project: Optional[str] = None,
    platform: Optional[str] = None,
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
    - platform: scope to this client/platform; omit to search across all (optional)

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
            platform=platform,
        )
        args = (
            req.query,
            req.session_name,
            req.limit,
            req.depth,
            req.direction,
            req.project,
        )
        if req.platform is None:
            return await asyncio.to_thread(_run_recall, *args)
        return await asyncio.to_thread(_run_recall, *args, req.platform)
    except Exception as e:
        # _run_recall failures can include SQLite paths/schema details --
        # log server-side (the HTTP endpoint's own try/except does this via
        # its "concepts.recall_error" log, but this STDIO wrapper calls
        # _run_recall directly and bypasses that), return a fixed message
        # to the client. Matches marm_concept_build's existing contract.
        _stdio_log.warning("concept recall failed: %s", e)
        return {"status": "error", "message": "Concept recall failed."}


def register_graph_tools(mcp: "FastMCP") -> None:
    """Explicit, order-independent tool registration -- called once from
    server_stdio.py after the 7 core tools are already registered, so
    tools/list order never depends on which module happens to import this
    one first."""
    mcp.add_tool(marm_graph_index)
    mcp.add_tool(marm_code_lookup)
    mcp.add_tool(marm_graph_trace)
    mcp.add_tool(marm_graph_architecture)
    mcp.add_tool(marm_graph_impact)
    mcp.add_tool(marm_concept_build)
    mcp.add_tool(marm_concept_recall)
