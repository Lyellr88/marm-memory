"""The 5 marm-graph AI tools, registered directly on marm-mcp-server.

Same operation_ids and request models as marm-graph's own endpoints/graph_ai.py
(imported from marm_graph.core.models), so existing agent prompts/docs referencing
these tool names keep working unchanged. Each route checks graph_supervisor
availability (triggering lazy startup on first call) before delegating to
marm_graph's tool_router, matching marm_graph's own asyncio.to_thread pattern.
"""

import asyncio
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from marm_graph.core import code_graph_view
from marm_graph.core import tool_router as R
from marm_graph.core.cbm_client import CbmError, CbmToolError
from marm_graph.core.models import (
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)

from ..core import code_link_queue, code_project_bindings, runtime_flags
from ..core.concept_db import ConceptDB, get_concept_db_path
from ..core.graph_index_lock import GraphIndexBusy, gate_sync, run_exclusive
from ..core.graph_index_worker import (
    AUTO_ACTIONS,
    auto_action,
    graph_index_worker,
    index_repository,
)
from ..core.graph_supervisor import graph_supervisor

router = APIRouter(prefix="", tags=["Graph"])

_UNAVAILABLE = {"status": "error", "message": "graph backend unavailable"}
_project_jobs: dict[str, dict] = {}
_project_job_lock = threading.Lock()
_project_jobs_lock = threading.Lock()
_PROJECT_JOB_TTL_SECONDS = 3600


class ConsoleIndexRequest(BaseModel):
    repo_path: str = Field(..., min_length=1, max_length=4096)
    mode: Literal["full", "moderate", "fast"] = "moderate"


class ConsoleProjectRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)


class ConsoleMemoryBindingRequest(ConsoleProjectRequest):
    memory_project: str = Field(..., min_length=1, max_length=512)


class ConsoleGraphNeighborhoodRequest(ConsoleProjectRequest):
    node_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9._/\\@+()\[\] -]+$",
    )


class ConsoleTraceRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)
    symbol: str = Field(..., min_length=1, max_length=1024)
    direction: Literal["inbound", "outbound", "both"] = "both"
    mode: Literal["calls", "data_flow", "cross_service"] = "calls"
    depth: int = Field(3, ge=1, le=5)


class ConsoleDeleteProjectRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)
    name: str = Field(..., min_length=1, max_length=512)
    confirm: bool = False


class ConsoleAdrUpdateRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1, max_length=200000)


class ConsoleRuntimeTrace(BaseModel):
    caller: str = Field(..., min_length=1, max_length=2048)
    callee: str = Field(..., min_length=1, max_length=2048)
    count: int = Field(..., ge=1, le=1000000)


class ConsoleRuntimeTracesRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)
    traces: list[ConsoleRuntimeTrace] = Field(..., min_length=1, max_length=500)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prune_project_jobs() -> None:
    cutoff = datetime.now(timezone.utc).timestamp() - _PROJECT_JOB_TTL_SECONDS
    with _project_jobs_lock:
        for job_id, job in list(_project_jobs.items()):
            finished_at = job.get("_finished_timestamp")
            if finished_at is not None and finished_at < cutoff:
                _project_jobs.pop(job_id, None)


def _console_graph_result(result: dict) -> dict:
    if result.get("status") == "error":
        return {
            "status": "error",
            "error_code": "graph_request_failed",
            "message": "Graph operation failed.",
        }
    return result


async def _console_engine_call(
    tool: str, arguments: dict, *, mutates_store: bool = False
) -> dict:
    """Call an engine-only Console operation without leaking backend details."""
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return dict(_UNAVAILABLE)
    try:
        if mutates_store:
            result = await run_exclusive(
                f"console_{tool}", client.call_tool, tool, arguments
            )
        else:
            result = await asyncio.to_thread(client.call_tool, tool, arguments)
    except GraphIndexBusy as busy:
        return {
            "status": "error",
            "error_code": "index_in_progress",
            "message": str(busy),
        }
    except (CbmError, CbmToolError):
        return dict(_UNAVAILABLE)
    return _console_graph_result(
        result if isinstance(result, dict) else {"result": result}
    )


