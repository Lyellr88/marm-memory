#!/usr/bin/env python3
"""
MARM MCP Server - Memory Accurate Response Mode for Claude Desktop

This MCP server provides MARM's session management, notebook, and memory tools
for use with Claude Desktop and other MCP-compatible clients.

Core Features:
- Session management with persistent memory
- User notebook for storing key information  
- Log entries with structured timestamps
- Session summaries for context continuity
- Protocol activation and management

Author: MARM Systems
License: MIT
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import argparse

try:
    from fastmcp import FastMCP
except ImportError:
    print("Error: fastmcp is not installed. Run: pip install fastmcp>=0.4.0", file=sys.stderr)
    sys.exit(1)

# MCP Server Configuration
SERVER_NAME = "marm-memory-server"
SERVER_VERSION = "2.0.2"

# MARM Protocol Version
PROTOCOL_VERSION = "2.0.2"

# Storage paths
DATA_DIR = Path.home() / ".marm-mcp"
SESSIONS_FILE = DATA_DIR / "sessions.json"
NOTEBOOKS_FILE = DATA_DIR / "notebooks.json"
CONFIG_FILE = DATA_DIR / "config.json"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

class MARMStorage:
    """Handles persistent storage for MARM data"""
    
    def __init__(self):
        self.sessions = self._load_json(SESSIONS_FILE, {})
        self.notebooks = self._load_json(NOTEBOOKS_FILE, {})
        self.config = self._load_json(CONFIG_FILE, {
            "current_session": None,
            "active_protocol": False,
            "default_session": "main"
        })
    
    def _load_json(self, file_path: Path, default: Any) -> Any:
        """Load JSON from file or return default"""
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load {file_path}: {e}", file=sys.stderr)
        return default
    
    def _save_json(self, file_path: Path, data: Any) -> bool:
        """Save data to JSON file"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error: Could not save {file_path}: {e}", file=sys.stderr)
            return False
    
    def save_sessions(self) -> bool:
        """Save sessions to disk"""
        return self._save_json(SESSIONS_FILE, self.sessions)
    
    def save_notebooks(self) -> bool:
        """Save notebooks to disk"""
        return self._save_json(NOTEBOOKS_FILE, self.notebooks)
    
    def save_config(self) -> bool:
        """Save config to disk"""
        return self._save_json(CONFIG_FILE, self.config)
    
    def get_current_session_id(self) -> str:
        """Get current session ID"""
        return self.config.get("current_session", self.config.get("default_session", "main"))
    
    def set_current_session_id(self, session_id: str):
        """Set current session ID"""
        self.config["current_session"] = session_id
        self.save_config()

# Global storage instance
storage = MARMStorage()

# Initialize FastMCP server
mcp = FastMCP(SERVER_NAME)

@mcp.tool()
def marm_start(session_name: str = "main") -> str:
    """
    Activate MARM protocol for the specified session.
    
    Args:
        session_name: Name of the session to activate (default: "main")
    
    Returns:
        Status message confirming MARM activation
    """
    storage.set_current_session_id(session_name)
    storage.config["active_protocol"] = True
    storage.save_config()
    
    # Initialize session if it doesn't exist
    if session_name not in storage.sessions:
        storage.sessions[session_name] = {
            "id": session_name,
            "created": datetime.now().isoformat(),
            "logs": [],
            "context": "",
            "active_notebook_entries": [],
            "protocol_version": PROTOCOL_VERSION
        }
        storage.save_sessions()
    
    return f"✅ MARM Protocol v{PROTOCOL_VERSION} activated for session: {session_name}\n\nMemory Accurate Response Mode is now active. All conversation context will be tracked and maintained for accurate, transparent responses.\n\nAvailable tools:\n• marm_log_entry - Add structured log entries\n• marm_notebook_add - Store key information  \n• marm_session_summary - Generate session summaries\n• marm_show_context - View current session context"

@mcp.tool()
def marm_log_entry(entry: str, session_name: Optional[str] = None) -> str:
    """
    Add a structured log entry to the current session.
    
    Args:
        entry: Log entry in format [YYYY-MM-DD-topic-summary] or free text
        session_name: Session to log to (uses current session if not specified)
    
    Returns:
        Confirmation message
    """
    session_id = session_name or storage.get_current_session_id()
    
    # Ensure session exists
    if session_id not in storage.sessions:
        storage.sessions[session_id] = {
            "id": session_id,
            "created": datetime.now().isoformat(),
            "logs": [],
            "context": "",
            "active_notebook_entries": [],
            "protocol_version": PROTOCOL_VERSION
        }
    
    # Add timestamp if not present
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "entry": entry.strip(),
        "type": "log"
    }
    
    storage.sessions[session_id]["logs"].append(log_entry)
    storage.save_sessions()
    
    return f"📝 Log entry added to session '{session_id}':\n{entry}\n\nTotal entries: {len(storage.sessions[session_id]['logs'])}"

