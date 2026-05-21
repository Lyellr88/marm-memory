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

import functools
import logging
import os
import pathlib
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

# Docker images default to SERVER_HOST=0.0.0.0 for HTTP mode. STDIO mode never
# opens a network listener, so force loopback before shared settings import to
# prevent HTTP-only API key generation from polluting the MCP stream.
os.environ["SERVER_HOST"] = "127.0.0.1"

# File logger — stdout is reserved for JSON-RPC so we write diagnostics to disk.
_log_dir_env = os.environ.get("MARM_STDIO_LOG_DIR")
_log_dir = pathlib.Path(_log_dir_env) if _log_dir_env else pathlib.Path.home() / ".marm" / "logs"
_log_level_name = os.environ.get("MARM_STDIO_LOG_LEVEL", "INFO").upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
_debug = _log_level <= logging.DEBUG

_stdio_log = logging.getLogger("marm.stdio")
_stdio_log.setLevel(_log_level)
_stdio_log.propagate = False

_fmt = logging.Formatter("%(asctime)s [MARM] %(levelname)s %(message)s")

_sh = logging.StreamHandler(sys.stderr)
_sh.setFormatter(_fmt)
_stdio_log.addHandler(_sh)

try:
    _log_dir.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(_log_dir / "marm-stdio.log", encoding="utf-8")
    _fh.setFormatter(_fmt)
    _stdio_log.addHandler(_fh)
except Exception:
    pass  # log setup failure must not break the server

_protocol_delivered = False

def _log_tool_call(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        name = fn.__name__
        if _debug:
            safe = []
            for k, v in kwargs.items():
                if k == "session_name":
                    safe.append(f"session={v}")
                elif k == "query":
                    safe.append(f"query_len={len(v) if v else 0}")
                elif k in ("limit", "search_all"):
                    safe.append(f"{k}={v}")
            _stdio_log.debug("CALL %s %s", name, " ".join(safe))
        else:
            _stdio_log.info("CALL %s", name)

        global _protocol_delivered
        session_name = kwargs.get("session_name", "default")
        try:
            await ensure_marm_started(session_name)
        except Exception as e:
            _stdio_log.warning("session init failed: %s", e)

        try:
            result = await fn(*args, **kwargs)
        except Exception as e:
            _stdio_log.error("EXCEPTION %s %s: %s", name, type(e).__name__, e)
            raise
        if isinstance(result, dict):
            status = result.get("status", "ok")
            if status == "error":
                _stdio_log.error("FAIL %s: %s", name, result.get("message", ""))
            elif _debug:
                count = next(
                    (result[k] for k in ("results_count", "total_entries", "total_count")
                     if k in result),
                    None,
                )
                _stdio_log.debug(
                    "OK %s status=%s%s", name, status,
                    f" count={count}" if count is not None else "",
                )
            else:
                _stdio_log.info("OK %s", name)

            if not _protocol_delivered:
                try:
                    result["marm_protocol"] = await read_protocol_file()
                    _protocol_delivered = True
                except Exception as e:
                    _stdio_log.warning("protocol injection failed: %s", e)

        try:
            await maybe_auto_refresh()
        except Exception as e:
            _stdio_log.warning("auto-refresh failed: %s", e)

        return result
    return wrapper


from fastmcp import FastMCP

from marm_mcp_server.core.memory import memory
from marm_mcp_server.core.events import events
from marm_mcp_server.core.response_limiter import MCPResponseLimiter
from marm_mcp_server.services.documentation import (
    ensure_marm_started,
    maybe_auto_refresh,
)
from marm_mcp_server.utils.helpers import read_protocol_file
from marm_mcp_server.config.settings import (
    SERVER_VERSION,
    DEFAULT_DB_PATH,
    SEMANTIC_SEARCH_AVAILABLE,
)

mcp = FastMCP("MARM MCP Server")
response_limiter = MCPResponseLimiter()

# ============================================================================
# Session Tools
# ============================================================================

# ============================================================================
# Memory Tools
# ============================================================================

@mcp.tool()
@_log_tool_call
async def marm_smart_recall(
    query: str,
    session_name: str = "default",
    limit: int = 5,
    search_all: bool = False,
    include_logs: bool = False,
) -> dict:
    """
    🧠 Intelligent memory recall based on semantic similarity

    Finds relevant memories using semantic similarity or text search.
    Returns the most relevant memories with similarity scores.
    """
    try:
        search_session = None if search_all else session_name

        # Run log query up front so it's available in both no_results and success paths.
        # Scope to session_name unless search_all=True, matching memory search behaviour.
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
                {"session_name": r[0], "topic": r[1], "summary": r[2], "entry_date": r[3], "type": "log"}
                for r in log_rows
            ]

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
                if include_logs:
                    response["log_results"] = log_results
                    response["log_results_count"] = len(log_results)
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

        if include_logs:
            response_data["log_results"] = log_results
            response_data["log_results_count"] = len(log_results)

        return response_data

    except Exception as e:
        return {"status": "error", "message": f"Error during smart recall: {str(e)}"}


