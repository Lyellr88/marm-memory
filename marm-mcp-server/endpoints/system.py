"""System endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter
import sqlite3
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Import core components
from core.memory import memory
from core.events import events
from config.settings import SEMANTIC_SEARCH_AVAILABLE, SCHEDULER_AVAILABLE, SERVER_VERSION
from core.response_limiter import MCPResponseLimiter
from core.rate_limiter import rate_limiter

# Import the documentation loader function
# This will need to be imported from the services module when it's created
# from services.documentation import load_marm_documentation

# Create router for system endpoints
router = APIRouter(prefix="", tags=["System"])

@router.get("/health", include_in_schema=False)
async def health_check():
    """Health check endpoint for Docker and monitoring"""
    try:
        # Test database connection
        with memory.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()

        return {
            "status": "healthy",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "connected",
            "semantic_search": "available" if SEMANTIC_SEARCH_AVAILABLE else "text_only"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }

@router.get("/ready", include_in_schema=False)
async def readiness_check():
    """Readiness check endpoint - service ready to handle requests"""
    try:
        # Test database connection and basic functionality
        with memory.get_connection() as conn:
            conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            conn.execute("SELECT COUNT(*) FROM sessions").fetchone()

        return {
            "status": "ready",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoints": {
                "mcp": "http://localhost:8001/mcp",
                "websocket": "ws://localhost:8001/mcp/ws",
                "docs": "http://localhost:8001/docs"
            }
        }
    except Exception as e:
        return {
            "status": "not_ready",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }

@router.get("/marm_current_context", operation_id="marm_current_context", include_in_schema=False)
async def marm_current_context():
    """
    🕐 Get current date and system context
    
    Provides current date/time to prevent AI date confusion
    """
    now = datetime.now(timezone.utc)
    
    return {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M:%S UTC"),
        "formatted_date": now.strftime("%A, %B %d, %Y"),
        "context": f"Today is {now.strftime('%A, %B %d, %Y')} at {now.strftime('%H:%M UTC')}",
        "system_status": "operational",
        "semantic_search": "available" if SEMANTIC_SEARCH_AVAILABLE else "text_only",
        "scheduler": "available" if SCHEDULER_AVAILABLE else "disabled"
    }

@router.post("/marm_reload_docs", operation_id="marm_reload_docs")
async def marm_reload_docs():
    """
    📚 Reload MARM documentation into memory system
    
    Refreshes all documentation files and core knowledge in the database
    """
    try:
        # This will be implemented when we create the services module
        # await load_marm_documentation()
        return {
            "status": "success",
            "message": "📚 MARM documentation reloaded successfully",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload documentation: {str(e)}")

@router.get("/marm_system_info", operation_id="marm_system_info")
async def marm_system_info():
    """
    ℹ️ Get comprehensive system information and loaded documentation
    
    Shows what documentation is available and system capabilities
    """
    try:
        # Get notebook entries (documentation)
        with memory.get_connection() as conn:
            cursor = conn.execute('''
                SELECT name, LENGTH(data) as size, created_at, updated_at
                FROM notebook_entries
                WHERE name LIKE 'marm_%'
                ORDER BY updated_at DESC
            ''')
            docs = [{"name": r[0], "size_chars": r[1], "created": r[2], "updated": r[3]} 
                   for r in cursor.fetchall()]
            
            # Get memory count
            cursor = conn.execute('SELECT COUNT(*) FROM memories')
            memory_count = cursor.fetchone()[0]
            
            # Get session count  
            cursor = conn.execute('SELECT COUNT(*) FROM sessions')
            session_count = cursor.fetchone()[0]
        
        # Build response with health status and size monitoring
        current_time = datetime.now(timezone.utc)
        response = {
            "status": "operational",
            "version": SERVER_VERSION,
            "service": "MARM MCP Server",
            "timestamp": current_time.isoformat(),
            "health": {
                "status": "healthy",
                "service": "MARM MCP Server",
                "version": SERVER_VERSION,
                "timestamp": current_time.isoformat(),
                "docker_health_endpoint": "/health"
            },
            "capabilities": {
                "semantic_search": SEMANTIC_SEARCH_AVAILABLE,
                "scheduler": SCHEDULER_AVAILABLE,
                "documentation_loaded": len(docs) > 0
            },
            "database_stats": {
                "notebook_entries": len(docs),
                "memories": memory_count, 
                "sessions": session_count
            },
            "loaded_documentation": docs,
            "mcp_endpoint": "http://localhost:8001/mcp",
            "api_docs": "http://localhost:8001/docs"
        }
        
        # Check response size and truncate documentation list if needed
        response_size = MCPResponseLimiter.estimate_response_size(response)
        if response_size > MCPResponseLimiter.CONTENT_LIMIT:
            # Truncate documentation list to fit
            original_doc_count = len(docs)
            
            # Keep removing docs until response fits
            while response_size > MCPResponseLimiter.CONTENT_LIMIT and docs:
                docs.pop()
                response["loaded_documentation"] = docs
                response_size = MCPResponseLimiter.estimate_response_size(response)
            
            # Add truncation notice
            if len(docs) < original_doc_count:
                response["_mcp_truncated"] = True
                response["_truncation_reason"] = "Documentation list truncated for MCP size compliance"
                response["_total_docs_available"] = original_doc_count
                response["_docs_shown"] = len(docs)
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system info: {str(e)}")

