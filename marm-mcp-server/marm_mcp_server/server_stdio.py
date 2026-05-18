"""
MARM MCP Server - STDIO Transport
Memory Accurate Response Mode for Model Context Protocol

Runs via FastMCP over standard input/output. No port, no API key, no HTTP listener.
Intended for local single-client use (e.g. Docker STDIO, direct CLI invocation).

Usage:
  python -m marm_mcp_server.server_stdio
  docker run -i --rm -v ~/.marm:/home/marm/.marm lyellr88/marm-mcp-server:latest python -m marm_mcp_server.server_stdio
"""

# Redirect print() to stderr before any imports that might trigger model loading.
# STDIO MCP protocol reserves stdout exclusively for JSON-RPC messages — any
# stray print() would corrupt the stream and break client parsing.
import builtins
import sys

_real_print = builtins.print
builtins.print = lambda *args, **kwargs: _real_print(
    *args, **{**kwargs, "file": sys.stderr}
)

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

# Docker images default to SERVER_HOST=0.0.0.0 for HTTP mode. STDIO mode never
# opens a network listener, so force loopback before shared settings import to
# prevent HTTP-only API key generation from polluting the MCP stream.
os.environ["SERVER_HOST"] = "127.0.0.1"

from fastmcp import FastMCP

from marm_mcp_server.core.memory import memory
from marm_mcp_server.core.events import events
from marm_mcp_server.core.response_limiter import MCPResponseLimiter
from marm_mcp_server.utils.helpers import read_protocol_file
from marm_mcp_server.config.settings import (
    SERVER_VERSION,
    DEFAULT_DB_PATH,
    SEMANTIC_SEARCH_AVAILABLE,
    SCHEDULER_AVAILABLE,
)

mcp = FastMCP("MARM MCP Server")
response_limiter = MCPResponseLimiter()

# ============================================================================
# Session Tools
# ============================================================================