def _validated_repo_path(raw_path: str) -> str:
    if any(ord(char) < 32 for char in raw_path):
        raise HTTPException(status_code=422, detail="Repository path is invalid.")
    path = Path(raw_path).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise HTTPException(
            status_code=422,
            detail="Repository path must be an existing absolute directory.",
        )
    return str(path.resolve())


def _run_project_index(job_id: str, repo_path: str, mode: str) -> None:
    job: dict | None = None
    try:
        with _project_jobs_lock:
            job = _project_jobs.get(job_id)
        if job is None:
            return
        job.update(status="running", phase="starting", started_at=_now_iso())
        client = graph_supervisor.get_client()
        if client is None:
            job.update(
                status="error", phase="unavailable", error="Graph backend unavailable."
            )
            return
        job["phase"] = "indexing"
        # _project_job_lock only serializes this interpreter's jobs; the lease
        # is what keeps this off the same repo as the other transport's poller.
        try:
            with gate_sync("manual_index:console"):
                result = index_repository(
                    client,
                    GraphIndexRequest(repo_path=repo_path, mode=mode, action="index"),
                )
        except GraphIndexBusy as busy:
            job.update(status="error", phase="busy", error=str(busy))
            return
        if result.get("status") == "error":
            job.update(
                status="error", phase="failed", error="Repository indexing failed."
            )
            return
        job.update(
            status="success",
            phase="complete",
            project=result.get("project"),
        )
    except Exception:
        if job is not None:
            job.update(
                status="error", phase="failed", error="Repository indexing failed."
            )
    finally:
        if job is not None:
            job["finished_at"] = _now_iso()
            job["_finished_timestamp"] = datetime.now(timezone.utc).timestamp()
        _project_job_lock.release()


def _project_root_path(project: str) -> str | None:
    client = graph_supervisor.get_client()
    if client is None:
        return None
    result = R.do_index(client, GraphIndexRequest(action="list"))
    if result.get("status") == "error":
        return None
    for entry in result.get("projects", []):
        if (entry or {}).get("name") == project:
            return (entry or {}).get("root_path")
    return None


def _resolve_and_delete(project: str) -> tuple[str | None, str | None, dict]:
    """Resolve the root, delete the project, write its tombstone. Under the gate.

    The root has to be read before the delete, because afterwards the project is
    gone and its root path with it, and without the path there is nothing to
    suppress: the poller would re-index the root from its cached watch set and
    recreate what the user just deleted.

    The tombstone is written here rather than by the caller for the same reason
    the delete itself is gated. Writing it after the gate was released left a
    window where the other transport's poller could take the gate and start an
    opaque re-index of its cached root; a tombstone written after that call is
    already running cannot stop it, and the project comes back.
    """
    client = graph_supervisor.get_client()
    if client is None:
        return None, None, dict(_UNAVAILABLE)
    root_path = _project_root_path(project)
    try:
        result = client.call_tool("delete_project", {"project": project})
    except CbmError as exc:
        # call_tool directly, not through tool_router.safe, which is what turns a
        # CbmError into an error payload. Unmapped it leaves this route as a 500,
        # and a client closed under a concurrent teardown now raises rather than
        # respawning, so this is reachable where it previously was not.
        return None, None, {"status": "error", "message": f"delete failed: {exc}"}
    failed = isinstance(result, dict) and result.get("status") == "error"
    if failed:
        return root_path, None, result
    try:
        _cleanup_project_code_links(project)
    except Exception:
        if isinstance(result, dict):
            result["code_link_cleanup"] = "failed"
    if not root_path:
        return None, "unresolved_root", result
    try:
        runtime_flags.suppress_watch(root_path)
    except Exception:
        # Never raised past here. The project is already gone, so failing the
        # request would report a delete that did happen as a failure.
        return root_path, "failed", result
    return root_path, None, result


def _cleanup_project_code_links(project: str) -> None:
    code_link_queue.drop_project(project)
    code_project_bindings.drop_graph_project(project)
    db_path = get_concept_db_path()
    if os.path.exists(db_path):
        ConceptDB(db_path).cleanup_graph_project_links(project)


