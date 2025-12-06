"""
MARM MCP Server - STDIO Version
Memory Accurate Response Mode for Model Context Protocol

This is a STDIO-compatible version using FastMCP instead of FastAPI.
All core business logic is reused from the existing modules.

This enables MARM to work with MCP clients that require STDIO transport,
such as orchestration platforms and command-line tools.

Author: MARM Systems (STDIO transport addition)
Version: 2.2.6
"""

import sys
import os
import asyncio
from pathlib import Path
from typing import Optional

# Add the server directory to the path
sys.path.insert(0, str(Path(__file__).parent))

# Import FastMCP (using OI-OS fork)
from fastmcp import FastMCP

# Import core components (reused from FastAPI version)
from core.memory import memory
from core.events import events
from core.response_limiter import MCPResponseLimiter
from utils.helpers import read_protocol_file
from config.settings import (
    SERVER_VERSION,
    DEFAULT_DB_PATH,
    SEMANTIC_SEARCH_AVAILABLE,
    SCHEDULER_AVAILABLE
)

# Initialize FastMCP server
mcp = FastMCP("MARM MCP Server")

# Response limiter for MCP compliance
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
    import sqlite3
    from datetime import datetime, timezone
    
    try:
        with memory.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, marm_active, last_accessed)
                VALUES (?, TRUE, ?)
            ''', (session_name, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        
        # Read the current protocol from file
        protocol_content = await read_protocol_file()
        
        await events.emit('marm_started', {'session': session_name})
        
        return {
            "status": "success",
            "message": f"🚀 MARM protocol activated for session '{session_name}'",
            "session_name": session_name,
            "marm_active": True,
            "protocol_content": protocol_content,
            "instructions": "The complete MARM protocol documentation has been loaded and is available for reference."
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error during MARM start: {str(e)}"
        }

@mcp.tool()
async def marm_refresh(session_name: str) -> dict:
    """
    🔄 Refreshes active session state and reaffirms protocol adherence
    
    Equivalent to /refresh marm command
    """
    import sqlite3
    from datetime import datetime, timezone
    
    try:
        with memory.get_connection() as conn:
            conn.execute('''
                UPDATE sessions SET last_accessed = ? WHERE session_name = ?
            ''', (datetime.now(timezone.utc).isoformat(), session_name))
            conn.commit()
        
        # Read the current protocol from file to reaffirm adherence
        protocol_content = await read_protocol_file()
        
        await events.emit('marm_refreshed', {'session': session_name})
        
        return {
            "status": "success", 
            "message": f"🔄 MARM session '{session_name}' refreshed - protocol adherence reaffirmed",
            "session_name": session_name,
            "protocol_content": protocol_content,
            "instructions": "Protocol documentation refreshed. Please review the current MARM protocol specifications above."
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error during MARM refresh: {str(e)}"
        }

# ============================================================================
# Memory Tools
# ============================================================================

@mcp.tool()
async def marm_smart_recall(
    query: str,
    session_name: str = "default",
    limit: int = 5,
    search_all: bool = False
) -> dict:
    """
    🧠 Intelligent memory recall based on semantic similarity
    
    Finds relevant memories using semantic similarity or text search.
    Returns the most relevant memories with similarity scores.
    """
    try:
        # Determine which session(s) to search
        search_session = None if search_all else session_name
        
        similar_memories = await memory.recall_similar(query, session=search_session, limit=limit)
        
        if not similar_memories:
            # If searching all sessions and still no results, check system session specifically
            if not search_all:
                system_memories = await memory.recall_similar(query, session="marm_system", limit=limit)
                
                response = {
                    "status": "no_results",
                    "query": query,
                    "session_name": session_name,
                    "search_all": search_all,
                    "results": []
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
        
        # Format results for MCP response
        formatted_results = []
        for mem in similar_memories:
            formatted_results.append({
                "id": mem.get("id"),
                "content": mem.get("content"),
                "session_name": mem.get("session_name"),
                "similarity": mem.get("similarity", 0.0),
                "timestamp": mem.get("timestamp"),
                "context_type": mem.get("context_type", "general")
            })
        
        # Apply response size limiting
        response_metadata = {
            "status": "success",
            "query": query,
            "session_name": session_name,
            "search_all": search_all,
        }
        
        limited_results, was_truncated = response_limiter.limit_memory_response(
            formatted_results, response_metadata
        )
        
        response_data = response_metadata.copy()
        response_data["results_count"] = len(limited_results)
        response_data["results"] = limited_results
        
        if was_truncated:
            response_data = response_limiter.add_truncation_notice(
                response_data, was_truncated, len(formatted_results)
            )
        
        return response_data
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error during smart recall: {str(e)}"
        }

@mcp.tool()
async def marm_contextual_log(
    content: str,
    session_name: str = "default",
    context_type: str = "general",
    metadata: Optional[dict] = None
) -> dict:
    """
    📝 Log contextual information with automatic categorization
    
    Saves information to memory with automatic context type detection.
    """
    try:
        # Use the core memory module to save
        memory_id = await memory.store_memory(
            content=content,
            session=session_name,
            context_type=context_type,
            metadata=metadata or {}
        )
        
        await events.emit('memory_logged', {
            'session': session_name,
            'memory_id': memory_id,
            'context_type': context_type
        })
        
        return {
            "status": "success",
            "message": f"✅ Contextual information logged to session '{session_name}'",
            "memory_id": memory_id,
            "session_name": session_name,
            "context_type": context_type
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error during contextual log: {str(e)}"
        }

# ============================================================================
# Logging Tools
# ============================================================================

@mcp.tool()
async def marm_log_session(session_name: str) -> dict:
    """
    📋 Create or switch to named session container
    """
    import sqlite3
    from datetime import datetime, timezone
    
    try:
        with memory.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
            ''', (session_name, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        
        await events.emit('session_created', {'session': session_name})
        
        return {
            "status": "success",
            "message": f"✅ Session '{session_name}' created/activated",
            "session_name": session_name
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error creating session: {str(e)}"
        }

@mcp.tool()
async def marm_log_entry(
    content: str,
    session_name: str = "default",
    metadata: Optional[dict] = None
) -> dict:
    """
    📝 Log important information to MARM's memory system
    """
    try:
        memory_id = await memory.store_memory(
            content=content,
            session=session_name,
            context_type="general",
            metadata=metadata or {}
        )
        
        await events.emit('log_entry_created', {
            'session': session_name,
            'memory_id': memory_id
        })
        
        return {
            "status": "success",
            "message": f"✅ Log entry created in session '{session_name}'",
            "memory_id": memory_id,
            "session_name": session_name
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error creating log entry: {str(e)}"
        }

@mcp.tool()
async def marm_log_show(
    session_name: str = "default",
    limit: int = 10,
    offset: int = 0
) -> dict:
    """
    📋 Display memory log entries
    """
    try:
        # Get memories using text search with empty query to get all
        memories = await memory.recall_text_search("", session=session_name, limit=limit)
        
        formatted_memories = []
        for mem in memories:
            formatted_memories.append({
                "id": mem.get("id"),
                "content": mem.get("content"),
                "timestamp": mem.get("timestamp"),
                "context_type": mem.get("context_type", "general")
            })
        
        response_metadata = {
            "status": "success",
            "session_name": session_name,
        }
        
        limited_entries, was_truncated = response_limiter.limit_memory_response(
            formatted_memories, response_metadata
        )
        
        response_data = response_metadata.copy()
        response_data["count"] = len(limited_entries)
        response_data["entries"] = limited_entries
        
        if was_truncated:
            response_data = response_limiter.add_truncation_notice(
                response_data, was_truncated, len(formatted_memories)
            )
        
        return response_data
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error retrieving log entries: {str(e)}"
        }

