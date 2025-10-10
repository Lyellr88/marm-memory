"""WebSocket endpoints for MARM MCP Server - CLEAN IMPORT/EXPORT ARCHITECTURE."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Any
import json

from core.websocket_manager import websocket_manager as ws_manager
from middleware.websocket_rate_limiting import websocket_rate_limit_middleware

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
    """Main WebSocket endpoint for MCP protocol communication - CLEAN ROUTING ONLY"""

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
        except Exception as e:
            # Handle any other connection errors
            try:
                await ws_manager.disconnect(client_id)
            except:
                pass

    # Apply the rate limiting middleware
    await websocket_rate_limit_middleware(websocket, handle_websocket_logic)