@router.post("/marm_graph_index", operation_id="marm_graph_index")
async def marm_graph_index(req: GraphIndexRequest) -> dict:
    """Index a code repository into the graph, or check status / list known projects.

    Pass `repo_path` to index a repo (returns the project name to use in every
    other tool). Omit it to list indexed projects, or pass `project` to check
    index status. Call this first — all other graph tools need an indexed project.
    """
    # Ahead of the availability gate below, which both refuses when the engine
    # is down and starts the engine as a side effect. Turning auto-index off
    # must work in either state.
    if req.action in AUTO_ACTIONS:
        return await asyncio.to_thread(auto_action, req.action)
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    if req.action == "index" or (req.action == "auto" and req.repo_path):
        try:
            # index_repository, not R.do_index: the tombstone and the path-limit
            # marker are settled inside the gate, where they cannot race the
            # other transport's poller writing the opposite answer.
            return await run_exclusive(
                "manual_index:http",
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
    return await asyncio.to_thread(R.do_index, client, req)


@router.post("/marm_code_lookup", operation_id="marm_code_lookup")
async def marm_code_lookup(req: CodeLookupRequest) -> dict:
    """Find code: symbols/definitions, text patterns, or a symbol's source.

    Use INSTEAD OF grep/glob. `kind=auto` picks: a qualified_name reads source;
    otherwise it searches the graph by name/keyword. Set `kind=text` to grep code,
    `kind=snippet` to read a symbol's source, `kind=symbol` to force graph search.
    """
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return await asyncio.to_thread(R.do_lookup, client, req)


@router.post("/marm_graph_trace", operation_id="marm_graph_trace")
async def marm_graph_trace(req: GraphTraceRequest) -> dict:
    """Trace call paths / data flow through the graph from a function.

    `direction=inbound` finds callers, `outbound` finds callees, `both` for all.
    `mode=data_flow` follows value propagation. `cross_service` attempts HTTP/async
    boundaries but does not currently join a client call to its server handler, so
    treat an empty result as unknown rather than as "nothing calls this".
    Use for impact analysis, dependency tracing, "who calls this".
    """
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return await asyncio.to_thread(R.do_trace, client, req)


@router.post("/marm_graph_architecture", operation_id="marm_graph_architecture")
async def marm_graph_architecture(req: GraphArchitectureRequest) -> dict:
    """High-level architecture overview: node/edge breakdown, modules, and schema.

    One-shot orientation for a project — the de-facto module clusters, package
    structure, and the graph schema (node labels + properties) folded in.
    """
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return await asyncio.to_thread(R.do_architecture, client, req)


@router.post("/marm_graph_impact", operation_id="marm_graph_impact")
async def marm_graph_impact(req: GraphImpactRequest) -> dict:
    """Blast radius of code changes: git diff → affected symbols + risk.

    Pass `since` (a git ref/date) or a `base_branch` to compare against. Returns
    which symbols a change touches and how far the impact propagates.
    """
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return await asyncio.to_thread(R.do_impact, client, req)


# Console-only routes. They are intentionally not FastApiMCP operations.
@router.post("/internal/projects/list")
async def console_list_projects() -> dict:
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(
            R.do_index,
            client,
            GraphIndexRequest(action="list"),
        )
    )


@router.post("/internal/projects/index", status_code=202)
async def console_index_project(req: ConsoleIndexRequest) -> dict:
    repo_path = _validated_repo_path(req.repo_path)
    if not _project_job_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="An index job is already running.")
    _prune_project_jobs()
    job_id = str(uuid.uuid4())
    with _project_jobs_lock:
        _project_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "project": None,
            "phase": "queued",
            "error": None,
            "created_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
        }
    worker = threading.Thread(
        target=_run_project_index, args=(job_id, repo_path, req.mode), daemon=True
    )
    try:
        worker.start()
    except Exception as exc:
        with _project_jobs_lock:
            _project_jobs.pop(job_id, None)
        _project_job_lock.release()
        raise HTTPException(
            status_code=500, detail="Could not start index job."
        ) from exc
    return {"job_id": job_id}