@mcp.tool()
async def marm_start(session_name: str) -> dict:
    """
    🚀 Activates MARM memory and accuracy layers

    Equivalent to /start marm command
    """
    try:
        with memory.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions (session_name, marm_active, last_accessed)
                VALUES (?, TRUE, ?)
                """,
                (session_name, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

        protocol_content = await read_protocol_file()
        await events.emit("marm_started", {"session": session_name})

        return {
            "status": "success",
            "message": f"🚀 MARM protocol activated for session '{session_name}'",
            "session_name": session_name,
            "marm_active": True,
            "protocol_content": protocol_content,
            "instructions": "The complete MARM protocol documentation has been loaded and is available for reference.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Error during MARM start: {str(e)}"}


@mcp.tool()
async def marm_refresh(session_name: str) -> dict:
    """
    🔄 Refreshes active session state and reaffirms protocol adherence

    Equivalent to /refresh marm command
    """
    try:
        with memory.get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET last_accessed = ? WHERE session_name = ?",
                (datetime.now(timezone.utc).isoformat(), session_name),
            )
            conn.commit()

        protocol_content = await read_protocol_file()
        await events.emit("marm_refreshed", {"session": session_name})

        return {
            "status": "success",
            "message": f"🔄 MARM session '{session_name}' refreshed - protocol adherence reaffirmed",
            "session_name": session_name,
            "protocol_content": protocol_content,
            "instructions": "Protocol documentation refreshed. Please review the current MARM protocol specifications above.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Error during MARM refresh: {str(e)}"}


# ============================================================================
# Memory Tools
# ============================================================================

@mcp.tool()
async def marm_smart_recall(
    query: str,
    session_name: str = "default",
    limit: int = 5,
    search_all: bool = False,
) -> dict:
    """
    🧠 Intelligent memory recall based on semantic similarity

    Finds relevant memories using semantic similarity or text search.
    Returns the most relevant memories with similarity scores.
    """
    try:
        search_session = None if search_all else session_name
        similar_memories = await memory.recall_similar(query, session=search_session, limit=limit)

        if not similar_memories:
            if not search_all:
                system_memories = await memory.recall_similar(
                    query, session="marm_system", limit=limit
                )
                response: dict = {
                    "status": "no_results",
                    "query": query,
                    "session_name": session_name,
                    "search_all": search_all,
                    "results": [],
                }
                if system_memories:
                    response["message"] = (
                        f"🤔 No memories found in session '{session_name}' for query: '{query}'. "
                        f"However, {len(system_memories)} relevant results were found in the system documentation. "
                        f"Consider using search_all=true to search across all sessions."
                    )
                    response["system_results"] = system_memories
                else:
                    response["message"] = f"No memories found for query: '{query}'"
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
        }

        limited_results, was_truncated = response_limiter.limit_memory_response(
            formatted_results, response_metadata
        )

        response_data = {
            **response_metadata,
            "results_count": len(limited_results),
            "results": limited_results,
        }

        if was_truncated:
            response_data = response_limiter.add_truncation_notice(
                response_data, was_truncated, len(formatted_results)
            )

        return response_data

    except Exception as e:
        return {"status": "error", "message": f"Error during smart recall: {str(e)}"}


@mcp.tool()
async def marm_contextual_log(
    content: str,
    session_name: str = "default",
    context_type: str = "general",
    metadata: Optional[dict] = None,
) -> dict:
    """
    📝 Log contextual information with automatic categorization

    Saves information to memory with automatic context type detection.
    """
    try:
        memory_id = await memory.store_memory(
            content=content,
            session=session_name,
            context_type=context_type,
            metadata=metadata or {},
        )

        await events.emit(
            "memory_logged",
            {"session": session_name, "memory_id": memory_id, "context_type": context_type},
        )

        return {
            "status": "success",
            "message": f"✅ Contextual information logged to session '{session_name}'",
            "memory_id": memory_id,
            "session_name": session_name,
            "context_type": context_type,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error during contextual log: {str(e)}"}


# ============================================================================
# Logging Tools
# Uses log_entries table — same schema as HTTP endpoints.
# ============================================================================

@mcp.tool()
async def marm_log_session(session_name: str) -> dict:
    """
    📂 Create or switch to named session container
    """
    try:
        with memory.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_name, last_accessed) VALUES (?, ?)",
                (session_name, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

        await events.emit("session_created", {"session": session_name})

        return {
            "status": "success",
            "message": f"📂 Session '{session_name}' created/activated",
            "session_name": session_name,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error creating session: {str(e)}"}


@mcp.tool()
async def marm_log_entry(
    entry: str,
    session_name: str = "main",
) -> dict:
    """
    📝 Add structured log entry for milestones or decisions

    Entry format: YYYY-MM-DD-topic-summary (date prefix optional)
    """
    try:
        formatted_entry = entry.strip()

        entry_pattern = r"^(\d{4}-\d{2}-\d{2})-(.*?)-(.*?)$"
        match = re.match(entry_pattern, formatted_entry)

        if match:
            entry_date, topic, summary = match.groups()
        else:
            entry_date = None
            topic = "general"
            summary = formatted_entry

        entry_id = str(uuid.uuid4())

        with memory.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (entry_id, session_name, entry_date, topic, summary, formatted_entry),
            )
            conn.commit()

        await events.emit(
            "log_entry_created",
            {"entry_id": entry_id, "session": session_name, "content": formatted_entry},
        )

        return {
            "status": "success",
            "message": f"📝 Log entry added: {formatted_entry}",
            "entry_id": entry_id,
            "formatted_entry": formatted_entry,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error creating log entry: {str(e)}"}


@mcp.tool()
async def marm_log_show(
    session_name: Optional[str] = None,
) -> dict:
    """
    📋 Display all entries and sessions logged
    """
    try:
        with memory.get_connection() as conn:
            if session_name:
                cursor = conn.execute(
                    """
                    SELECT id, entry_date, topic, summary, full_entry
                    FROM log_entries WHERE session_name = ?
                    ORDER BY entry_date DESC
                    """,
                    (session_name,),
                )
                entries = [
                    {"id": r[0], "entry_date": r[1], "topic": r[2], "summary": r[3], "full_entry": r[4]}
                    for r in cursor.fetchall()
                ]
                return {
                    "status": "success",
                    "session_name": session_name,
                    "entries": entries,
                    "total_entries": len(entries),
                }
            else:
                cursor = conn.execute(
                    "SELECT session_name, COUNT(*) FROM log_entries GROUP BY session_name"
                )
                sessions = [{"session_name": r[0], "entry_count": r[1]} for r in cursor.fetchall()]
                return {
                    "status": "success",
                    "sessions": sessions,
                    "total_sessions": len(sessions),
                }
    except Exception as e:
        return {"status": "error", "message": f"Error retrieving log entries: {str(e)}"}


@mcp.tool()
async def marm_log_delete(
    target: str,
    session_name: Optional[str] = None,
) -> dict:
    """
    🗑️ Delete a session or specific log entry

    If session_name is provided, deletes the entry matching target within that session.
    If session_name is omitted, target is treated as a session name and the whole session is deleted.
    """
    try:
        with memory.get_connection() as conn:
            if session_name:
                cursor = conn.execute(
                    "DELETE FROM log_entries WHERE session_name = ? AND (id = ? OR topic = ?)",
                    (session_name, target, target),
                )
                deleted = cursor.rowcount
            else:
                conn.execute("DELETE FROM sessions WHERE session_name = ?", (target,))
                cursor = conn.execute(
                    "DELETE FROM log_entries WHERE session_name = ?", (target,)
                )
                deleted = cursor.rowcount
            conn.commit()

        return {
            "status": "success",
            "message": f"🗑️ Deleted {deleted} items",
            "deleted_count": deleted,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error deleting: {str(e)}"}


# ============================================================================
# Notebook Tools
# Uses notebook_entries table — same schema as HTTP endpoints.
# ============================================================================

@mcp.tool()
async def marm_notebook_add(
    name: str,
    data: str,
) -> dict:
    """
    📔 Add a new notebook entry
    """
    try:
        embedding_bytes = None
        if memory.encoder:
            try:
                embedding = memory.encoder.encode(data)
                embedding_bytes = embedding.tobytes()
            except Exception:
                pass

        with memory.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (name, data, embedding_bytes, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

        await events.emit("notebook_entry_added", {"name": name, "data": data})

        return {
            "status": "success",
            "message": f"📓 Notebook entry '{name}' added",
            "name": name,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error adding notebook entry: {str(e)}"}


@mcp.tool()
async def marm_notebook_use(names: str) -> dict:
    """
    🔧 Activate notebook entries as instructions

    names: comma-separated list of notebook entry names
    """
    try:
        name_list = [n.strip() for n in names.split(",")]
        activated_entries = []

        with memory.get_connection() as conn:
            for name in name_list:
                cursor = conn.execute(
                    "SELECT name, data FROM notebook_entries WHERE name = ?", (name,)
                )
                result = cursor.fetchone()
                if result:
                    activated_entries.append({"name": result[0], "data": result[1]})

        memory.active_notebook_entries = activated_entries

        return {
            "status": "success",
            "message": f"🔧 Activated {len(activated_entries)} notebook entries",
            "activated_entries": [e["name"] for e in activated_entries],
            "entries": activated_entries,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error activating notebook entries: {str(e)}"}


@mcp.tool()
async def marm_notebook_show() -> dict:
    """
    📚 Display all saved notebook keys and summaries
    """
    try:
        with memory.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT name, data, created_at, updated_at
                FROM notebook_entries
                ORDER BY updated_at DESC
                """
            )
            entries = []
            for row in cursor.fetchall():
                preview = row[1][:100] + "..." if len(row[1]) > 100 else row[1]
                entries.append({
                    "name": row[0],
                    "preview": preview,
                    "created_at": row[2],
                    "updated_at": row[3],
                })

        return {
            "status": "success",
            "message": f"📚 Found {len(entries)} notebook entries",
            "entries": entries,
            "total_count": len(entries),
        }
    except Exception as e:
        return {"status": "error", "message": f"Error showing notebook: {str(e)}"}


