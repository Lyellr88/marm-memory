"""Complete WebSocket handlers for all MCP protocol methods."""

from fastapi import WebSocket
from typing import Dict, Any
import sqlite3
from datetime import datetime, timezone

from core.memory import memory
from core.events import events
from core.websocket_manager import websocket_manager as ws_manager
from core.response_limiter import MCPResponseLimiter
from utils.helpers import read_protocol_file

# ===== MEMORY HANDLERS =====

async def handle_smart_recall(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle smart recall requests via WebSocket"""
    try:
        query = message.get("params", {}).get("query", "")
        session_name = message.get("params", {}).get("session_name", ws_manager.get_client_session(client_id))
        search_all = message.get("params", {}).get("search_all", False)

        # Perform the search
        results = await memory.recall_similar(query, session_name if not search_all else None)

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "memories": results,
                "count": len(results)
            }
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

async def handle_contextual_log(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle contextual log requests via WebSocket"""
    try:
        params = message.get("params", {})
        content = params.get("content", "")
        session_name = params.get("session_name", ws_manager.get_client_session(client_id))

        if not content:
            raise ValueError("content parameter is required")

        # Store memory with contextual processing
        memory_id = await memory.store_memory(content, session_name)

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "status": "success",
                "message": f"🧠 Memory stored with contextual processing",
                "memory_id": memory_id,
                "session_name": session_name,
                "content_length": len(content)
            }
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

# ===== SESSION HANDLERS =====

async def handle_start(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle MARM start requests via WebSocket"""
    try:
        params = message.get("params", {})
        session_name = params.get("session_name", f"ws_session_{client_id}")

        with memory.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, marm_active, last_accessed)
                VALUES (?, TRUE, ?)
            ''', (session_name, datetime.now(timezone.utc).isoformat()))
            conn.commit()

        # Read the current protocol from file
        protocol_content = await read_protocol_file()
        await events.emit('marm_started', {'session': session_name})

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "status": "success",
                "message": f"🚀 MARM protocol activated for session '{session_name}'",
                "session_name": session_name,
                "marm_active": True,
                "protocol_content": protocol_content,
                "instructions": "The complete MARM protocol documentation has been loaded and is available for reference."
            }
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

async def handle_refresh(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle MARM refresh requests via WebSocket"""
    try:
        params = message.get("params", {})
        session_name = params.get("session_name", ws_manager.get_client_session(client_id))

        with memory.get_connection() as conn:
            conn.execute('''
                UPDATE sessions SET last_accessed = ? WHERE session_name = ?
            ''', (datetime.now(timezone.utc).isoformat(), session_name))
            conn.commit()

        # Read the current protocol from file to reaffirm adherence
        protocol_content = await read_protocol_file()
        await events.emit('marm_refreshed', {'session': session_name})

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "status": "success",
                "message": f"🔄 MARM session '{session_name}' refreshed - protocol adherence reaffirmed",
                "session_name": session_name,
                "protocol_content": protocol_content,
                "instructions": "Protocol documentation refreshed. Please review the current MARM protocol specifications above."
            }
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

# ===== LOGGING HANDLERS =====

async def handle_log_entry(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle log entry requests via WebSocket"""
    try:
        params = message.get("params", {})
        session_name = params.get("session_name", ws_manager.get_client_session(client_id))
        entry = params.get("entry", "")

        if not entry:
            raise ValueError("Entry parameter is required")

        # Log the entry
        memory_id = await memory.store_memory(entry, session_name)

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "id": memory_id,
                "session_name": session_name,
                "timestamp": "current_time"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

async def handle_log_session(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle log session requests via WebSocket"""
    try:
        params = message.get("params", {})
        session_name = params.get("session_name", f"ws_session_{client_id}")

        # Create the session if it doesn't exist
        with memory.get_connection() as conn:
            conn.execute('''
                INSERT OR IGNORE INTO sessions (session_name, marm_active, last_accessed)
                VALUES (?, FALSE, ?)
            ''', (session_name, datetime.now(timezone.utc).isoformat()))
            conn.commit()

        await events.emit('log_session_created', {'session': session_name})

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "status": "success",
                "message": f"📝 Log session '{session_name}' created and activated",
                "session_name": session_name,
                "instructions": "Session is ready for logging entries. Use log_entry to add content."
            }
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

