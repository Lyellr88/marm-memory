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
from marm_graph.core import tool_router as R
from marm_graph.core.models import (
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)
from pydantic import BaseModel, Field

from ..core.graph_supervisor import graph_supervisor
from ..core.concept_db import ConceptDB, get_concept_db_path

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
        if not graph_supervisor.is_available():
            job.update(status="error", phase="unavailable", error="Graph backend unavailable.")
            return
        job["phase"] = "indexing"
        result = R.do_index(
            graph_supervisor.get_client(),
            GraphIndexRequest(repo_path=repo_path, mode=mode, action="index"),
        )
        if result.get("status") == "error":
            job.update(status="error", phase="failed", error="Repository indexing failed.")
            return
        job.update(
            status="success",
            phase="complete",
            project=result.get("project"),
        )
    except Exception:
        if job is not None:
            job.update(status="error", phase="failed", error="Repository indexing failed.")
    finally:
        if job is not None:
            job["finished_at"] = _now_iso()
            job["_finished_timestamp"] = datetime.now(timezone.utc).timestamp()
        _project_job_lock.release()


def _cleanup_project_code_links(project: str) -> None:
    db_path = get_concept_db_path()
    if not os.path.exists(db_path):
        return
    concept_db = ConceptDB(db_path)
    with concept_db.get_connection() as conn:
        conn.execute("DELETE FROM entity_code_links WHERE project = ?", (project,))


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


# Console-only routes. They are intentionally not FastApiMCP operations.
@router.post("/internal/projects/list")
async def console_list_projects() -> dict:
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(
            R.do_index,
            graph_supervisor.get_client(),
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
        raise HTTPException(status_code=500, detail="Could not start index job.") from exc
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
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(
            R.do_index,
            graph_supervisor.get_client(),
            GraphIndexRequest(project=req.project, action="status"),
        )
    )


@router.post("/internal/projects/architecture")
async def console_project_architecture(req: ConsoleProjectRequest) -> dict:
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(
            R.do_architecture,
            graph_supervisor.get_client(),
            GraphArchitectureRequest(project=req.project),
        )
    )


@router.post("/internal/projects/search")
async def console_project_search(req: CodeLookupRequest) -> dict:
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(R.do_lookup, graph_supervisor.get_client(), req)
    )


@router.post("/internal/projects/trace")
async def console_project_trace(req: ConsoleTraceRequest) -> dict:
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(
            R.do_trace,
            graph_supervisor.get_client(),
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
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    return _console_graph_result(
        await asyncio.to_thread(R.do_impact, graph_supervisor.get_client(), req)
    )


@router.post("/internal/projects/delete")
async def console_delete_project(req: ConsoleDeleteProjectRequest) -> dict:
    if not req.confirm or req.name != req.project:
        raise HTTPException(status_code=422, detail="Typed project confirmation is required.")
    if not await asyncio.to_thread(graph_supervisor.is_available):
        return _UNAVAILABLE
    result = await asyncio.to_thread(
        graph_supervisor.get_client().call_tool,
        "delete_project",
        {"project": req.project},
    )
    result = _console_graph_result(result if isinstance(result, dict) else {"result": result})
    if result.get("status") != "error":
        try:
            await asyncio.to_thread(_cleanup_project_code_links, req.project)
        except Exception:
            result["code_link_cleanup"] = "failed"
    return result
