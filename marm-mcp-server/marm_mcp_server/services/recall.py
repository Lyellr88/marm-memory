"""Smart recall logic for MARM MCP Server."""

from ..core.memory import memory
from ..core.response_limiter import MCPResponseLimiter

_limiter = MCPResponseLimiter()


async def smart_recall(
    query: str,
    session_name: str = "default",
    limit: int = 5,
    search_all: bool = False,
    include_logs: bool = False,
) -> dict:
    try:
        search_session = None if search_all else session_name

        log_results = []
        if include_logs:
            with memory.get_connection() as conn:
                if search_all:
                    log_rows = conn.execute(
                        """
                        SELECT session_name, topic, summary, entry_date
                        FROM log_entries
                        WHERE topic LIKE ? OR summary LIKE ?
                        ORDER BY entry_date DESC
                        LIMIT ?
                        """,
                        (f"%{query}%", f"%{query}%", limit),
                    ).fetchall()
                else:
                    log_rows = conn.execute(
                        """
                        SELECT session_name, topic, summary, entry_date
                        FROM log_entries
                        WHERE (topic LIKE ? OR summary LIKE ?) AND session_name = ?
                        ORDER BY entry_date DESC
                        LIMIT ?
                        """,
                        (f"%{query}%", f"%{query}%", session_name, limit),
                    ).fetchall()
            log_results = [
                {
                    "session_name": r[0],
                    "topic": r[1],
                    "summary": r[2],
                    "entry_date": r[3],
                    "type": "log",
                }
                for r in log_rows
            ]

        similar_memories, scan_meta = await memory.recall_similar(
            query, session=search_session, limit=limit, include_scan_metadata=True
        )

        if not similar_memories:
            response: dict = {
                "status": "no_results",
                "query": query,
                "session_name": session_name,
                "search_all": search_all,
                "results": [],
                **scan_meta,
            }
            if not search_all:
                system_memories = await memory.recall_similar(
                    query, session="marm_system", limit=limit
                )
                if system_memories:
                    response["message"] = (
                        f"🤔 No memories found in session '{session_name}' for query: '{query}'. "
                        f"However, {len(system_memories)} relevant results were found in the system documentation. "
                        f"Consider using search_all=true to search across all sessions."
                    )
                    response["system_results"] = system_memories
                else:
                    response["message"] = f"No memories found for query: '{query}'"
            else:
                response["message"] = (
                    f"No memories found across all sessions for query: '{query}'"
                )
            if include_logs:
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
            return response

        formatted_results = [
            {
                "id": mem.get("id"),
                "content": mem.get("content"),
                "session_name": mem.get("session_name"),
                "similarity": mem.get("similarity", 0.0),
                "timestamp": mem.get("timestamp"),
                "context_type": mem.get("context_type", "general"),
            }
            for mem in similar_memories
        ]

        response_metadata = {
            "status": "success",
            "query": query,
            "session_name": session_name,
            "search_all": search_all,
            **scan_meta,
        }

        limited_results, was_truncated = _limiter.limit_memory_response(
            formatted_results, response_metadata
        )

        response_data = {
            **response_metadata,
            "results_count": len(limited_results),
            "results": limited_results,
        }

        if was_truncated:
            response_data = _limiter.add_truncation_notice(
                response_data, was_truncated, len(formatted_results)
            )

        if include_logs:
            test = {
                **response_data,
                "log_results": log_results,
                "log_results_count": len(log_results),
            }
            if (
                MCPResponseLimiter.estimate_response_size(test)
                <= MCPResponseLimiter.CONTENT_LIMIT
            ):
                response_data["log_results"] = log_results
                response_data["log_results_count"] = len(log_results)
            else:
                response_data["log_results"] = []
                response_data["log_results_count"] = 0
                response_data["_log_results_truncated"] = True

        return response_data

    except Exception as e:
        print(f"Unexpected error in smart_recall_response: {e}")
        return {"status": "error", "message": "Error during smart recall."}
