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
import sys
from pathlib import Path


def _file_link(path: Path) -> str:
    try:
        uri = path.as_uri()
        return f"\033]8;;{uri}\033\\{path}\033]8;;\033\\"
    except Exception:
        return str(path)

from ..utils.security import generate_api_key

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

# Rate limiting configuration
RATE_LIMIT_ENABLED = True
RATE_LIMIT_DEFAULT_REQUESTS = 60
RATE_LIMIT_DEFAULT_WINDOW = 60
RATE_LIMIT_MEMORY_HEAVY_REQUESTS = 20
RATE_LIMIT_SEARCH_REQUESTS = 30

# Server configuration
SERVER_HOST = os.environ.get('SERVER_HOST', '127.0.0.1')
SERVER_PORT = int(os.environ.get('SERVER_PORT', 8001))
SERVER_VERSION = "2.6.2"

# Auth — set MARM_API_KEY to require a Bearer token on all capability routes.
# Leave unset for local-only deployments (loopback enforced automatically).
MARM_API_KEY = os.environ.get('MARM_API_KEY', '')

_MARM_ENV_PATH = Path.home() / ".marm" / ".env"


def _load_key_from_file() -> str:
    """Read MARM_API_KEY from ~/.marm/.env if present."""
    try:
        for line in _MARM_ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith('MARM_API_KEY=') and not line.startswith('#'):
                return line.split('=', 1)[1].strip()
    except Exception:
        pass
    return ''


# File-based key only applies when SERVER_HOST=0.0.0.0.
# Localhost mode (127.0.0.1) is loopback-only and never needs a key,
# so loading the file there would silently break the zero-friction path.
if SERVER_HOST == '0.0.0.0' and not MARM_API_KEY:
    _file_key = _load_key_from_file()
    if _file_key:
        MARM_API_KEY = _file_key

# Auto-generate when: exposed host, no key, and not a --generate-key invocation.
# --generate-key check prevents a double-print when the user explicitly generates
# a key while SERVER_HOST=0.0.0.0 is set (settings import runs before argparse).
_is_generate_key_cmd = '--generate-key' in sys.argv

if SERVER_HOST == '0.0.0.0' and not MARM_API_KEY and not _is_generate_key_cmd:
    MARM_API_KEY = generate_api_key()
    try:
        _marm_dir = Path.home() / ".marm"
        _marm_dir.mkdir(exist_ok=True)
        _MARM_ENV_PATH.write_text(f"MARM_API_KEY={MARM_API_KEY}\n")
    except Exception as _e:
        print(f"WARNING: Could not save API key to {_MARM_ENV_PATH}: {_e}")

    print()
    print("MARM: SERVER_HOST=0.0.0.0 detected — API key auto-generated (first start).")
    print(f"Saved to: {_file_link(_MARM_ENV_PATH)}")
    print()
    print("Add this to your MCP client (replace YOUR_KEY with the key from the file above):")
    print(f'  claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer YOUR_KEY"')
    print()
    print("On subsequent starts the key loads silently from the file above.")
    print()