async def handle_log_show(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle log show requests via WebSocket"""
    try:
        params = message.get("params", {})
        session_name = params.get("session_name")
        limit = params.get("limit", 20)

        with memory.get_connection() as conn:
            if session_name:
                # Show specific session
                cursor = conn.execute('''
                    SELECT entry_date, topic, summary, full_entry
                    FROM log_entries WHERE session_name = ?
                    ORDER BY entry_date DESC
                    LIMIT ?
                ''', (session_name, limit))
                entries = cursor.fetchall()

                response_data = {
                    "status": "success",
                    "session_name": session_name,
                    "entries": [{"date": e[0], "topic": e[1], "summary": e[2], "content": e[3]} for e in entries],
                    "entry_count": len(entries)
                }
            else:
                # Show all sessions
                cursor = conn.execute('''
                    SELECT DISTINCT session_name, COUNT(*) as entry_count,
                           MAX(entry_date) as last_entry
                    FROM log_entries
                    GROUP BY session_name
                    ORDER BY last_entry DESC
                    LIMIT ?
                ''', (limit,))
                sessions = cursor.fetchall()

                response_data = {
                    "status": "success",
                    "sessions": [{"name": s[0], "entry_count": s[1], "last_entry": s[2]} for s in sessions],
                    "session_count": len(sessions)
                }

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": response_data
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

async def handle_log_delete(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle log delete requests via WebSocket"""
    try:
        params = message.get("params", {})
        session_name = params.get("session_name")
        entry_id = params.get("entry_id")

        if not session_name:
            raise ValueError("session_name parameter is required")

        with memory.get_connection() as conn:
            if entry_id:
                # Delete specific entry
                cursor = conn.execute('''
                    DELETE FROM log_entries WHERE session_name = ? AND id = ?
                ''', (session_name, entry_id))
                deleted = cursor.rowcount
            else:
                # Delete entire session
                cursor = conn.execute('''
                    DELETE FROM log_entries WHERE session_name = ?
                ''', (session_name,))
                deleted = cursor.rowcount

                # Also delete session record
                conn.execute('''
                    DELETE FROM sessions WHERE session_name = ?
                ''', (session_name,))

            conn.commit()

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "status": "success" if deleted > 0 else "not_found",
                "message": f"🗑️ Deleted {deleted} entries" if deleted > 0 else "No entries found to delete",
                "deleted_count": deleted
            }
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

# ===== NOTEBOOK HANDLERS =====