@mcp.tool()
async def marm_notebook_status() -> dict:
    """
    📊 Show the current active notebook list
    """
    try:
        active_names = [entry["name"] for entry in memory.active_notebook_entries]

        return {
            "status": "success",
            "message": f"📊 {len(active_names)} active notebook entries",
            "active_entries": active_names,
            "entries": memory.active_notebook_entries,
            "active_count": len(active_names),
        }
    except Exception as e:
        return {"status": "error", "message": f"Error checking notebook status: {str(e)}"}


@mcp.tool()
async def marm_notebook_clear() -> dict:
    """
    🧹 Clear the active notebook list
    """
    try:
        memory.active_notebook_entries = []
        return {
            "status": "success",
            "message": "🧹 Active notebook entries cleared",
            "active_count": 0,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error clearing notebook: {str(e)}"}


@mcp.tool()
async def marm_notebook_delete(name: str) -> dict:
    """
    🗑️ Delete a specific notebook entry by name
    """
    try:
        with memory.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM notebook_entries WHERE name = ?", (name,)
            )
            deleted = cursor.rowcount
            conn.commit()

        return {
            "status": "success" if deleted > 0 else "not_found",
            "message": f"🗑️ Deleted notebook entry '{name}'" if deleted > 0 else f"Entry '{name}' not found",
            "deleted": deleted > 0,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error deleting notebook entry: {str(e)}"}


# ============================================================================
# Workflow Tools
# ============================================================================

@mcp.tool()
async def marm_summary(
    session_name: str,
    limit: int = 50,
) -> dict:
    """
    📊 Generate paste-ready context block for new chats

    Reads log_entries for the session and returns a formatted markdown summary.
    Equivalent to /summary: [session name] command
    """
    try:
        with memory.get_connection() as conn:
            total_entries = conn.execute(
                "SELECT COUNT(*) FROM log_entries WHERE session_name = ?", (session_name,)
            ).fetchone()[0]

            entries = conn.execute(
                """
                SELECT entry_date, topic, summary, full_entry
                FROM log_entries WHERE session_name = ?
                ORDER BY entry_date DESC
                LIMIT ?
                """,
                (session_name, limit),
            ).fetchall()

        if not entries:
            return {"status": "empty", "message": f"No entries found in session '{session_name}'"}

        base_response = {
            "status": "success",
            "session_name": session_name,
            "entry_count": 0,
            "total_entries": total_entries,
        }

        summary_lines = [f"# MARM Session Summary: {session_name}"]
        summary_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
        summary_lines.append("")

        if total_entries > len(entries):
            summary_lines.append(
                f"*Showing {len(entries)} most recent entries out of {total_entries} total*"
            )
            summary_lines.append("")

        included_entries = []
        current_lines = summary_lines.copy()

        for entry in entries:
            entry_summary = entry[2]
            if len(entry_summary) > 200:
                entry_summary = entry_summary[:197] + "..."

            entry_line = f"**{entry[0]}** [{entry[1]}]: {entry_summary}"
            test_lines = current_lines + [entry_line]
            test_response = base_response.copy()
            test_response["summary"] = "\n".join(test_lines)

            if MCPResponseLimiter.estimate_response_size(test_response) > MCPResponseLimiter.CONTENT_LIMIT:
                break

            current_lines.append(entry_line)
            included_entries.append(entry)

        final_response = {
            "status": "success",
            "session_name": session_name,
            "summary": "\n".join(current_lines),
            "entry_count": len(included_entries),
            "total_entries": total_entries,
        }

        if len(included_entries) < len(entries):
            final_response["_mcp_truncated"] = True
            final_response["_truncation_reason"] = "Summary limited to 1MB for MCP compliance"
            final_response["_entries_shown"] = len(included_entries)
            final_response["_entries_available"] = len(entries)

        return final_response

    except Exception as e:
        return {"status": "error", "message": f"Error generating summary: {str(e)}"}


@mcp.tool()
async def marm_context_bridge(
    new_topic: str,
    session_name: str = "default",
) -> dict:
    """
    🌉 Intelligent context bridging for smooth workflow transitions

    Searches memories and log_entries for content related to new_topic,
    then returns a formatted bridge_text block. Equivalent to /context_bridge: [new topic]
    """
    try:
        related_content = []

        if memory.encoder:
            related_memories = await memory.recall_similar(
                query=new_topic, session=None, limit=8
            )

            with memory.get_connection() as conn:
                log_matches = conn.execute(
                    """
                    SELECT session_name, topic, summary, full_entry
                    FROM log_entries
                    WHERE topic LIKE ? OR summary LIKE ?
                    ORDER BY entry_date DESC
                    LIMIT 3
                    """,
                    (f"%{new_topic}%", f"%{new_topic}%"),
                ).fetchall()

            for mem_item in related_memories[:5]:
                related_content.append({
                    "type": "memory",
                    "session": mem_item["session_name"],
                    "content": mem_item["content"],
                    "similarity": mem_item["similarity"],
                    "context_type": mem_item["context_type"],
                })

            for log_item in log_matches:
                related_content.append({
                    "type": "log",
                    "session": log_item[0],
                    "topic": log_item[1],
                    "summary": log_item[2],
                    "similarity": 0.7,
                })
        else:
            with memory.get_connection() as conn:
                log_matches = conn.execute(
                    """
                    SELECT session_name, topic, summary, full_entry
                    FROM log_entries
                    WHERE topic LIKE ? OR summary LIKE ?
                    ORDER BY entry_date DESC
                    LIMIT 5
                    """,
                    (f"%{new_topic}%", f"%{new_topic}%"),
                ).fetchall()

            for log_item in log_matches:
                related_content.append({
                    "type": "log",
                    "session": log_item[0],
                    "topic": log_item[1],
                    "summary": log_item[2],
                    "similarity": 0.7,
                })

        base_response = {
            "status": "success",
            "new_topic": new_topic,
            "session_name": session_name,
        }

        limited_content, was_truncated = MCPResponseLimiter.limit_context_bridge_response(
            related_content, base_response
        )

        bridge_lines = [f"# Context Bridge: {new_topic}", f"Session: {session_name}", ""]

        if limited_content:
            bridge_lines.append("## Related Context:")
            sorted_content = sorted(
                limited_content, key=lambda x: x.get("similarity", 0), reverse=True
            )

            for item in sorted_content:
                similarity_pct = int(item.get("similarity", 0.7) * 100)
                session_badge = f"[{item['session']}]"

                if item.get("type") == "memory":
                    context_badge = f"[{item['context_type'].upper()}]"
                    content_preview = (
                        item["content"][:100] + "..."
                        if len(item["content"]) > 100
                        else item["content"]
                    )
                    truncated = " [TRUNCATED]" if item.get("_truncated", False) else ""
                    bridge_lines.append(
                        f"- {session_badge} {context_badge} ({similarity_pct}%): {content_preview}{truncated}"
                    )
                else:
                    bridge_lines.append(
                        f"- {session_badge} [LOG] ({similarity_pct}%): {item['topic']} - {item['summary']}"
                    )

            bridge_lines.append("")

            if was_truncated:
                bridge_lines.append(
                    f"*Note: Results limited for size compliance. {len(related_content)} total matches found, "
                    f"showing {len(limited_content)}.*"
                )
                bridge_lines.append("")

        if limited_content:
            bridge_lines.append("## Recommended Approach:")
            context_types = [
                item.get("context_type", "general")
                for item in limited_content
                if item.get("type") == "memory"
            ]
            if "code" in context_types:
                bridge_lines.append("- Review related code patterns and implementations above")
                bridge_lines.append("- Consider lessons learned from similar technical work")
            elif "project" in context_types:
                bridge_lines.append("- Build on successful project patterns identified above")
                bridge_lines.append("- Apply lessons learned from previous project phases")
            else:
                bridge_lines.append("- Leverage insights from related work shown above")
                bridge_lines.append("- Build on established patterns and approaches")
        else:
            bridge_lines.append("## Starting Fresh:")
            bridge_lines.append("- No directly related context found - starting with clean slate")
            bridge_lines.append("- Consider documenting key decisions as you progress")

        bridge_lines.extend(["", "---", "*Ready to proceed with focused work*"])

        final_response = {
            "status": "success",
            "new_topic": new_topic,
            "session_name": session_name,
            "bridge_text": "\n".join(bridge_lines),
            "related_count": len(limited_content),
            "total_available": len(related_content),
        }

        if was_truncated:
            final_response["_mcp_truncated"] = True
            final_response["_truncation_reason"] = "Content limited to 1MB for MCP compliance"

        return final_response

    except Exception as e:
        return {"status": "error", "message": f"Error bridging context: {str(e)}"}


# ============================================================================
# System Tools
# ============================================================================

@mcp.tool()
async def marm_system_info() -> dict:
    """
    ℹ️ Comprehensive system information, health status, and loaded docs
    """
    import psutil

    try:
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024

        db_size = 0.0
        if os.path.exists(DEFAULT_DB_PATH):
            db_size = os.path.getsize(DEFAULT_DB_PATH) / 1024 / 1024

        with memory.get_connection() as conn:
            memory_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

        return {
            "status": "success",
            "version": SERVER_VERSION,
            "transport": "stdio",
            "system": {
                "memory_usage_mb": round(memory_mb, 2),
                "database_size_mb": round(db_size, 2),
                "database_path": DEFAULT_DB_PATH,
            },
            "features": {
                "semantic_search": SEMANTIC_SEARCH_AVAILABLE,
                "scheduler": SCHEDULER_AVAILABLE,
            },
            "statistics": {
                "total_memories": memory_count,
                "total_sessions": session_count,
            },
        }

    except Exception as e:
        return {"status": "error", "message": f"Error getting system info: {str(e)}"}


@mcp.tool()
async def marm_reload_docs() -> dict:
    """
    🔄 Reload documentation into memory system
    """
    try:
        protocol_content = await read_protocol_file()

        await memory.store_memory(
            content=protocol_content,
            session="marm_system",
            context_type="documentation",
            metadata={"source": "protocol_file", "reloaded": True},
        )

        return {
            "status": "success",
            "message": "✅ Documentation reloaded into memory system",
            "protocol_length": len(protocol_content),
        }

    except Exception as e:
        return {"status": "error", "message": f"Error reloading docs: {str(e)}"}


# ============================================================================
# Entrypoint
# ============================================================================

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
