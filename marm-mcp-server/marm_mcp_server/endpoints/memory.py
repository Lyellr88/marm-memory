"""Memory endpoints for MARM MCP Server."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.models import SmartRecallRequest
from ..core.memory import memory
from ..core.response_limiter import MCPResponseLimiter
from ..core.concept_db import ConceptDB, get_concept_db_path
from ..services.recall import _apply_detail_level
from ..services.graph_context import attach_graph_context, get_graph_context

logger = structlog.get_logger(__name__)


def track_endpoint_usage(
    endpoint: str, request: Request, extra_data: dict | None = None
) -> None:
    """Track MCP endpoint usage"""
    try:
        import sqlite3

        usage_db = "marm_usage_analytics.db"

        user_data = {
            "user_agent": request.headers.get("user-agent", "unknown"),
            "ip_address": request.client.host if request.client else "unknown",
            "endpoint": endpoint,
            **(extra_data or {}),
        }

        with sqlite3.connect(usage_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    endpoint TEXT,
                    user_agent TEXT,
                    ip_address TEXT,
                    session_id TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute(
                """
                INSERT INTO usage_events (timestamp, event_type, endpoint, user_agent, ip_address, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    datetime.now().isoformat(),
                    "endpoint_usage",
                    endpoint,
                    user_data.get("user_agent"),
                    user_data.get("ip_address"),
                    str(user_data),
                ),
            )
    except Exception:
        pass


router = APIRouter(prefix="", tags=["Memory"])


class ConsoleMemoryPayload(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    session_name: str = Field(min_length=1, max_length=255)
    context_type: str = Field(default="general", min_length=1, max_length=100)
    project: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=255)
    metadata: dict | None = None


class ConsoleDeletePayload(BaseModel):
    confirm: Literal["DELETE"]


class ConsoleBulkDeletePayload(BaseModel):
    memory_ids: list[str] = Field(min_length=1, max_length=100)
    confirm: Literal["DELETE"]