@mcp.tool()
async def marm_log_delete(
    session_name: str = None,
    memory_id: str = None
) -> dict:
    """
    🗑️ Delete specified session or individual entries
    """
    try:
        if session_name:
            # Delete entire session
            with memory.get_connection() as conn:
                conn.execute('DELETE FROM memories WHERE session_name = ?', (session_name,))
                conn.execute('DELETE FROM sessions WHERE session_name = ?', (session_name,))
                conn.commit()
            
            await events.emit('session_deleted', {'session': session_name})
            
            return {
                "status": "success",
                "message": f"✅ Session '{session_name}' deleted"
            }
        elif memory_id:
            # Delete specific memory
            with memory.get_connection() as conn:
                conn.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
                conn.commit()
            
            await events.emit('memory_deleted', {'memory_id': memory_id})
            
            return {
                "status": "success",
                "message": f"✅ Memory entry '{memory_id}' deleted"
            }
        else:
            return {
                "status": "error",
                "message": "Either session_name or memory_id must be provided"
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error deleting: {str(e)}"
        }

# ============================================================================
# Notebook Tools
# ============================================================================

@mcp.tool()
async def marm_notebook_add(
    notebook_name: str,
    content: str,
    metadata: Optional[dict] = None
) -> dict:
    """
    📔 Add structured information to MARM notebooks
    """
    try:
        # Notebooks are stored as memories with special context type
        memory_id = await memory.store_memory(
            content=content,
            session="notebooks",
            context_type="notebook",
            metadata={"notebook_name": notebook_name, **(metadata or {})}
        )
        
        await events.emit('notebook_entry_added', {
            'notebook_name': notebook_name,
            'memory_id': memory_id
        })
        
        return {
            "status": "success",
            "message": f"✅ Entry added to notebook '{notebook_name}'",
            "memory_id": memory_id,
            "notebook_name": notebook_name
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error adding notebook entry: {str(e)}"
        }