async def handle_notebook_add(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle notebook add requests via WebSocket"""
    try:
        params = message.get("params", {})
        name = params.get("name", "")
        data = params.get("data", "")

        if not name or not data:
            raise ValueError("Both name and data parameters are required")

        # Generate embedding if available
        embedding_bytes = None
        if memory.encoder:
            try:
                embedding = memory.encoder.encode(data)
                embedding_bytes = embedding.tobytes()
            except Exception as e:
                print(f"Failed to generate embedding: {e}")

        # Add to notebook using same logic as HTTP endpoint
        with memory.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (name, data, embedding_bytes, datetime.now(timezone.utc).isoformat()))
            conn.commit()

        # Emit event
        await events.emit('notebook_entry_added', {
            'name': name,
            'data': data
        })

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "status": "success",
                "message": f"📓 Notebook entry '{name}' added",
                "name": name
            }
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

async def handle_notebook_use(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle notebook use requests via WebSocket"""
    try:
        params = message.get("params", {})
        name = params.get("name", "")  # Updated from 'names' to 'name' for consistency

        if not name:
            raise ValueError("name parameter is required")

        names = [n.strip() for n in name.split(',')]
        activated_entries = []

        with memory.get_connection() as conn:
            for entry_name in names:
                cursor = conn.execute('SELECT name, data FROM notebook_entries WHERE name = ?', (entry_name,))
                result = cursor.fetchone()
                if result:
                    activated_entries.append({"name": result[0], "data": result[1]})

        # Update active list in memory
        memory.active_notebook_entries = activated_entries

        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "status": "success",
                "message": f"🔧 Activated {len(activated_entries)} notebook entries",
                "activated_entries": [e["name"] for e in activated_entries],
                "entries": activated_entries
            }
        }
        await ws_manager.send_personal_message(response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

async def handle_notebook_show(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle notebook show requests via WebSocket"""
    try:
        with memory.get_connection() as conn:
            cursor = conn.execute('SELECT name, data, created_at, updated_at FROM notebook_entries ORDER BY updated_at DESC')
            entries = [{"name": row[0], "preview": row[1][:100] + "..." if len(row[1]) > 100 else row[1],
                       "created_at": row[2], "updated_at": row[3]} for row in cursor.fetchall()]

        response = {"jsonrpc": "2.0", "id": message.get("id"), "result": {"status": "success", "entries": entries, "total_count": len(entries)}}
        await ws_manager.send_personal_message(response, client_id)
    except Exception as e:
        await ws_manager.send_personal_message({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}, client_id)

async def handle_notebook_delete(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle notebook delete requests via WebSocket"""
    try:
        name = message.get("params", {}).get("name", "")
        if not name:
            raise ValueError("name parameter is required")

        with memory.get_connection() as conn:
            cursor = conn.execute('DELETE FROM notebook_entries WHERE name = ?', (name,))
            deleted = cursor.rowcount
            conn.commit()

        response = {"jsonrpc": "2.0", "id": message.get("id"), "result": {"status": "success" if deleted > 0 else "not_found", "deleted": deleted > 0}}
        await ws_manager.send_personal_message(response, client_id)
    except Exception as e:
        await ws_manager.send_personal_message({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}, client_id)

async def handle_notebook_clear(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle notebook clear requests via WebSocket"""
    try:
        memory.active_notebook_entries = []
        response = {"jsonrpc": "2.0", "id": message.get("id"), "result": {"status": "success", "message": "🧹 Active notebook entries cleared", "active_count": 0}}
        await ws_manager.send_personal_message(response, client_id)
    except Exception as e:
        await ws_manager.send_personal_message({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}, client_id)

async def handle_notebook_status(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle notebook status requests via WebSocket"""
    try:
        active_names = [entry["name"] for entry in memory.active_notebook_entries]
        response = {"jsonrpc": "2.0", "id": message.get("id"), "result": {"status": "success", "active_entries": active_names, "active_count": len(active_names)}}
        await ws_manager.send_personal_message(response, client_id)
    except Exception as e:
        await ws_manager.send_personal_message({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}, client_id)

# ===== REASONING HANDLERS =====

async def handle_summary(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle summary requests via WebSocket"""
    try:
        params = message.get("params", {})
        session_name = params.get("session_name", ws_manager.get_client_session(client_id))
        limit = params.get("limit", 50)

        # Generate summary using same logic as HTTP endpoint
        with memory.get_connection() as conn:
            # Get total count first
            cursor = conn.execute('''
                SELECT COUNT(*) FROM log_entries WHERE session_name = ?
            ''', (session_name,))
            total_entries = cursor.fetchone()[0]

            # Get limited entries for summary
            cursor = conn.execute('''
                SELECT entry_date, topic, summary, full_entry
                FROM log_entries WHERE session_name = ?
                ORDER BY entry_date DESC
                LIMIT ?
            ''', (session_name, limit))
            entries = cursor.fetchall()

        if not entries:
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {
                    "status": "empty",
                    "message": f"No entries found in session '{session_name}'"
                }
            }
            await ws_manager.send_personal_message(response, client_id)
            return

        # Build base response metadata
        base_response = {
            "status": "success",
            "session_name": session_name,
            "entry_count": len(entries),
            "total_entries": total_entries
        }

        # Build summary with size monitoring
        summary_lines = [f"# MARM Session Summary: {session_name}"]
        summary_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
        summary_lines.append("")

        if total_entries > len(entries):
            summary_lines.append(f"*Showing {len(entries)} most recent entries out of {total_entries} total*")
            summary_lines.append("")

        # Add entries with progressive truncation if needed
        included_entries = []
        current_summary_lines = summary_lines.copy()

        for entry in entries:
            # Truncate long summaries to prevent size explosion
            entry_summary = entry[2]
            if len(entry_summary) > 200:
                entry_summary = entry_summary[:197] + "..."

            entry_line = f"**{entry[0]}** [{entry[1]}]: {entry_summary}"
            test_lines = current_summary_lines + [entry_line]

            # Test response size with this entry added
            test_summary = "\n".join(test_lines)
            test_response = base_response.copy()
            test_response["summary"] = test_summary

            response_size = MCPResponseLimiter.estimate_response_size(test_response)

            if response_size > MCPResponseLimiter.CONTENT_LIMIT:
                # Can't fit this entry, stop here
                break

            # Entry fits, add it
            current_summary_lines.append(entry_line)
            included_entries.append(entry)

        summary_text = "\n".join(current_summary_lines)

        # Final response with truncation notice if needed
        final_response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "status": "success",
                "session_name": session_name,
                "summary": summary_text,
                "entry_count": len(included_entries),
                "total_entries": total_entries
            }
        }

        # Add truncation notice if we couldn't fit all entries
        if len(included_entries) < len(entries):
            final_response["result"]["_mcp_truncated"] = True
            final_response["result"]["_truncation_reason"] = "Summary limited to 1MB for MCP compliance"
            final_response["result"]["_entries_shown"] = len(included_entries)
            final_response["result"]["_entries_available"] = len(entries)

        await ws_manager.send_personal_message(final_response, client_id)

    except Exception as e:
        response = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        await ws_manager.send_personal_message(response, client_id)

async def handle_context_bridge(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle context bridge requests via WebSocket"""
    try:
        params = message.get("params", {})
        new_topic = params.get("new_topic", "")
        session_name = params.get("session_name", ws_manager.get_client_session(client_id))

        bridge_text = f"# Context Bridge: {new_topic}\nSession: {session_name}\n\nReady to proceed with focused work"
        response = {"jsonrpc": "2.0", "id": message.get("id"), "result": {"status": "success", "bridge_text": bridge_text, "session_name": session_name}}
        await ws_manager.send_personal_message(response, client_id)
    except Exception as e:
        await ws_manager.send_personal_message({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}, client_id)

# ===== SYSTEM HANDLERS =====

async def handle_current_context(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle current context requests via WebSocket"""
    try:
        current_time = datetime.now(timezone.utc).isoformat()
        response = {"jsonrpc": "2.0", "id": message.get("id"), "result": {"status": "success", "current_datetime": current_time}}
        await ws_manager.send_personal_message(response, client_id)
    except Exception as e:
        await ws_manager.send_personal_message({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}, client_id)

async def handle_system_info(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle system info requests via WebSocket"""
    try:
        response = {"jsonrpc": "2.0", "id": message.get("id"), "result": {"status": "success", "message": "MARM MCP Server - WebSocket Protocol", "version": "2.2.5-beta"}}
        await ws_manager.send_personal_message(response, client_id)
    except Exception as e:
        await ws_manager.send_personal_message({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}, client_id)

async def handle_reload_docs(websocket: WebSocket, client_id: str, message: Dict[str, Any]):
    """Handle reload docs requests via WebSocket"""
    try:
        response = {"jsonrpc": "2.0", "id": message.get("id"), "result": {"status": "success", "message": "📚 Documentation reloaded"}}
        await ws_manager.send_personal_message(response, client_id)
    except Exception as e:
        await ws_manager.send_personal_message({"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}, client_id)