@mcp.tool()
def marm_notebook_add(name: str, data: str, session_name: Optional[str] = None) -> str:
    """
    Add an entry to the user's knowledge notebook.
    
    Args:
        name: Unique name/key for the notebook entry
        data: Content to store
        session_name: Session context (uses current session if not specified)
    
    Returns:
        Confirmation message
    """
    session_id = session_name or storage.get_current_session_id()
    
    if session_id not in storage.notebooks:
        storage.notebooks[session_id] = {}
    
    # Validate entry size (max 2048 chars)
    if len(data) > 2048:
        return f"❌ Entry too large. Maximum size is 2048 characters, got {len(data)}"
    
    # Check total notebook entries (max 30)
    if len(storage.notebooks[session_id]) >= 30 and name not in storage.notebooks[session_id]:
        return f"❌ Notebook full. Maximum 30 entries allowed. Current: {len(storage.notebooks[session_id])}"
    
    storage.notebooks[session_id][name] = {
        "data": data,
        "created": datetime.now().isoformat(),
        "updated": datetime.now().isoformat()
    }
    
    storage.save_notebooks()
    
    return f"📚 Notebook entry '{name}' added to session '{session_id}'\n\nContent: {data[:100]}{'...' if len(data) > 100 else ''}\n\nTotal notebook entries: {len(storage.notebooks[session_id])}"

@mcp.tool()
def marm_notebook_show(session_name: Optional[str] = None) -> str:
    """
    Display all notebook entries for the session.
    
    Args:
        session_name: Session to show (uses current session if not specified)
    
    Returns:
        List of all notebook entries
    """
    session_id = session_name or storage.get_current_session_id()
    
    if session_id not in storage.notebooks or not storage.notebooks[session_id]:
        return f"📚 No notebook entries found for session '{session_id}'"
    
    entries = storage.notebooks[session_id]
    result = f"📚 **Notebook entries for session '{session_id}'** ({len(entries)} entries):\n\n"
    
    for name, entry in entries.items():
        result += f"**{name}**\n"
        result += f"Content: {entry['data']}\n"
        result += f"Created: {entry['created']}\n\n"
    
    return result

@mcp.tool()
def marm_notebook_use(names: str, session_name: Optional[str] = None) -> str:
    """
    Activate notebook entries as active instructions for the session.
    
    Args:
        names: Comma-separated list of notebook entry names to activate
        session_name: Session context (uses current session if not specified)
    
    Returns:
        Confirmation and active entries list
    """
    session_id = session_name or storage.get_current_session_id()
    
    if session_id not in storage.sessions:
        return f"❌ Session '{session_id}' not found. Use marm_start first."
    
    if session_id not in storage.notebooks:
        return f"❌ No notebook entries found for session '{session_id}'"
    
    # Parse names
    entry_names = [name.strip() for name in names.split(',')]
    valid_entries = []
    missing_entries = []
    
    for name in entry_names:
        if name in storage.notebooks[session_id]:
            valid_entries.append(name)
        else:
            missing_entries.append(name)
    
    if not valid_entries:
        return f"❌ No valid entries found. Available: {list(storage.notebooks[session_id].keys())}"
    
    # Update active notebook entries
    storage.sessions[session_id]["active_notebook_entries"] = valid_entries
    storage.save_sessions()
    
    result = f"✅ **Active notebook entries for session '{session_id}':**\n\n"
    for name in valid_entries:
        data = storage.notebooks[session_id][name]["data"]
        result += f"• **{name}**: {data}\n"
    
    if missing_entries:
        result += f"\n⚠️ Not found: {missing_entries}"
    
    return result