def _console_scope(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _cleanup_deleted_concepts(memory_ids: list[str]) -> dict:
    db_path = get_concept_db_path()
    if not Path(db_path).exists():
        return {"status": "skipped", "reason": "concept database not found"}
    try:
        return ConceptDB(db_path).cleanup_deleted_memory_provenance(memory_ids)
    except Exception as exc:
        logger.warning("memory.concept_cleanup_failed", error=str(exc))
        return {"status": "failed", "error": "Concept cleanup failed."}


async def _cleanup_deleted_concepts_async(memory_ids: list[str]) -> dict:
    return await asyncio.to_thread(_cleanup_deleted_concepts, memory_ids)


def _memory_conflict(exc: RuntimeError) -> HTTPException:
    logger.warning("memory.console_mutation_failed", error=str(exc))
    if str(exc) == "memory write queue is unavailable":
        detail = "memory write queue is unavailable"
    elif str(exc) == "write queue is shutting down":
        detail = "Memory write queue is shutting down."
    else:
        detail = "Memory mutation failed."
    return HTTPException(status_code=409, detail=detail)


@router.post("/internal/memories", status_code=201)
async def console_create_memory(payload: ConsoleMemoryPayload) -> dict:
    try:
        memory_id = await memory.console_create_memory(
            payload.content,
            payload.session_name,
            payload.context_type,
            payload.metadata,
            _console_scope(payload.project),
            _console_scope(payload.platform),
        )
    except RuntimeError as exc:
        raise _memory_conflict(exc) from exc
    return memory.console_memory_row(memory_id) or {"id": memory_id}


@router.put("/internal/memories/{memory_id}")
async def console_replace_memory(memory_id: str, payload: ConsoleMemoryPayload) -> dict:
    # Retract the old content's concepts before the replacement is written, not
    # after. The write queues the memory for reindexing, so cleaning up
    # afterwards can delete entities the indexing worker has already written for
    # the new content, and the queue row is settled by then with nothing left to
    # restore them. Same ordering as the promoted-doc resave path.
    #
    # Guarded on the memory existing, which is not true of that path: a replace
    # against a missing id is an ordinary 404, and cleaning first would strip a
    # live memory's provenance on the way to returning one.
    if memory.console_memory_row(memory_id) is not None:
        await _cleanup_deleted_concepts_async([memory_id])
    try:
        updated = await memory.console_replace_memory(
            memory_id,
            payload.content,
            payload.session_name,
            payload.context_type,
            payload.metadata,
            _console_scope(payload.project),
            _console_scope(payload.platform),
        )
    except RuntimeError as exc:
        raise _memory_conflict(exc) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory.console_memory_row(memory_id) or {"id": memory_id}


@router.delete("/internal/memories/{memory_id}")
async def console_delete_memory(memory_id: str, payload: ConsoleDeletePayload) -> dict:
    try:
        result = await memory.console_delete_memory(memory_id)
    except RuntimeError as exc:
        raise _memory_conflict(exc) from exc
    if not result["deleted_ids"]:
        raise HTTPException(status_code=404, detail="Memory not found")
    result["concept_cleanup"] = await _cleanup_deleted_concepts_async(
        result["deleted_ids"]
    )
    return result


@router.post("/internal/memories/bulk-delete")
async def console_bulk_delete_memories(payload: ConsoleBulkDeletePayload) -> dict:
    try:
        result = await memory.console_delete_memories(payload.memory_ids)
    except RuntimeError as exc:
        raise _memory_conflict(exc) from exc
    result["concept_cleanup"] = await _cleanup_deleted_concepts_async(
        result["deleted_ids"]
    )
    return result


def _inject_log_results(response: dict, log_results: list) -> None:
    test = {
        **response,
        "log_results": log_results,
        "log_results_count": len(log_results),
    }
    if (
        MCPResponseLimiter.estimate_response_size(test)
        <= MCPResponseLimiter.CONTENT_LIMIT
    ):
        response["log_results"] = log_results
        response["log_results_count"] = len(log_results)
    else:
        response["log_results"] = []
        response["log_results_count"] = 0
        response["_log_results_truncated"] = True


@router.post("/marm_smart_recall", operation_id="marm_smart_recall")
async def marm_smart_recall(request: SmartRecallRequest, http_request: Request) -> dict:
    """
    🧠 Intelligent memory recall based on semantic similarity

    Finds relevant memories using semantic similarity or text search.
    Returns the most relevant memories with similarity scores.
    """
    track_endpoint_usage(
        "marm_smart_recall",
        http_request,
        {
            "query_length": len(request.query),
            "session_name": request.session_name,
            "limit": request.limit,
            "search_all": request.search_all,
        },
    )

    try:
        search_session = None if request.search_all else request.session_name

        log_results = []
        if request.include_logs:
            with memory.get_connection() as conn:
                log_base = """
                    SELECT id, session_name, topic, summary, entry_date, project, platform
                    FROM log_entries
                    WHERE (topic LIKE ? OR summary LIKE ?)
                """
                log_params: list = [f"%{request.query}%", f"%{request.query}%"]
                if not request.search_all:
                    log_base += " AND session_name = ?"
                    log_params.append(request.session_name)
                if request.project is not None:
                    log_base += " AND project = ?"
                    log_params.append(request.project)
                if request.platform is not None:
                    log_base += " AND platform = ?"
                    log_params.append(request.platform)
                log_base += " ORDER BY entry_date DESC LIMIT ?"
                log_params.append(request.limit)
                log_results = [
                    {
                        "id": r[0],
                        "session_name": r[1],
                        "topic": r[2],
                        "summary": r[3],
                        "entry_date": r[4],
                        "project": r[5],
                        "platform": r[6],
                        "type": "log",
                    }
                    for r in conn.execute(log_base, log_params).fetchall()
                ]

        similar_memories, scan_meta = await memory.recall_similar(
            request.query,
            search_session,
            request.limit,
            include_scan_metadata=True,
            exact_mode=request.exact_mode,
            project=request.project,
            platform=request.platform,
        )
        graph_context = await asyncio.to_thread(
            get_graph_context,
            query=request.query,
            memory_ids=[item.get("id") for item in similar_memories],
            session_name=search_session,
            project=request.project,
            platform=request.platform,
            limit=request.limit,
        )

        if not similar_memories:
            if not request.search_all:
                system_memories = await memory.recall_similar(
                    request.query,
                    "marm_system",
                    request.limit,
                    exact_mode=request.exact_mode,
                    project=request.project,
                    platform=request.platform,
                )

                response = {
                    "status": "no_results",
                    "query": request.query,
                    "session_name": request.session_name,
                    "search_all": request.search_all,
                    "detail_level": request.detail,
                    "results": [],
                    **scan_meta,
                }

                if system_memories:
                    response["message"] = (
                        f"🤔 No memories found in session '{request.session_name}' for query: '{request.query}'. "
                        f"However, {len(system_memories)} relevant results were found in the system documentation. "
                        f"For future searches, try: marm_smart_recall('{request.query}', session_name='marm_system') "
                        f"or use search_all=True to search across all sessions."
                    )
                    response["suggestion"] = {
                        "try_session": "marm_system",
                        "try_search_all": True,
                        "reason": "System documentation found",
                        "results_count": len(system_memories),
                    }
                    response["system_results"] = [
                        {
                            **m,
                            "content": _apply_detail_level(
                                m["content"], request.detail
                            ),
                        }
                        for m in system_memories
                    ]
                else:
                    response["message"] = (
                        f"🤔 No memories found for query: '{request.query}'. "
                        f"Try broadening your query, using session_name='marm_system' for system documentation, "
                        f"or search_all=True to search across all sessions."
                    )

                if request.include_logs:
                    _inject_log_results(response, log_results)
                return attach_graph_context(response, graph_context)
            else:
                response = {
                    "status": "no_results",
                    "message": f"🤔 No memories found across all sessions for query: '{request.query}'. Try broadening your query.",
                    "query": request.query,
                    "session_name": request.session_name,
                    "search_all": request.search_all,
                    "detail_level": request.detail,
                    "results": [],
                    **scan_meta,
                }
                if request.include_logs:
                    _inject_log_results(response, log_results)
                return attach_graph_context(response, graph_context)

        base_response = {
            "status": "success",
            "message": f"🧠 Found {len(similar_memories)} relevant memories",
            "query": request.query,
            "session_name": request.session_name,
            "search_all": request.search_all,
            "detail_level": request.detail,
            **scan_meta,
        }

        memories_to_limit = (
            [
                {**m, "content": _apply_detail_level(m["content"], request.detail)}
                for m in similar_memories
            ]
            if request.detail < 3
            else similar_memories
        )
        limited_memories, was_truncated = MCPResponseLimiter.limit_memory_response(
            memories_to_limit, base_response
        )

        context_lines = []
        for mem in limited_memories:
            context_lines.append(f"[{mem['context_type'].upper()}] {mem['content']}")

        base_response["context_summary"] = "\n".join(context_lines)
        base_response["results"] = limited_memories

        final_response = MCPResponseLimiter.add_truncation_notice(
            base_response, was_truncated, len(similar_memories)
        )

        if request.include_logs:
            _inject_log_results(final_response, log_results)

        return attach_graph_context(final_response, graph_context)
    except Exception as e:
        print(f"Unexpected error in marm_smart_recall: {e}")
        return {"status": "error", "message": "Memory recall failed."}
