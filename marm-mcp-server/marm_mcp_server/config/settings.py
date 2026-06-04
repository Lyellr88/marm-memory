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

# Server configuration
SERVER_HOST = os.environ.get('SERVER_HOST', '127.0.0.1')
SERVER_PORT = int(os.environ.get('SERVER_PORT', 8001))
SERVER_VERSION = "2.9.1"

# Rate limiting configuration. MARM_RATE_LIMIT_RPM=0 disables limiting.
MARM_RATE_LIMIT_RPM = int(os.environ.get('MARM_RATE_LIMIT_RPM', '80'))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get('RATE_LIMIT_WINDOW_SECONDS', '60'))
RATE_LIMIT_BLOCK_SECONDS = int(os.environ.get('RATE_LIMIT_BLOCK_SECONDS', '30'))

# Serialized write queue is enabled by default to reduce SQLite writer contention.
WRITE_QUEUE_ENABLED = os.environ.get('WRITE_QUEUE_ENABLED', '1') == '1'
MAX_QUEUE_SIZE = int(os.environ.get('MAX_QUEUE_SIZE', '100'))

# Consolidation — default off. CONSOLIDATION_ENABLED=1 activates hash dedup (Layer 1)
# and semantic merge (Layer 2). Threshold only applies to semantic merge.
CONSOLIDATION_ENABLED = os.environ.get('CONSOLIDATION_ENABLED', '0') == '1'
CONSOLIDATION_THRESHOLD = float(os.environ.get('CONSOLIDATION_THRESHOLD', '0.92'))

# Compaction worker — Layer 3 background cluster detection and dry-run reporting. Off by default.
COMPACTION_ENABLED = os.environ.get('COMPACTION_ENABLED', '0') == '1'
COMPACTION_TRIGGER_COUNT = int(os.environ.get('COMPACTION_TRIGGER_COUNT', '5'))
COMPACTION_SIMILARITY_THRESHOLD = float(os.environ.get('COMPACTION_SIMILARITY_THRESHOLD', '0.88'))
COMPACTION_MIN_CLUSTER_SIZE = int(os.environ.get('COMPACTION_MIN_CLUSTER_SIZE', '3'))
COMPACTION_MIN_AGE_HOURS = int(os.environ.get('COMPACTION_MIN_AGE_HOURS', '24'))
COMPACTION_ACTIVE_SESSION_GRACE_MINUTES = int(os.environ.get('COMPACTION_ACTIVE_SESSION_GRACE_MINUTES', '15'))
COMPACTION_STAGING_TTL_HOURS = int(os.environ.get('COMPACTION_STAGING_TTL_HOURS', '168'))
COMPACTION_AUTO_APPLY_ENABLED = os.environ.get('COMPACTION_AUTO_APPLY_ENABLED', '0') == '1'
COMPACTION_AUTO_APPLY_INTERVAL_MINUTES = int(os.environ.get('COMPACTION_AUTO_APPLY_INTERVAL_MINUTES', '60'))
COMPACTION_MAX_NUDGES = int(os.environ.get('COMPACTION_MAX_NUDGES', '5'))
COMPACTION_NUDGE_COOLDOWN_SECONDS = int(os.environ.get('COMPACTION_NUDGE_COOLDOWN_SECONDS', '2'))
COMPACTION_INJECTION_BYTE_BUDGET = int(os.environ.get('COMPACTION_INJECTION_BYTE_BUDGET', '2048'))

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
