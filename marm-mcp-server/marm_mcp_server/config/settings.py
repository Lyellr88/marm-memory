"""Configuration settings for MARM MCP Server."""

import importlib.util
import os
import sys
from pathlib import Path

from ..utils.security import generate_api_key


def _safe_int(env_key: str, default: int) -> int:
    """Parse an env var as int, falling back to default on malformed input."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        print(
            f"WARNING: {env_key}={raw!r} is not a valid integer, using default {default}",
            file=sys.stderr,
        )
        return default


def _safe_float(env_key: str, default: float) -> float:
    """Parse an env var as float, falling back to default on malformed input."""
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        print(
            f"WARNING: {env_key}={raw!r} is not a valid number, using default {default}",
            file=sys.stderr,
        )
        return default


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
_raw_port = _safe_int("SERVER_PORT", 8001)
SERVER_PORT = max(1, min(65535, _raw_port))
if not (1 <= _raw_port <= 65535):
    print(
        f"WARNING: SERVER_PORT={_raw_port} out of [1, 65535], clamped to {SERVER_PORT}",
        file=sys.stderr,
    )
SERVER_VERSION = "2.12.2"

_raw_rpm = _safe_int("MARM_RATE_LIMIT_RPM", 80)
# 0 = disable rate limiting; negative values clamped to 0
MARM_RATE_LIMIT_RPM = max(0, _raw_rpm)
if _raw_rpm < 0:
    print(
        f"WARNING: MARM_RATE_LIMIT_RPM={_raw_rpm} below minimum 0, clamped to {MARM_RATE_LIMIT_RPM}",
        file=sys.stderr,
    )

_raw_rls = _safe_int("RATE_LIMIT_WINDOW_SECONDS", 60)
RATE_LIMIT_WINDOW_SECONDS = max(1, _raw_rls)
if _raw_rls < 1:
    print(
        f"WARNING: RATE_LIMIT_WINDOW_SECONDS={_raw_rls} below minimum 1, clamped to {RATE_LIMIT_WINDOW_SECONDS}",
        file=sys.stderr,
    )

_raw_rbs = _safe_int("RATE_LIMIT_BLOCK_SECONDS", 30)
RATE_LIMIT_BLOCK_SECONDS = max(0, _raw_rbs)
if _raw_rbs < 0:
    print(
        f"WARNING: RATE_LIMIT_BLOCK_SECONDS={_raw_rbs} below minimum 0, clamped to {RATE_LIMIT_BLOCK_SECONDS}",
        file=sys.stderr,
    )

WRITE_QUEUE_ENABLED = os.environ.get("WRITE_QUEUE_ENABLED", "1") == "1"

_raw_mqs = _safe_int("MAX_QUEUE_SIZE", 100)
MAX_QUEUE_SIZE = max(1, _raw_mqs)
if _raw_mqs < 1:
    print(
        f"WARNING: MAX_QUEUE_SIZE={_raw_mqs} below minimum 1, clamped to {MAX_QUEUE_SIZE}",
        file=sys.stderr,
    )

_raw_rsl = _safe_int("RECALL_SCAN_LIMIT", 10000)
RECALL_SCAN_LIMIT = max(1, _raw_rsl)
if _raw_rsl < 1:
    print(
        f"WARNING: RECALL_SCAN_LIMIT={_raw_rsl} below minimum 1, clamped to {RECALL_SCAN_LIMIT}",
        file=sys.stderr,
    )

_raw_hsw = _safe_float("HYBRID_SEARCH_TEXT_WEIGHT", 0.35)
_raw_tw = _safe_float("TEMPORAL_WEIGHT", 0.1)
_raw_hld = _safe_float("TEMPORAL_HALF_LIFE_DAYS", 30)
HYBRID_SEARCH_TEXT_WEIGHT = max(0.0, min(1.0, _raw_hsw))
TEMPORAL_WEIGHT = max(0.0, min(1.0, _raw_tw))
TEMPORAL_HALF_LIFE_DAYS = max(1.0, _raw_hld)
if not (0.0 <= _raw_hsw <= 1.0):
    print(
        f"WARNING: HYBRID_SEARCH_TEXT_WEIGHT={_raw_hsw} out of [0, 1], clamped to {HYBRID_SEARCH_TEXT_WEIGHT}",
        file=sys.stderr,
    )
if not (0.0 <= _raw_tw <= 1.0):
    print(
        f"WARNING: TEMPORAL_WEIGHT={_raw_tw} out of [0, 1], clamped to {TEMPORAL_WEIGHT}",
        file=sys.stderr,
    )
if _raw_hld < 1.0:
    print(
        f"WARNING: TEMPORAL_HALF_LIFE_DAYS={_raw_hld} below minimum 1.0, clamped to {TEMPORAL_HALF_LIFE_DAYS}",
        file=sys.stderr,
    )

CONSOLIDATION_ENABLED = os.environ.get("CONSOLIDATION_ENABLED", "0") == "1"
_raw_ct = _safe_float("CONSOLIDATION_THRESHOLD", 0.92)
CONSOLIDATION_THRESHOLD = max(0.0, min(1.0, _raw_ct))
if not (0.0 <= _raw_ct <= 1.0):
    print(
        f"WARNING: CONSOLIDATION_THRESHOLD={_raw_ct} out of [0, 1], clamped to {CONSOLIDATION_THRESHOLD}",
        file=sys.stderr,
    )

COMPACTION_ENABLED = os.environ.get("COMPACTION_ENABLED", "0") == "1"
_raw_cst = _safe_float("COMPACTION_SIMILARITY_THRESHOLD", 0.88)
COMPACTION_SIMILARITY_THRESHOLD = max(0.0, min(1.0, _raw_cst))
if not (0.0 <= _raw_cst <= 1.0):
    print(
        f"WARNING: COMPACTION_SIMILARITY_THRESHOLD={_raw_cst} out of [0, 1], clamped to {COMPACTION_SIMILARITY_THRESHOLD}",
        file=sys.stderr,
    )

_raw_ctc = _safe_int("COMPACTION_TRIGGER_COUNT", 5)
COMPACTION_TRIGGER_COUNT = max(1, _raw_ctc)
if _raw_ctc < 1:
    print(
        f"WARNING: COMPACTION_TRIGGER_COUNT={_raw_ctc} below minimum 1, clamped to {COMPACTION_TRIGGER_COUNT}",
        file=sys.stderr,
    )

_raw_cmcs = _safe_int("COMPACTION_MIN_CLUSTER_SIZE", 3)
COMPACTION_MIN_CLUSTER_SIZE = max(1, _raw_cmcs)
if _raw_cmcs < 1:
    print(
        f"WARNING: COMPACTION_MIN_CLUSTER_SIZE={_raw_cmcs} below minimum 1, clamped to {COMPACTION_MIN_CLUSTER_SIZE}",
        file=sys.stderr,
    )

_raw_cmah = _safe_int("COMPACTION_MIN_AGE_HOURS", 24)
COMPACTION_MIN_AGE_HOURS = max(0, _raw_cmah)
if _raw_cmah < 0:
    print(
        f"WARNING: COMPACTION_MIN_AGE_HOURS={_raw_cmah} below minimum 0, clamped to {COMPACTION_MIN_AGE_HOURS}",
        file=sys.stderr,
    )

_raw_casm = _safe_int("COMPACTION_ACTIVE_SESSION_GRACE_MINUTES", 15)
COMPACTION_ACTIVE_SESSION_GRACE_MINUTES = max(0, _raw_casm)
if _raw_casm < 0:
    print(
        f"WARNING: COMPACTION_ACTIVE_SESSION_GRACE_MINUTES={_raw_casm} below minimum 0, clamped to {COMPACTION_ACTIVE_SESSION_GRACE_MINUTES}",
        file=sys.stderr,
    )

_raw_csttl = _safe_int("COMPACTION_STAGING_TTL_HOURS", 168)
COMPACTION_STAGING_TTL_HOURS = max(1, _raw_csttl)
if _raw_csttl < 1:
    print(
        f"WARNING: COMPACTION_STAGING_TTL_HOURS={_raw_csttl} below minimum 1, clamped to {COMPACTION_STAGING_TTL_HOURS}",
        file=sys.stderr,
    )

COMPACTION_AUTO_APPLY_ENABLED = (
    os.environ.get("COMPACTION_AUTO_APPLY_ENABLED", "0") == "1"
)

_raw_caai = _safe_int("COMPACTION_AUTO_APPLY_INTERVAL_MINUTES", 60)
COMPACTION_AUTO_APPLY_INTERVAL_MINUTES = max(1, _raw_caai)
if _raw_caai < 1:
    print(
        f"WARNING: COMPACTION_AUTO_APPLY_INTERVAL_MINUTES={_raw_caai} below minimum 1, clamped to {COMPACTION_AUTO_APPLY_INTERVAL_MINUTES}",
        file=sys.stderr,
    )

_raw_cmn = _safe_int("COMPACTION_MAX_NUDGES", 5)
COMPACTION_MAX_NUDGES = max(1, _raw_cmn)
if _raw_cmn < 1:
    print(
        f"WARNING: COMPACTION_MAX_NUDGES={_raw_cmn} below minimum 1, clamped to {COMPACTION_MAX_NUDGES}",
        file=sys.stderr,
    )

_raw_cncs = _safe_int("COMPACTION_NUDGE_COOLDOWN_SECONDS", 2)
COMPACTION_NUDGE_COOLDOWN_SECONDS = max(0, _raw_cncs)
if _raw_cncs < 0:
    print(
        f"WARNING: COMPACTION_NUDGE_COOLDOWN_SECONDS={_raw_cncs} below minimum 0, clamped to {COMPACTION_NUDGE_COOLDOWN_SECONDS}",
        file=sys.stderr,
    )

_raw_cibb = _safe_int("COMPACTION_INJECTION_BYTE_BUDGET", 2048)
COMPACTION_INJECTION_BYTE_BUDGET = max(0, _raw_cibb)
if _raw_cibb < 0:
    print(
        f"WARNING: COMPACTION_INJECTION_BYTE_BUDGET={_raw_cibb} below minimum 0, clamped to {COMPACTION_INJECTION_BYTE_BUDGET}",
        file=sys.stderr,
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