@mcp.tool()
async def marm_notebook_use(notebook_name: str) -> dict:
    """
    📖 Retrieve and use notebook information
    """
    try:
        memories = await memory.recall_similar(
            query=notebook_name,
            session="notebooks",
            limit=50
        )
        
        # Filter for this specific notebook
        notebook_entries = [
            m for m in memories 
            if m.get("metadata", {}).get("notebook_name") == notebook_name
        ]
        
        response_metadata = {
            "status": "success",
            "notebook_name": notebook_name,
        }
        
        limited_entries, was_truncated = response_limiter.limit_memory_response(
            notebook_entries, response_metadata
        )
        
        response_data = response_metadata.copy()
        response_data["entries_count"] = len(limited_entries)
        response_data["entries"] = limited_entries
        
        if was_truncated:
            response_data = response_limiter.add_truncation_notice(
                response_data, was_truncated, len(notebook_entries)
            )
        
        return response_data
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error retrieving notebook: {str(e)}"
        }

@mcp.tool()
async def marm_notebook_show(notebook_name: str = None) -> dict:
    """
    📋 Display notebook contents and structure
    """
    try:
        if notebook_name:
            memories = await memory.recall_similar(
                query=notebook_name,
                session="notebooks",
                limit=100
            )
            notebook_entries = [
                m for m in memories 
                if m.get("metadata", {}).get("notebook_name") == notebook_name
            ]
        else:
            # Show all notebooks
            memories = await memory.recall_text_search("", session="notebooks", limit=1000)
            notebook_entries = memories
        
        response_metadata = {
            "status": "success",
            "notebook_name": notebook_name or "all",
        }
        
        # Limit to 50 entries for display
        display_entries = notebook_entries[:50]
        
        limited_entries, was_truncated = response_limiter.limit_memory_response(
            display_entries, response_metadata
        )
        
        response_data = response_metadata.copy()
        response_data["entries_count"] = len(limited_entries)
        response_data["entries"] = limited_entries
        
        if was_truncated or len(notebook_entries) > 50:
            response_data = response_limiter.add_truncation_notice(
                response_data, True, len(notebook_entries)
            )
        
        return response_data
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error showing notebook: {str(e)}"
        }

@mcp.tool()
async def marm_notebook_status(notebook_name: str = None) -> dict:
    """
    📊 Check notebook status and metadata
    """
    try:
        if notebook_name:
            memories = await memory.recall_similar(
                query=notebook_name,
                session="notebooks",
                limit=1000
            )
            notebook_entries = [
                m for m in memories 
                if m.get("metadata", {}).get("notebook_name") == notebook_name
            ]
        else:
            memories = await memory.recall_text_search("", session="notebooks", limit=1000)
            notebook_entries = memories
        
        # Group by notebook name
        notebooks = {}
        for entry in notebook_entries:
            nb_name = entry.get("metadata", {}).get("notebook_name", "unnamed")
            if nb_name not in notebooks:
                notebooks[nb_name] = []
            notebooks[nb_name].append(entry)
        
        status = {
            "status": "success",
            "notebooks": {
                name: {
                    "entry_count": len(entries),
                    "last_updated": max(e.get("timestamp", "") for e in entries) if entries else ""
                }
                for name, entries in notebooks.items()
            }
        }
        
        return status
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error checking notebook status: {str(e)}"
        }

@mcp.tool()
async def marm_notebook_clear(notebook_name: str) -> dict:
    """
    🧹 Clear notebook contents
    """
    try:
        with memory.get_connection() as conn:
            conn.execute('''
                DELETE FROM memories 
                WHERE session_name = 'notebooks' 
                AND json_extract(metadata, '$.notebook_name') = ?
            ''', (notebook_name,))
            conn.commit()
        
        await events.emit('notebook_cleared', {'notebook_name': notebook_name})
        
        return {
            "status": "success",
            "message": f"✅ Notebook '{notebook_name}' cleared"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error clearing notebook: {str(e)}"
        }