@mcp.tool()
@_log_tool_call
async def marm_context_log(
    content: str,
    session_name: str = "default",
    context_type: str = "general",
    metadata: Optional[dict] = None,
) -> dict:
    """
    📝 Log durable context with automatic categorization

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
            "message": f"✅ Context logged to session '{session_name}'",
            "memory_id": memory_id,
            "session_name": session_name,
            "context_type": context_type,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error during context log: {str(e)}"}


# ============================================================================
# Logging Tools
# Uses log_entries table — same schema as HTTP endpoints.
# ============================================================================

@mcp.tool()
@_log_tool_call
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

        memory.active_log_session = session_name
        await events.emit("session_created", {"session": session_name})

        return {
            "status": "success",
            "message": f"📂 Session '{session_name}' created/activated",
            "session_name": session_name,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error creating session: {str(e)}"}


@mcp.tool()
@_log_tool_call
async def marm_log_entry(
    entry: str,
    session_name: Optional[str] = None,
) -> dict:
    """
    📝 Add structured log entry for milestones or decisions

    Entry format: YYYY-MM-DD-topic-summary (date prefix optional).
    Omit session_name to use the active session set by marm_log_session.
    """
    try:
        formatted_entry = entry.strip()
        session = session_name or memory.active_log_session

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
                (entry_id, session, entry_date, topic, summary, formatted_entry),
            )
            conn.commit()

        await events.emit(
            "log_entry_created",
            {"entry_id": entry_id, "session": session, "content": formatted_entry},
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
@_log_tool_call
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
@_log_tool_call
async def marm_delete(
    type: str,
    target: str,
    session_name: Optional[str] = None,
) -> dict:
    """
    🗑️ Delete a log session, log entry, or notebook entry

    type="log" + session_name: delete specific entry by id or topic
    type="log" (no session_name): delete entire session and all its entries
    type="notebook": delete notebook entry by name
    """
    try:
        with memory.get_connection() as conn:
            if type == "log":
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
                    if memory.active_log_session == target:
                        memory.active_log_session = "main"
                conn.commit()
                return {
                    "status": "success",
                    "message": f"🗑️ Deleted {deleted} items",
                    "deleted_count": deleted,
                }
            elif type == "notebook":
                cursor = conn.execute("DELETE FROM notebook_entries WHERE name = ?", (target,))
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    memory.active_notebook_entries = [
                        entry for entry in memory.active_notebook_entries
                        if entry.get("name") != target
                    ]
                return {
                    "status": "success" if deleted > 0 else "not_found",
                    "message": f"🗑️ Deleted notebook entry '{target}'" if deleted > 0 else f"Entry '{target}' not found",
                    "deleted": deleted > 0,
                }
            else:
                return {"status": "error", "message": f"Invalid type '{type}'. Must be 'log' or 'notebook'."}
    except Exception as e:
        return {"status": "error", "message": f"Error deleting: {str(e)}"}


# ============================================================================
# Notebook Tools
# Uses notebook_entries table — same schema as HTTP endpoints.
# ============================================================================

@mcp.tool()
@_log_tool_call
async def marm_notebook(
    action: str,
    name: Optional[str] = None,
    data: Optional[str] = None,
    names: Optional[str] = None,
) -> dict:
    """
    📔 Unified notebook — add, use, show, status, or clear

    action="add": save or update an entry (name + data required)
    action="use": activate entries as instructions (names required, comma-separated)
    action="show": list all saved entries with previews
    action="status": show currently active entries
    action="clear": clear the active entry list
    """
    try:
        if action == "add":
            if name is None or data is None:
                return {"status": "error", "message": "name and data are required for action='add'"}
            embedding_bytes = None
            if memory.encoder:
                try:
                    embedding = memory.encoder.encode(data)
                    embedding_bytes = embedding.tobytes()
                except Exception:
                    pass
            with memory.get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at) VALUES (?, ?, ?, ?)",
                    (name, data, embedding_bytes, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
            await events.emit("notebook_entry_added", {"name": name, "data": data})
            return {"status": "success", "message": f"📓 Notebook entry '{name}' added", "name": name}

        elif action == "use":
            if names is None:
                return {"status": "error", "message": "names is required for action='use'"}
            name_list = [n.strip() for n in names.split(",")]
            activated_entries = []
            with memory.get_connection() as conn:
                for n in name_list:
                    cursor = conn.execute("SELECT name, data FROM notebook_entries WHERE name = ?", (n,))
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

        elif action == "show":
            with memory.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT name, data, created_at, updated_at FROM notebook_entries ORDER BY updated_at DESC"
                )
                entries = []
                for row in cursor.fetchall():
                    preview = row[1][:100] + "..." if len(row[1]) > 100 else row[1]
                    entries.append({"name": row[0], "preview": preview, "created_at": row[2], "updated_at": row[3]})
            return {"status": "success", "message": f"📚 Found {len(entries)} notebook entries", "entries": entries, "total_count": len(entries)}

        elif action == "status":
            active_names = [entry["name"] for entry in memory.active_notebook_entries]
            return {
                "status": "success",
                "message": f"📊 {len(active_names)} active notebook entries",
                "active_entries": active_names,
                "entries": memory.active_notebook_entries,
                "active_count": len(active_names),
            }

        elif action == "clear":
            memory.active_notebook_entries = []
            return {"status": "success", "message": "🧹 Active notebook entries cleared", "active_count": 0}

        else:
            return {"status": "error", "message": f"Unknown action '{action}'. Must be: add, use, show, status, clear"}

    except Exception as e:
        return {"status": "error", "message": f"Notebook operation failed: {str(e)}"}



# ============================================================================
# Workflow Tools
# ============================================================================

@mcp.tool()
@_log_tool_call
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


# ============================================================================
# Entrypoint
# ============================================================================

def main() -> None:
    _stdio_log.info(
        "startup version=%s db=%s semantic_search=%s",
        SERVER_VERSION, DEFAULT_DB_PATH, SEMANTIC_SEARCH_AVAILABLE,
    )
    try:
        mcp.run()
    finally:
        _stdio_log.info("shutdown")


if __name__ == "__main__":
    main()