@router.get("/internal/projects/jobs/{job_id}")
async def console_project_job(job_id: str) -> dict:
    _prune_project_jobs()
    with _project_jobs_lock:
        job = _project_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Index job not found.")
    return {key: value for key, value in job.items() if not key.startswith("_")}


@router.post("/internal/projects/status")
async def console_project_status(req: ConsoleProjectRequest) -> dict:
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(
            R.do_index,
            client,
            GraphIndexRequest(project=req.project, action="status"),
        )
    )


@router.post("/internal/projects/coverage")
async def console_project_coverage(req: ConsoleProjectRequest) -> dict:
    """Return a bounded root-scope coverage report for the Console.

    Coverage is intentionally best-effort and only signals recorded gaps; the
    browser labels it accordingly rather than treating it as proof of completeness.
    """
    return await _console_engine_call(
        "check_index_coverage",
        {"project": req.project, "scopes": ["."], "scope_limit": 30},
    )


@router.post("/internal/projects/adr")
async def console_project_adr(req: ConsoleProjectRequest) -> dict:
    return await _console_engine_call(
        "manage_adr", {"project": req.project, "mode": "get"}
    )


@router.post("/internal/projects/adr/update")
async def console_project_adr_update(req: ConsoleAdrUpdateRequest) -> dict:
    return await _console_engine_call(
        "manage_adr",
        {"project": req.project, "mode": "update", "content": req.content},
        mutates_store=True,
    )


@router.post("/internal/projects/runtime-traces")
async def console_project_runtime_traces(req: ConsoleRuntimeTracesRequest) -> dict:
    return await _console_engine_call(
        "ingest_traces",
        {
            "project": req.project,
            "traces": [trace.model_dump() for trace in req.traces],
        },
        mutates_store=True,
    )


@router.post("/internal/projects/architecture")
async def console_project_architecture(req: ConsoleProjectRequest) -> dict:
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(
            R.do_architecture,
            client,
            GraphArchitectureRequest(project=req.project),
        )
    )


@router.post("/internal/projects/code-units")
async def console_project_code_units(req: ConsoleProjectRequest) -> dict:
    """Console-only. Deliberately not routed through tool_router or a tool.

    The limit stays server-side: no caller chooses it, so nothing from the
    browser reaches the query layer at all.
    """
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        # Deliberately not _UNAVAILABLE. That shape is `{"status": "error"}`,
        # which the Console adapter turns into a 503, failing the query and
        # leaving the table blank rather than saying the graph is unavailable.
        return code_graph_view.unavailable("graph_unavailable")
    return await asyncio.to_thread(code_graph_view.code_units, client, req.project)


@router.post("/internal/projects/graph")
async def console_project_graph(req: ConsoleProjectRequest) -> dict:
    """Return the Console's bounded file/import graph snapshot.

    This stays outside the MCP tool surface. The view owns fixed engine queries,
    so callers select a project but never submit graph query text.
    """
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return code_graph_view.graph_unavailable("graph_unavailable")
    return await asyncio.to_thread(code_graph_view.code_graph, client, req.project)


@router.post("/internal/projects/graph/neighborhood")
async def console_project_graph_neighborhood(
    req: ConsoleGraphNeighborhoodRequest,
) -> dict:
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return {
            "state": "unavailable",
            "reason": "graph_unavailable",
            "nodes": [],
            "edges": [],
        }
    return await asyncio.to_thread(
        code_graph_view.code_graph_neighborhood, client, req.project, req.node_id
    )


def _memory_linking_status(project: str, root_path: str | None) -> dict:
    try:
        binding = code_project_bindings.get_by_graph_project(project)
        queue = code_link_queue.status(project)
    except Exception:
        return {
            "state": "unbound",
            "binding": None,
            "candidates": [],
            "refresh": None,
            "linked_entities": 0,
        }
    linked_entities = 0
    db_path = get_concept_db_path()
    if os.path.exists(db_path):
        try:
            linked_entities = ConceptDB(db_path).graph_project_link_count(project)
        except Exception:
            linked_entities = 0
    if binding is None:
        try:
            candidates = code_project_bindings.matching_memory_project_scopes(
                project, root_path
            )
        except Exception:
            candidates = []
        return {
            "state": "ambiguous" if len(candidates) > 1 else "unbound",
            "binding": None,
            "candidates": candidates,
            "refresh": queue,
            "linked_entities": linked_entities,
        }
    return {
        "state": "bound",
        "binding": binding.as_dict(),
        "candidates": [],
        "refresh": queue,
        "linked_entities": linked_entities,
    }