@mcp.tool()
async def marm_notebook_delete(notebook_name: str) -> dict:
    """
    🗑️ Delete specific notebook entry
    """
    try:
        with memory.get_connection() as conn:
            conn.execute('''
                DELETE FROM memories 
                WHERE session_name = 'notebooks' 
                AND json_extract(metadata, '$.notebook_name') = ?
            ''', (notebook_name,))
            conn.commit()
        
        await events.emit('notebook_deleted', {'notebook_name': notebook_name})
        
        return {
            "status": "success",
            "message": f"✅ Notebook '{notebook_name}' deleted"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error deleting notebook: {str(e)}"
        }

# ============================================================================
# Workflow Tools
# ============================================================================

@mcp.tool()
async def marm_summary(
    session_name: str = "default",
    limit: int = 20
) -> dict:
    """
    📊 Generate intelligent summaries from memory data
    """
    try:
        memories = await memory.recall_text_search("", session=session_name, limit=limit)
        
        if not memories:
            return {
                "status": "no_data",
                "message": f"No memories found in session '{session_name}'"
            }
        
        # Simple summary: group by context type and count
        summary = {
            "status": "success",
            "session_name": session_name,
            "total_memories": len(memories),
            "by_context_type": {}
        }
        
        for mem in memories:
            ctx_type = mem.get("context_type", "general")
            if ctx_type not in summary["by_context_type"]:
                summary["by_context_type"][ctx_type] = 0
            summary["by_context_type"][ctx_type] += 1
        
        return summary
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error generating summary: {str(e)}"
        }

@mcp.tool()
async def marm_context_bridge(
    from_session: str,
    to_session: str,
    query: str = None
) -> dict:
    """
    🌉 Smart context bridging for seamless AI agent workflow transitions
    """
    try:
        # Find relevant memories in source session
        if query:
            memories = await memory.recall_similar(query, session=from_session, limit=10)
        else:
            memories = await memory.recall_text_search("", session=from_session, limit=10)
        
        # Copy relevant memories to target session
        copied_count = 0
        for mem in memories:
            await memory.store_memory(
                content=mem.get("content"),
                session=to_session,
                context_type=mem.get("context_type", "general"),
                metadata={"bridged_from": from_session, **mem.get("metadata", {})}
            )
            copied_count += 1
        
        return {
            "status": "success",
            "message": f"✅ Bridged {copied_count} memories from '{from_session}' to '{to_session}'",
            "from_session": from_session,
            "to_session": to_session,
            "memories_copied": copied_count
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error bridging context: {str(e)}"
        }

# ============================================================================
# System Tools
# ============================================================================

@mcp.tool()
async def marm_current_context() -> dict:
    """
    🕐 Get current date/time for accurate log entry timestamps
    """
    from datetime import datetime, timezone
    
    return {
        "status": "success",
        "current_time": datetime.now(timezone.utc).isoformat(),
        "timestamp": datetime.now(timezone.utc).timestamp()
    }

@mcp.tool()
async def marm_system_info() -> dict:
    """
    ℹ️ Comprehensive system information, health status, and loaded docs
    """
    import psutil
    
    try:
        # Get memory usage
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        
        # Get database info
        db_size = 0
        if os.path.exists(DEFAULT_DB_PATH):
            db_size = os.path.getsize(DEFAULT_DB_PATH) / 1024 / 1024  # MB
        
        # Count memories
        with memory.get_connection() as conn:
            cursor = conn.execute('SELECT COUNT(*) FROM memories')
            memory_count = cursor.fetchone()[0]
            
            cursor = conn.execute('SELECT COUNT(*) FROM sessions')
            session_count = cursor.fetchone()[0]
        
        return {
            "status": "success",
            "version": SERVER_VERSION,
            "system": {
                "memory_usage_mb": round(memory_mb, 2),
                "database_size_mb": round(db_size, 2),
                "database_path": DEFAULT_DB_PATH
            },
            "features": {
                "semantic_search": SEMANTIC_SEARCH_AVAILABLE,
                "scheduler": SCHEDULER_AVAILABLE
            },
            "statistics": {
                "total_memories": memory_count,
                "total_sessions": session_count
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting system info: {str(e)}"
        }

@mcp.tool()
async def marm_reload_docs() -> dict:
    """
    🔄 Reload documentation into memory system
    """
    try:
        protocol_content = await read_protocol_file()
        
        # Save to system session
        await memory.store_memory(
            content=protocol_content,
            session="marm_system",
            context_type="documentation",
            metadata={"source": "protocol_file", "reloaded": True}
        )
        
        return {
            "status": "success",
            "message": "✅ Documentation reloaded into memory system",
            "protocol_length": len(protocol_content)
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error reloading docs: {str(e)}"
        }

# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    # Run the FastMCP server with STDIO
    mcp.run()