@mcp.tool()
def marm_session_summary(session_name: Optional[str] = None) -> str:
    """
    Generate a structured summary of the session for context transfer.
    
    Args:
        session_name: Session to summarize (uses current session if not specified)
    
    Returns:
        Formatted session summary for copy/paste to new sessions
    """
    session_id = session_name or storage.get_current_session_id()
    
    if session_id not in storage.sessions:
        return f"❌ Session '{session_id}' not found"
    
    session = storage.sessions[session_id]
    
    summary = f"# MARM Session Summary: {session_id}\n\n"
    summary += f"**Protocol Version:** {session.get('protocol_version', PROTOCOL_VERSION)}\n"
    summary += f"**Created:** {session.get('created', 'Unknown')}\n"
    summary += f"**Log Entries:** {len(session.get('logs', []))}\n\n"
    
    # Add log entries
    logs = session.get('logs', [])
    if logs:
        summary += "## Session Log:\n"
        for log in logs:
            summary += f"• {log.get('entry', '')}\n"
        summary += "\n"
    
    # Add active notebook entries
    active_entries = session.get('active_notebook_entries', [])
    if active_entries and session_id in storage.notebooks:
        summary += "## Active Knowledge:\n"
        for name in active_entries:
            if name in storage.notebooks[session_id]:
                data = storage.notebooks[session_id][name]["data"]
                summary += f"• **{name}**: {data}\n"
        summary += "\n"
    
    summary += "---\n"
    summary += "**To continue this session:** Use `marm_start` and `marm_notebook_use` to restore context.\n"
    
    return summary

@mcp.tool()
def marm_show_context(session_name: Optional[str] = None) -> str:
    """
    Show current session context and active state.
    
    Args:
        session_name: Session to show (uses current session if not specified)
    
    Returns:
        Current session status and context
    """
    session_id = session_name or storage.get_current_session_id()
    current_id = storage.get_current_session_id()
    protocol_active = storage.config.get("active_protocol", False)
    
    result = f"🧠 **MARM Context Status**\n\n"
    result += f"**Current Session:** {current_id}\n"
    result += f"**Protocol Active:** {'✅ Yes' if protocol_active else '❌ No'}\n"
    result += f"**Viewing Session:** {session_id}\n\n"
    
    if session_id not in storage.sessions:
        result += f"❌ Session '{session_id}' not found\n"
        result += f"**Available Sessions:** {list(storage.sessions.keys())}\n"
        return result
    
    session = storage.sessions[session_id]
    result += f"**Session Created:** {session.get('created', 'Unknown')}\n"
    result += f"**Log Entries:** {len(session.get('logs', []))}\n"
    result += f"**Active Notebook Entries:** {len(session.get('active_notebook_entries', []))}\n\n"
    
    # Show recent log entries
    logs = session.get('logs', [])
    if logs:
        result += "**Recent Log Entries:**\n"
        for log in logs[-3:]:  # Show last 3 entries
            result += f"• {log.get('entry', '')}\n"
        if len(logs) > 3:
            result += f"... and {len(logs) - 3} more entries\n"
    
    return result

@mcp.tool()
def marm_list_sessions() -> str:
    """
    List all available sessions.
    
    Returns:
        List of all sessions with basic info
    """
    if not storage.sessions:
        return "📋 No sessions found. Use `marm_start` to create your first session."
    
    current_id = storage.get_current_session_id()
    result = f"📋 **Available Sessions** (Current: {current_id}):\n\n"
    
    for session_id, session in storage.sessions.items():
        marker = "👉 " if session_id == current_id else "   "
        log_count = len(session.get('logs', []))
        notebook_count = len(storage.notebooks.get(session_id, {}))
        created = session.get('created', 'Unknown')[:10]  # Just the date part
        
        result += f"{marker}**{session_id}**\n"
        result += f"    Created: {created} | Logs: {log_count} | Notebook: {notebook_count} entries\n\n"
    
    return result

def main():
    """Main entry point for the MCP server"""
    parser = argparse.ArgumentParser(description="MARM MCP Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--http", action="store_true", help="Run as HTTP server")
    parser.add_argument("--port", type=int, default=9999, help="Port for HTTP server (default: 9999)")
    parser.add_argument("--host", default="localhost", help="Host for HTTP server (default: localhost)")
    args = parser.parse_args()
    
    if args.debug:
        print(f"🚀 Starting MARM MCP Server v{SERVER_VERSION}")
        print(f"📁 Data directory: {DATA_DIR}")
        print(f"📝 Sessions: {len(storage.sessions)}")
        print(f"📚 Notebooks: {sum(len(nb) for nb in storage.notebooks.values())}")
    
    # Run the FastMCP server
    if args.http:
        if args.debug:
            print(f"🌐 Starting HTTP server on {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        if args.debug:
            print("📡 Starting STDIO server")
        mcp.run()

if __name__ == "__main__":
    main()