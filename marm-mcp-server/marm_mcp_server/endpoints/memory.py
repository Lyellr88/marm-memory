"""Memory endpoints for MARM MCP Server."""

from fastapi import APIRouter, Request
from datetime import datetime

from ..core.models import SmartRecallRequest
from ..core.memory import memory
from ..core.response_limiter import MCPResponseLimiter
from ..services.recall import _apply_detail_level


def track_endpoint_usage(endpoint: str, request: Request, extra_data: dict = None):
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
async def marm_smart_recall(request: SmartRecallRequest, http_request: Request):
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
                if request.search_all:
                    cursor = conn.execute(
                        """
                        SELECT session_name, topic, summary, entry_date
                        FROM log_entries
                        WHERE topic LIKE ? OR summary LIKE ?
                        ORDER BY entry_date DESC
                        LIMIT ?
                        """,
                        (f"%{request.query}%", f"%{request.query}%", request.limit),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT session_name, topic, summary, entry_date
                        FROM log_entries
                        WHERE (topic LIKE ? OR summary LIKE ?) AND session_name = ?
                        ORDER BY entry_date DESC
                        LIMIT ?
                        """,
                        (
                            f"%{request.query}%",
                            f"%{request.query}%",
                            request.session_name,
                            request.limit,
                        ),
                    )
                log_results = [
                    {
                        "session_name": r[0],
                        "topic": r[1],
                        "summary": r[2],
                        "entry_date": r[3],
                        "type": "log",
                    }
                    for r in cursor.fetchall()
                ]

        similar_memories, scan_meta = await memory.recall_similar(
            request.query, search_session, request.limit, include_scan_metadata=True
        )

        if not similar_memories:
            if not request.search_all:
                system_memories = await memory.recall_similar(
                    request.query, "marm_system", request.limit
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
                return response
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
                return response

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

        return final_response
    except Exception as e:
        print(f"Unexpected error in marm_smart_recall: {e}")
        return {"status": "error", "message": "Memory recall failed."}
