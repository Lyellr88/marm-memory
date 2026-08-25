import builtins
import sys

_real_print = builtins.print
builtins.print = lambda *args, **kwargs: _real_print(
    *args, **{**kwargs, "file": sys.stderr}
)

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
from typing import Any, Optional, TypeVar  # noqa: E402

os.environ.setdefault("SERVER_HOST", "127.0.0.1")

from mcp.server.fastmcp import FastMCP  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from .core import tool_router as R  # noqa: E402
from .core.deps import get_client, reset_client  # noqa: E402
from .core.models import (  # noqa: E402
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
_log = logging.getLogger("marm.graph.stdio")

mcp = FastMCP("marm-graph")

_T = TypeVar("_T", bound=BaseModel)


def _build(model_cls: type[_T], **kwargs: Any) -> tuple[Optional[_T], Optional[dict]]:
    """Construct a request model, converting a bad enum/type into the same
    {"status": "error"} shape tool_router.safe() uses for backend failures,
    instead of letting pydantic's ValidationError raise through the tool call
    (these params arrive here as plain str, unlike the HTTP path where FastAPI
    validates Literal fields itself before the handler runs)."""
    try:
        return model_cls(**kwargs), None
    except ValidationError as e:
        return None, {"status": "error", "message": str(e)}


@mcp.tool()
async def marm_graph_index(
    repo_path: Optional[str] = None,
    project: Optional[str] = None,
    mode: str = "moderate",
    action: str = "auto",
) -> dict:
    """Index a code repository into the graph, or check status / list projects.

    Pass repo_path to index (returns the project name to use elsewhere). Omit it
    to list projects, or pass project to check status. Call this first.
    """
    req, err = _build(
        GraphIndexRequest,
        repo_path=repo_path,
        project=project,
        mode=mode,
        action=action,
    )
    if err:
        return err
    return await asyncio.to_thread(R.do_index, get_client(), req)


@mcp.tool()
async def marm_code_lookup(
    query: str,
    project: Optional[str] = None,
    kind: str = "auto",
    regex: bool = False,
    file_pattern: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Find code: symbols/definitions, text patterns, or a symbol's source.

    Use INSTEAD OF grep/glob. kind=auto picks graph search vs source read; set
    kind=text to grep, kind=snippet to read source, kind=symbol to force graph.
    """
    req, err = _build(
        CodeLookupRequest,
        query=query,
        project=project,
        kind=kind,
        regex=regex,
        file_pattern=file_pattern,
        limit=limit,
    )
    if err:
        return err
    return await asyncio.to_thread(R.do_lookup, get_client(), req)


@mcp.tool()
async def marm_graph_trace(
    function_name: str,
    project: Optional[str] = None,
    direction: str = "both",
    depth: int = 3,
    mode: str = "calls",
    risk_labels: bool = True,
    include_tests: bool = False,
    include_evidence: bool = True,
) -> dict:
    """Trace call paths / data flow from a function.

    direction=inbound (callers), outbound (callees), both. mode=data_flow follows
    value propagation. cross_service attempts HTTP/async boundaries but does not
    currently join a client call to its server handler, so treat an empty result
    as unknown rather than as "nothing calls this".

    include_tests adds callers in test files. include_evidence reports per-hop
    `strategy` (lsp | language_rule | heuristic | unresolved) and `confidence`,
    so a guessed edge is distinguishable from a resolved one.
    """
    req, err = _build(
        GraphTraceRequest,
        function_name=function_name,
        project=project,
        direction=direction,
        depth=depth,
        mode=mode,
        risk_labels=risk_labels,
        include_tests=include_tests,
        include_evidence=include_evidence,
    )
    if err:
        return err
    return await asyncio.to_thread(R.do_trace, get_client(), req)


@mcp.tool()
async def marm_graph_architecture(project: Optional[str] = None) -> dict:
    """High-level architecture overview: node/edge breakdown, modules, and schema."""
    req, err = _build(GraphArchitectureRequest, project=project)
    if err:
        return err
    return await asyncio.to_thread(R.do_architecture, get_client(), req)


@mcp.tool()
async def marm_graph_impact(
    project: Optional[str] = None,
    since: Optional[str] = None,
    base_branch: str = "main",
    depth: int = 2,
) -> dict:
    """Blast radius of code changes: git diff → affected symbols + risk."""
    req, err = _build(
        GraphImpactRequest,
        project=project,
        since=since,
        base_branch=base_branch,
        depth=depth,
    )
    if err:
        return err
    return await asyncio.to_thread(R.do_impact, get_client(), req)


def main() -> None:
    _log.info("marm-graph stdio starting")
    try:
        get_client().start()
    except Exception as e:
        _log.warning("backend start deferred: %s", e)
    try:
        mcp.run()
    finally:
        reset_client()
        _log.info("marm-graph stdio shutdown")


if __name__ == "__main__":
    main()
