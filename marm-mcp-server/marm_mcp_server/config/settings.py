"""Configuration settings for MARM MCP Server."""

import importlib.util
import os
import sys
from pathlib import Path

from ..utils.security import generate_api_key

SEMANTIC_SEARCH_AVAILABLE = (
    importlib.util.find_spec("sentence_transformers") is not None
)
if not SEMANTIC_SEARCH_AVAILABLE:
    print(
        "WARNING: Semantic search not available. Install: pip install sentence-transformers"
    )

SCHEDULER_AVAILABLE = importlib.util.find_spec("apscheduler") is not None
if not SCHEDULER_AVAILABLE:
    print("WARNING: Scheduler not available. Install: pip install apscheduler")


def _file_link(path: Path) -> str:
    try:
        uri = path.as_uri()
        return f"\033]8;;{uri}\033\\{path}\033]8;;\033\\"
    except Exception:
        return str(path)


def get_marm_db_path():
    """Get the official MARM database path, respecting environment variable if set"""
    env_db_path = os.environ.get("MARM_DB_PATH")
    if env_db_path:
        db_dir = Path(env_db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        return env_db_path

    marm_dir = Path.home() / ".marm"

    marm_dir.mkdir(exist_ok=True)

    return str(marm_dir / "marm_memory.db")


DEFAULT_DB_PATH = get_marm_db_path()
MAX_DB_CONNECTIONS = 5


def get_analytics_db_path():
    """Get the analytics database path, respecting environment variable if set"""
    env_analytics_db_path = os.environ.get("MARM_ANALYTICS_DB_PATH")
    if env_analytics_db_path:
        analytics_dir = os.path.dirname(env_analytics_db_path)
        if analytics_dir:
            os.makedirs(analytics_dir, exist_ok=True)
        return env_analytics_db_path

    if os.path.exists("/app/data"):
        return "/app/data/marm_usage_analytics.db"
    else:
        return "marm_usage_analytics.db"


ANALYTICS_DB_PATH = get_analytics_db_path()

DEFAULT_SEMANTIC_MODEL = "all-MiniLM-L6-v2"

SERVER_HOST = os.environ.get("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("SERVER_PORT", 8001))
SERVER_VERSION = "2.10.0"

MARM_RATE_LIMIT_RPM = int(os.environ.get("MARM_RATE_LIMIT_RPM", "80"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_BLOCK_SECONDS = int(os.environ.get("RATE_LIMIT_BLOCK_SECONDS", "30"))

WRITE_QUEUE_ENABLED = os.environ.get("WRITE_QUEUE_ENABLED", "1") == "1"
MAX_QUEUE_SIZE = int(os.environ.get("MAX_QUEUE_SIZE", "100"))
RECALL_SCAN_LIMIT = int(os.environ.get("RECALL_SCAN_LIMIT", "1000"))

CONSOLIDATION_ENABLED = os.environ.get("CONSOLIDATION_ENABLED", "0") == "1"
CONSOLIDATION_THRESHOLD = float(os.environ.get("CONSOLIDATION_THRESHOLD", "0.92"))

COMPACTION_ENABLED = os.environ.get("COMPACTION_ENABLED", "0") == "1"
COMPACTION_TRIGGER_COUNT = int(os.environ.get("COMPACTION_TRIGGER_COUNT", "5"))
COMPACTION_SIMILARITY_THRESHOLD = float(
    os.environ.get("COMPACTION_SIMILARITY_THRESHOLD", "0.88")
)
COMPACTION_MIN_CLUSTER_SIZE = int(os.environ.get("COMPACTION_MIN_CLUSTER_SIZE", "3"))
COMPACTION_MIN_AGE_HOURS = int(os.environ.get("COMPACTION_MIN_AGE_HOURS", "24"))
COMPACTION_ACTIVE_SESSION_GRACE_MINUTES = int(
    os.environ.get("COMPACTION_ACTIVE_SESSION_GRACE_MINUTES", "15")
)
COMPACTION_STAGING_TTL_HOURS = int(
    os.environ.get("COMPACTION_STAGING_TTL_HOURS", "168")
)
COMPACTION_AUTO_APPLY_ENABLED = (
    os.environ.get("COMPACTION_AUTO_APPLY_ENABLED", "0") == "1"
)
COMPACTION_AUTO_APPLY_INTERVAL_MINUTES = int(
    os.environ.get("COMPACTION_AUTO_APPLY_INTERVAL_MINUTES", "60")
)
COMPACTION_MAX_NUDGES = int(os.environ.get("COMPACTION_MAX_NUDGES", "5"))
COMPACTION_NUDGE_COOLDOWN_SECONDS = int(
    os.environ.get("COMPACTION_NUDGE_COOLDOWN_SECONDS", "2")
)
COMPACTION_INJECTION_BYTE_BUDGET = int(
    os.environ.get("COMPACTION_INJECTION_BYTE_BUDGET", "2048")
)

MARM_API_KEY = os.environ.get("MARM_API_KEY", "")

_MARM_ENV_PATH = Path.home() / ".marm" / ".env"


def _load_key_from_file() -> str:
    """Read MARM_API_KEY from ~/.marm/.env if present."""
    try:
        for raw_line in _MARM_ENV_PATH.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("MARM_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                else:
                    value = value.split("#", 1)[0].strip()
                return value
    except Exception:
        pass
    return ""


if SERVER_HOST == "0.0.0.0" and not MARM_API_KEY:
    _file_key = _load_key_from_file()
    if _file_key:
        MARM_API_KEY = _file_key


_is_generate_key_cmd = "--generate-key" in sys.argv

if SERVER_HOST == "0.0.0.0" and not MARM_API_KEY and not _is_generate_key_cmd:
    MARM_API_KEY = generate_api_key()
    try:
        _marm_dir = Path.home() / ".marm"
        _marm_dir.mkdir(exist_ok=True)
        _MARM_ENV_PATH.write_text(f"MARM_API_KEY={MARM_API_KEY}\n")
        try:
            _MARM_ENV_PATH.chmod(0o600)
        except OSError:
            pass
        if sys.platform == "win32":
            try:
                import subprocess
                import getpass

                user = getpass.getuser()
                subprocess.run(
                    [
                        "icacls",
                        str(_MARM_ENV_PATH),
                        "/inheritance:r",
                        "/grant:r",
                        f"{user}:(F)",
                    ],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass
    except Exception as _e:
        print(f"WARNING: Could not save API key to {_MARM_ENV_PATH}: {_e}")

    print()
    print("MARM: SERVER_HOST=0.0.0.0 detected — API key auto-generated (first start).")
    print(f"Saved to: {_file_link(_MARM_ENV_PATH)}")
    print()
    print(
        "Add this to your MCP client (replace YOUR_KEY with the key from the file above):"
    )
    print(
        '  claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer YOUR_KEY"'
    )
    print()
    print("On subsequent starts the key loads silently from the file above.")
    print()
