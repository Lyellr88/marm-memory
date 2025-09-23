"""
MARM MCP Server - Memory Accurate Response Mode for Model Context Protocol

This server integrates all modular components of the MARM protocol into a single
FastAPI application, compliant with the MCP protocol via FastApiMCP.

Author: Lyell - MARM Systems
Version: 2.2.5
"""

import uvicorn
import uuid
import json
import os
import sys
import psutil
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Body
from fastapi_mcp import FastApiMCP
from fastapi.responses import JSONResponse, RedirectResponse
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path
import sqlite3


# Configure structured logging
logger = structlog.get_logger()

# Simple usage tracking
def track_usage(event_type: str, endpoint: str = None, user_data: dict = None):
    """Track MCP usage events for launch analytics"""
    try:
        usage_db = ANALYTICS_DB_PATH
        
        # Create analytics table if it doesn't exist
        with sqlite3.connect(usage_db) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    endpoint TEXT,
                    user_agent TEXT,
                    ip_address TEXT,
                    session_id TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Insert usage event
            conn.execute('''
                INSERT INTO usage_events (timestamp, event_type, endpoint, user_agent, ip_address, session_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                event_type,
                endpoint,
                user_data.get('user_agent', 'unknown') if user_data else 'unknown',
                user_data.get('ip_address', 'unknown') if user_data else 'unknown',
                user_data.get('session_id', 'unknown') if user_data else 'unknown',
                str(user_data) if user_data else '{}'
            ))
            
        logger.info("Usage tracked", event_type=event_type, endpoint=endpoint)
    except Exception as e:
        # Don't break MCP if analytics fails
        logger.warning("Analytics tracking failed", error=str(e))

# Import rate limiting middleware
from middleware.rate_limiting import rate_limit_middleware

# Import configuration and services
from config.settings import (
    SEMANTIC_SEARCH_AVAILABLE, 
    SCHEDULER_AVAILABLE,
    SERVER_HOST,
    SERVER_PORT,
    SERVER_VERSION,
    DEFAULT_DB_PATH,
    ANALYTICS_DB_PATH
)
from services.documentation import load_marm_documentation
from services.automation import register_event_handlers

# Import all endpoint routers
from endpoints.session import router as session_router
from endpoints.logging import router as logging_router
from endpoints.reasoning import router as reasoning_router
from endpoints.notebook import router as notebook_router
from endpoints.memory import router as memory_router
from endpoints.system import router as system_router
from endpoints.websocket import router as websocket_router
from endpoints.oauth import router as oauth_router

import httpx
import asyncio
from fastapi.testclient import TestClient
# ...

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan management for startup and shutdown"""
    # Startup
    logger.info("Initializing MARM MCP Server", version=SERVER_VERSION)
    
    # Measure memory before loading
    memory_before = get_memory_usage()
    logger.info("Initial memory usage", memory_mb=f"{memory_before:.1f}")
    
    # Show database paths
    logger.info("Database locations",
                memory_db=DEFAULT_DB_PATH,
                analytics_db=ANALYTICS_DB_PATH)
    
    # Load all MARM documentation into memory
    await load_marm_documentation()
    
    # Register automation event handlers
    register_event_handlers()
    
    # Check memory usage after loading
    memory_after = get_memory_usage()
    logger.info("Memory usage after startup", memory_mb=f"{memory_after:.1f}")
    
    # Report memory increase from startup
    memory_increase = memory_after - memory_before
    logger.info("Startup memory increase", increase_mb=f"{memory_increase:.1f}")
    
    logger.info("MARM MCP Server initialization complete")
    
    # Track server startup
    track_usage("server_startup", user_data={"version": SERVER_VERSION})


    yield

    # Shutdown (cleanup if needed)
    logger.info("Shutting down MARM MCP Server")
    track_usage("server_shutdown")

# Create the main FastAPI application with modern lifespan
app = FastAPI(
    title="MARM MCP Server",
    description="Memory Accurate Response Mode - Complete Protocol Implementation",
    version=SERVER_VERSION,
    lifespan=lifespan
)

# Add rate limiting middleware (applies to all routes)
app.middleware("http")(rate_limit_middleware)

# OAuth endpoints now handled by oauth_router

def get_memory_usage():
    """Get current memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024  # MB






# Modern lifespan management implemented above - no deprecated startup events needed

# Include all the modular routers
app.include_router(session_router)
app.include_router(logging_router)
app.include_router(reasoning_router)
app.include_router(notebook_router)
app.include_router(memory_router)
app.include_router(system_router)
app.include_router(websocket_router)
app.include_router(oauth_router)



# Create and mount the MCP server wrapper
mcp = FastApiMCP(app)
mcp.mount_http()

# Main execution block for development
def check_dependencies():
    """Validate all system dependencies and requirements"""
    print("MARM MCP Server - Dependency Check")
    print("="*40)
    
    issues = []
    
    # Python version check
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"Python version: {python_version}")
    if sys.version_info < (3, 8):
        issues.append("Python 3.8+ required")
    else:
        print("Python version OK")
    
    # Core dependencies check
    required_modules = [
        ("fastapi", "FastAPI web framework"),
        ("fastapi_mcp", "MCP protocol implementation"),
        ("uvicorn", "ASGI web server"),
        ("pydantic", "Data validation"),
        ("sqlite3", "Database (built-in)"),
        ("structlog", "Structured logging")
    ]
    
    for module, description in required_modules:
        try:
            if module == "sqlite3":
                import sqlite3
            else:
                __import__(module)
            print(f"OK {description}")
        except ImportError:
            issues.append(f"Missing: {module} ({description})")
            print(f"Missing: {module}")
    
    # Optional features check
    print("\nOptional Features:")
    if SEMANTIC_SEARCH_AVAILABLE:
        print("OK Semantic search (sentence-transformers)")
    else:
        print("Semantic search disabled - install sentence-transformers")
    
    if SCHEDULER_AVAILABLE:
        print("OK Automation scheduler (apscheduler)")
    else:
        print("Scheduler disabled - install apscheduler")
    
    # Database path check
    print(f"\nDatabase location: {DEFAULT_DB_PATH}")
    db_dir = Path(DEFAULT_DB_PATH).parent
    if db_dir.exists() and os.access(db_dir, os.W_OK):
        print("OK Database directory writable")
    else:
        issues.append(f"Cannot write to database directory: {db_dir}")
    
    # Summary
    print("\n" + "="*40)
    if issues:
        print("Issues found:")
        for issue in issues:
            print(f"   • {issue}")
        print("\nRun: pip install -r requirements.txt")
        return False
    else:
        print("All dependencies satisfied!")
        print("Ready to start MARM MCP Server")
        return True

async def run_server_with_shutdown():
    """Run server with proper signal handling and graceful shutdown"""
    from core.shutdown_manager import shutdown_manager

    # Setup signal handlers
    await shutdown_manager.setup_signal_handlers()

    # Configure uvicorn server
    config = uvicorn.Config(
        app,
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level="info"
    )
    server = uvicorn.Server(config)

    # Start server in background
    server_task = asyncio.create_task(server.serve())

    # Wait for shutdown signal
    shutdown_task = asyncio.create_task(shutdown_manager.wait_for_shutdown())

    # Wait for either server completion or shutdown signal
    done, pending = await asyncio.wait(
        [server_task, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED
    )

    # If shutdown signal received, perform graceful shutdown
    if shutdown_task in done:
        logger.info("Shutdown signal received, closing server")

        # Perform graceful shutdown
        await shutdown_manager.graceful_shutdown()

        # Stop the server
        server.should_exit = True

        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Wait for server to finish
        try:
            await server_task
        except asyncio.CancelledError:
            pass

        logger.info("Server shutdown complete")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='MARM MCP Server')
    parser.add_argument('--check-deps', action='store_true',
                       help='Check system dependencies and exit')
    args = parser.parse_args()

    if args.check_deps:
        success = check_dependencies()
        sys.exit(0 if success else 1)

    logger.info("Starting MARM MCP Server",
                version="v2.2.5",
                mcp_endpoint="http://localhost:8001/mcp",
                docs="http://localhost:8001/docs",
                database=DEFAULT_DB_PATH)

    logger.info("Feature status",
                semantic_search="ENABLED" if SEMANTIC_SEARCH_AVAILABLE else "DISABLED - install sentence-transformers",
                scheduler="ENABLED" if SCHEDULER_AVAILABLE else "DISABLED - install apscheduler")

    try:
        asyncio.run(run_server_with_shutdown())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)