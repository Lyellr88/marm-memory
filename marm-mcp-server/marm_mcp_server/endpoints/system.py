"""System endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter
import logging
from datetime import datetime, timezone

# Setup logging for security error tracking
logger = logging.getLogger(__name__)

# Import core components
from ..core.memory import memory
from ..config.settings import SEMANTIC_SEARCH_AVAILABLE, SERVER_VERSION

from ..services.documentation import reload_marm_documentation

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
        # Log detailed error server-side for debugging (secure)
        logger.error(f"Health check failed: {str(e)}", exc_info=True)

        # Return generic error message to external users (secure)
        return {
            "status": "unhealthy",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "Service temporarily unavailable"
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
                "docs": "http://localhost:8001/docs"
            }
        }
    except Exception as e:
        # Log detailed error server-side for debugging (secure)
        logger.error(f"Readiness check failed: {str(e)}", exc_info=True)

        # Return generic error message to external users (secure)
        return {
            "status": "not_ready",
            "service": "MARM MCP Server",
            "version": SERVER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "Service not ready"
        }

@router.post("/marm_reload_docs", operation_id="marm_reload_docs", include_in_schema=False)
async def marm_reload_docs():
    """
    📚 Reload MARM documentation into memory system
    
    Refreshes all documentation files and core knowledge in the database
    """
    try:
        await reload_marm_documentation()
        return {
            "status": "success",
            "message": "📚 MARM documentation reloaded successfully",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload documentation: {str(e)}")

