"""WebSocket endpoints for MARM MCP Server."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Any
import json
from datetime import datetime, timezone
from core.memory import memory
from core.events import events
from core.websocket_manager import websocket_manager as ws_manager
from middleware.websocket_rate_limiting import websocket_rate_limit_middleware
from core.response_limiter import MCPResponseLimiter
from utils.helpers import read_protocol_file

# Import ALL handlers for complete MCP coverage - CLEAN IMPORT/EXPORT ARCHITECTURE
from endpoints.websocket_handlers_complete import (
    handle_smart_recall, handle_contextual_log, handle_start, handle_refresh,
    handle_log_session, handle_log_entry, handle_log_show, handle_log_delete,
    handle_summary, handle_context_bridge, handle_notebook_add, handle_notebook_use,
    handle_notebook_show, handle_notebook_delete, handle_notebook_clear,
    handle_notebook_status, handle_current_context, handle_system_info, handle_reload_docs
)

router = APIRouter()

@router.websocket("/mcp/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for MCP protocol communication"""
    # Import and apply rate limiting middleware
    from middleware.websocket_rate_limiting import websocket_rate_limit_middleware
    
    # Define the actual WebSocket handling logic as call_next
    async def handle_websocket_logic(ws):
        client_id = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"
        
        await ws_manager.connect(ws, client_id)
        
        try:
            while True:
                data = await ws.receive_text()
                
                try:
                    # Parse the incoming message
                    message = json.loads(data)
                    message_type = message.get("method", "unknown")
                    
                    # Handle different message types - COMPLETE MCP PROTOCOL COVERAGE
                    # Memory Operations
                    if message_type == "smart_recall":
                        await handle_smart_recall(ws, client_id, message)
                    elif message_type == "contextual_log":
                        await handle_contextual_log(ws, client_id, message)

                    # Session Operations
                    elif message_type == "start":
                        await handle_start(ws, client_id, message)
                    elif message_type == "refresh":
                        await handle_refresh(ws, client_id, message)

                    # Logging Operations
                    elif message_type == "log_session":
                        await handle_log_session(ws, client_id, message)
                    elif message_type == "log_entry":
                        await handle_log_entry(ws, client_id, message)
                    elif message_type == "log_show":
                        await handle_log_show(ws, client_id, message)
                    elif message_type == "log_delete":
                        await handle_log_delete(ws, client_id, message)

                    # Reasoning Operations
                    elif message_type == "summary":
                        await handle_summary(ws, client_id, message)
                    elif message_type == "context_bridge":
                        await handle_context_bridge(ws, client_id, message)

                    # Notebook Operations
                    elif message_type == "notebook_add":
                        await handle_notebook_add(ws, client_id, message)
                    elif message_type == "notebook_use":
                        await handle_notebook_use(ws, client_id, message)
                    elif message_type == "notebook_show":
                        await handle_notebook_show(ws, client_id, message)
                    elif message_type == "notebook_delete":
                        await handle_notebook_delete(ws, client_id, message)
                    elif message_type == "notebook_clear":
                        await handle_notebook_clear(ws, client_id, message)
                    elif message_type == "notebook_status":
                        await handle_notebook_status(ws, client_id, message)

                    # System Operations
                    elif message_type == "current_context":
                        await handle_current_context(ws, client_id, message)
                    elif message_type == "system_info":
                        await handle_system_info(ws, client_id, message)
                    elif message_type == "reload_docs":
                        await handle_reload_docs(ws, client_id, message)

                    else:
                        # Proper MCP error for unknown methods (no more echo!)
                        response = {
                            "jsonrpc": "2.0",
                            "id": message.get("id"),
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {message_type}",
                                "data": {
                                    "available_methods": [
                                        "smart_recall", "contextual_log", "start", "refresh",
                                        "log_session", "log_entry", "log_show", "log_delete",
                                        "summary", "context_bridge", "notebook_add", "notebook_use",
                                        "notebook_show", "notebook_delete", "notebook_clear",
                                        "notebook_status", "current_context", "system_info", "reload_docs"
                                    ]
                                }
                            }
                        }
                        await ws_manager.send_personal_message(response, client_id)
                        
                except json.JSONDecodeError:
                    # Proper MCP error for invalid JSON
                    response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32700,
                            "message": "Parse error",
                            "data": {
                                "error": "Invalid JSON-RPC 2.0 message format",
                                "received": data[:100] + "..." if len(data) > 100 else data
                            }
                        }
                    }
                    await ws_manager.send_personal_message(response, client_id)
                    
        except WebSocketDisconnect:
            await ws_manager.disconnect(client_id)
    
    # Apply the rate limiting middleware
    await websocket_rate_limit_middleware(websocket, handle_websocket_logic)

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