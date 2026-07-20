"""Smart recall logic for MARM MCP Server."""

import asyncio

from ..core.memory import memory
from ..core.response_limiter import MCPResponseLimiter
from .graph_context import attach_graph_context, get_graph_context

_limiter = MCPResponseLimiter()

_DETAIL_LIMITS: dict[int, int] = {1: 200, 2: 500}


def _apply_detail_level(content: str, detail: int) -> str:
    limit = _DETAIL_LIMITS.get(detail)
    if limit is None or len(content) <= limit:
        return content
    return content[:limit] + "…"


async def smart_recall(
    query: str,
    session_name: str = "default",
    limit: int = 5,
    search_all: bool = False,
    include_logs: bool = False,
    detail: int = 1,
    exact_mode: str = "auto",
    project: str = None,
    platform: str = None,
) -> dict:
    try:
        search_session = None if search_all else session_name

        log_results = []
        if include_logs:
            with memory.get_connection() as conn:
                log_base = """
                    SELECT id, session_name, topic, summary, entry_date, project, platform
                    FROM log_entries
                    WHERE (topic LIKE ? OR summary LIKE ?)
                """
                log_params: list = [f"%{query}%", f"%{query}%"]
                if not search_all:
                    log_base += " AND session_name = ?"
                    log_params.append(session_name)
                if project is not None:
                    log_base += " AND project = ?"
                    log_params.append(project)
                if platform is not None:
                    log_base += " AND platform = ?"
                    log_params.append(platform)
                log_base += " ORDER BY entry_date DESC LIMIT ?"
                log_params.append(limit)
                log_rows = conn.execute(log_base, log_params).fetchall()
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
                for r in log_rows
            ]

        similar_memories, scan_meta = await memory.recall_similar(
            query,
            session=search_session,
            limit=limit,
            include_scan_metadata=True,
            exact_mode=exact_mode,
            project=project,
            platform=platform,
        )
        graph_context = await asyncio.to_thread(
            get_graph_context,
            query=query,
            memory_ids=[item.get("id") for item in similar_memories],
            session_name=search_session,
            project=project,
            platform=platform,
            limit=limit,
        )

        if not similar_memories:
            response: dict = {
                "status": "no_results",
                "query": query,
                "session_name": session_name,
                "search_all": search_all,
                "detail_level": detail,
                "results": [],
                **scan_meta,
            }
            if not search_all:
                system_memories = await memory.recall_similar(
                    query,
                    session="marm_system",
                    limit=limit,
                    project=project,
                    platform=platform,
                    exact_mode=exact_mode,
                )
                if system_memories:
                    response["message"] = (
                        f"🤔 No memories found in session '{session_name}' for query: '{query}'. "
                        f"However, {len(system_memories)} relevant results were found in the system documentation. "
                        f"Consider using search_all=true to search across all sessions."
                    )
                    response["system_results"] = [
                        {**m, "content": _apply_detail_level(m["content"], detail)}
                        for m in system_memories
                    ]
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
            return attach_graph_context(response, graph_context)

        formatted_results = [
            {
                "id": mem.get("id"),
                "content": _apply_detail_level(mem.get("content", ""), detail),
                "session_name": mem.get("session_name"),
                "similarity": mem.get("similarity", 0.0),
                "timestamp": mem.get("timestamp"),
                "context_type": mem.get("context_type", "general"),
                "project": mem.get("project"),
                "platform": mem.get("platform"),
            }
            for mem in similar_memories
        ]

        response_metadata = {
            "status": "success",
            "query": query,
            "session_name": session_name,
            "search_all": search_all,
            "detail_level": detail,
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

        response_data = attach_graph_context(response_data, graph_context)

        return response_data

    except Exception as e:
        print(f"Unexpected error in smart_recall_response: {e}")
        return {"status": "error", "message": "Error during smart recall."}