@router.post("/internal/projects/memory-linking")
async def console_project_memory_linking(req: ConsoleProjectRequest) -> dict:
    root_path = await asyncio.to_thread(_project_root_path, req.project)
    return await asyncio.to_thread(_memory_linking_status, req.project, root_path)


@router.post("/internal/projects/memory-links")
async def console_project_memory_links(req: ConsoleProjectRequest) -> dict:
    db_path = get_concept_db_path()
    if not os.path.exists(db_path):
        return {"links": []}
    try:
        links = await asyncio.to_thread(
            ConceptDB(db_path).code_links_for_graph_project, req.project
        )
    except Exception:
        links = []
    return {"links": links}


@router.post("/internal/projects/memory-linking/confirm")
async def console_confirm_project_memory_linking(
    req: ConsoleMemoryBindingRequest,
) -> dict:
    root_path = await asyncio.to_thread(_project_root_path, req.project)
    if not root_path:
        raise HTTPException(status_code=404, detail="Indexed project not found.")
    try:
        binding = await asyncio.to_thread(
            code_project_bindings.set_user_binding,
            req.project,
            req.memory_project,
            root_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await asyncio.to_thread(
        code_link_queue.enqueue_refresh,
        binding.graph_project,
        binding.memory_project,
        binding.root_path,
    )
    return await asyncio.to_thread(_memory_linking_status, req.project, root_path)


@router.post("/internal/projects/search")
async def console_project_search(req: CodeLookupRequest) -> dict:
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return _console_graph_result(await asyncio.to_thread(R.do_lookup, client, req))


@router.post("/internal/projects/trace")
async def console_project_trace(req: ConsoleTraceRequest) -> dict:
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(
            R.do_trace,
            client,
            GraphTraceRequest(
                function_name=req.symbol,
                project=req.project,
                direction=req.direction,
                mode=req.mode,
                depth=req.depth,
            ),
        )
    )


@router.post("/internal/projects/impact")
async def console_project_impact(req: GraphImpactRequest) -> dict:
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    return _console_graph_result(await asyncio.to_thread(R.do_impact, client, req))


@router.post("/internal/projects/delete")
async def console_delete_project(req: ConsoleDeleteProjectRequest) -> dict:
    if not req.confirm or req.name != req.project:
        raise HTTPException(
            status_code=422, detail="Typed project confirmation is required."
        )
    client = await asyncio.to_thread(graph_supervisor.get_client)
    if client is None:
        return _UNAVAILABLE
    # Under the same gate as indexing. A delete that lands while a poller is
    # inside index_repository on the same project is silently undone: that index
    # finishes afterwards and writes the project back, so the user sees a deleted
    # project reappear while the suppression stops it ever updating again.
    #
    # Root resolution is inside the gate too. It is a 265ms engine call, so doing
    # it first would spend it only to discard the answer when the gate refuses.
    try:
        root_path, suppression_issue, result = await run_exclusive(
            f"delete_project:{req.project}", _resolve_and_delete, req.project
        )
    except GraphIndexBusy as busy:
        return {
            "status": "error",
            "error_code": "index_in_progress",
            "message": str(busy),
        }
    result = _console_graph_result(
        result if isinstance(result, dict) else {"result": result}
    )
    if result.get("status") != "error":
        if root_path:
            # The tombstone is already written, under the gate. This only drops
            # the local watch entry ahead of its next refresh.
            graph_index_worker.drop_watch(root_path)
        if suppression_issue:
            # Reported rather than swallowed: with no tombstone the other
            # transport's poller can re-index this root from its cached watch
            # set, and the symptom is a deleted project reappearing minutes later.
            result["watch_suppression"] = suppression_issue
    return result
