"""Configuration settings for MARM MCP Server."""

# Advanced memory system availability flags
try:
    from sentence_transformers import SentenceTransformer
    SEMANTIC_SEARCH_AVAILABLE = True
except ImportError:
    SEMANTIC_SEARCH_AVAILABLE = False
    print("WARNING: Semantic search not available. Install: pip install sentence-transformers")

# Automation scheduler availability
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    print("WARNING: Scheduler not available. Install: pip install apscheduler")

import os
from pathlib import Path

# Database configuration - Official .marm system directory (CLI standard)
def get_marm_db_path():
    """Get the official MARM database path, respecting environment variable if set"""
    # Check if MARM_DB_PATH environment variable is set (for Docker)
    env_db_path = os.environ.get('MARM_DB_PATH')
    if env_db_path:
        # Ensure the directory exists
        db_dir = Path(env_db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        return env_db_path
    
    # Follow professional CLI standard: ~/.marm/ (like ~/.git, ~/.docker, ~/.claude)
    marm_dir = Path.home() / ".marm"
    
    # Create .marm directory if it doesn't exist
    marm_dir.mkdir(exist_ok=True)
    
    return str(marm_dir / "marm_memory.db")

DEFAULT_DB_PATH = get_marm_db_path()
MAX_DB_CONNECTIONS = 5

# Analytics database path
def get_analytics_db_path():
    """Get the analytics database path, respecting environment variable if set"""
    # Check if MARM_ANALYTICS_DB_PATH environment variable is set
    env_analytics_db_path = os.environ.get('MARM_ANALYTICS_DB_PATH')
    if env_analytics_db_path:
        # Ensure the directory exists
        analytics_dir = os.path.dirname(env_analytics_db_path)
        if analytics_dir:
            os.makedirs(analytics_dir, exist_ok=True)
        return env_analytics_db_path
    
    # For Docker, use /app/data, for local use the current directory or user's home
    if os.path.exists('/app/data'):
        # Docker environment
        return '/app/data/marm_usage_analytics.db'
    else:
        # Local development environment
        return 'marm_usage_analytics.db'

ANALYTICS_DB_PATH = get_analytics_db_path()

# Semantic search configuration  
DEFAULT_SEMANTIC_MODEL = "all-MiniLM-L6-v2"

# Rate limiting configuration (for future Pro version flexibility)
RATE_LIMIT_ENABLED = True
RATE_LIMIT_DEFAULT_REQUESTS = 60
RATE_LIMIT_DEFAULT_WINDOW = 60
RATE_LIMIT_MEMORY_HEAVY_REQUESTS = 20
RATE_LIMIT_SEARCH_REQUESTS = 30

# Server configuration
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.environ.get('SERVER_PORT', 8001))
SERVER_VERSION = "2.2.5"

# WebSocket configuration
WEBSOCKET_HOST = SERVER_HOST
WEBSOCKET_PORT = SERVER_PORT
WEBSOCKET_PATH = "/mcp/ws"
MAX_WEBSOCKET_CONNECTIONS = 100
WEBSOCKET_PING_INTERVAL = 30
WEBSOCKET_PING_TIMEOUT = 10