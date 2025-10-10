"""WebSocket connection manager for MARM MCP Server."""

from typing import Dict, Set
from fastapi import WebSocket
import asyncio
import json
from config.settings import MAX_WEBSOCKET_CONNECTIONS

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_lock = asyncio.Lock()
        self.client_sessions: Dict[str, str] = {}
        self.client_metadata: Dict[str, Dict] = {}

    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        """Connect a new WebSocket client"""
        async with self.connection_lock:
            # Check connection limit
            if len(self.active_connections) >= MAX_WEBSOCKET_CONNECTIONS:
                return False
            
            await websocket.accept()
            self.active_connections[client_id] = websocket
            return True

    async def disconnect(self, client_id: str):
        """Disconnect a WebSocket client"""
        async with self.connection_lock:
            if client_id in self.active_connections:
                del self.active_connections[client_id]
            if client_id in self.client_sessions:
                del self.client_sessions[client_id]
            if client_id in self.client_metadata:
                del self.client_metadata[client_id]

    async def send_personal_message(self, message: dict, client_id: str):
        """Send a message to a specific client"""
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_text(json.dumps(message))
            except Exception as e:
                print(f"Error sending message to {client_id}: {e}")
                await self.disconnect(client_id)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients"""
        if not self.active_connections:
            return
            
        disconnected_clients = []
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                print(f"Error broadcasting to {client_id}: {e}")
                disconnected_clients.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected_clients:
            await self.disconnect(client_id)

    def set_client_session(self, client_id: str, session_name: str):
        """Set the session name for a client"""
        self.client_sessions[client_id] = session_name

    def get_client_session(self, client_id: str) -> str:
        """Get the session name for a client"""
        return self.client_sessions.get(client_id, "default")

    def set_client_metadata(self, client_id: str, metadata: dict):
        """Set metadata for a client"""
        self.client_metadata[client_id] = metadata

    def get_client_metadata(self, client_id: str) -> dict:
        """Get metadata for a client"""
        return self.client_metadata.get(client_id, {})

    def get_connection_count(self) -> int:
        """Get the current number of active connections"""
        return len(self.active_connections)

    def get_client_ids(self) -> Set[str]:
        """Get all connected client IDs"""
        return set(self.active_connections.keys())

    async def shutdown_all_connections(self):
        """Force close all WebSocket connections for server shutdown"""
        if not self.active_connections:
            return

        # Get a copy of client IDs to avoid modification during iteration
        client_ids = list(self.active_connections.keys())

        for client_id in client_ids:
            try:
                if client_id in self.active_connections:
                    websocket = self.active_connections[client_id]
                    await websocket.close(code=1001, reason="Server shutting down")
                    await self.disconnect(client_id)
            except Exception as e:
                # Force disconnect even if close fails
                await self.disconnect(client_id)

# Global WebSocket manager instance
websocket_manager = WebSocketManager()