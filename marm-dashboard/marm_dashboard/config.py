"""Dashboard configuration (aligned with marm-mcp-server auth rules)."""

import os
from pathlib import Path

_MARM_ENV_PATH = Path.home() / ".marm" / ".env"


def get_db_path() -> str:
    env_path = os.environ.get("MARM_DB_PATH")
    if env_path:
        Path(env_path).parent.mkdir(parents=True, exist_ok=True)
        return env_path

    marm_dir = Path.home() / ".marm"
    marm_dir.mkdir(exist_ok=True)
    return str(marm_dir / "marm_memory.db")


def _load_key_from_file() -> str:
    """Read MARM_API_KEY from ~/.marm/.env (same file MCP uses in Docker mode)."""
    try:
        for line in _MARM_ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("MARM_API_KEY=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


# Same env var as MCP. Env wins; then ~/.marm/.env so host dashboard matches Docker key file.
MARM_API_KEY = os.environ.get("MARM_API_KEY", "").strip()
if not MARM_API_KEY:
    MARM_API_KEY = _load_key_from_file()

DASHBOARD_HOST = os.environ.get("MARM_DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("MARM_DASHBOARD_PORT", "8002"))
