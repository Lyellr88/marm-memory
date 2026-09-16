import os
import shlex
import sys
from pathlib import Path
from typing import Optional

PINNED_CBM_VERSION = "0.10.5"


def _safe_int(env_key: str, default: int) -> int:
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


# ── HTTP server ────────────────────────────────────────────────────
SERVER_HOST = os.environ.get("SERVER_HOST", "127.0.0.1")
_raw_port = _safe_int("SERVER_PORT", 8003)
SERVER_PORT = max(1, min(65535, _raw_port))
if not (1 <= _raw_port <= 65535):
    print(
        f"WARNING: SERVER_PORT={_raw_port} out of [1, 65535], clamped to {SERVER_PORT}",
        file=sys.stderr,
    )

SERVER_VERSION = "0.1.0"

# ── Auth ───────────────────────────────────────────────────────────
MARM_GRAPH_API_KEY = os.environ.get("MARM_GRAPH_API_KEY", "")

# ── codebase-memory-mcp subprocess ─────────────────────────────────
CBM_BINARY_PATH = os.environ.get("CBM_BINARY_PATH", "")
_CBM_COMMAND_RAW = os.environ.get("CBM_COMMAND", "")


def cbm_spawn_command() -> list[str]:
    if CBM_BINARY_PATH:
        return [CBM_BINARY_PATH]
    if _CBM_COMMAND_RAW:
        return shlex.split(_CBM_COMMAND_RAW)
    return [sys.executable, "-m", "codebase_memory_mcp"]


def resolve_engine_binary() -> Optional[Path]:
    """Resolve the engine binary path, checking CBM_BINARY_PATH first, then
    CBM_COMMAND, then the pip-managed fallback location. Returns None when the
    binary cannot be found through any route."""
    if CBM_BINARY_PATH:
        path = Path(CBM_BINARY_PATH)
        if path.exists():
            return path
        return None
    if _CBM_COMMAND_RAW:
        cmd = shlex.split(_CBM_COMMAND_RAW)
        if cmd and Path(cmd[0]).exists():
            return Path(cmd[0])
        return None
    try:
        from codebase_memory_mcp import _cli

        path = _cli._bin_path(_cli._version())
        if path.exists():
            return path
    except Exception:
        pass
    return None


def engine_binary_details() -> dict:
    """Return diagnostic details about the engine binary resolution.

    Returns a dict with 'present' (bool), 'source' (str describing how the
    path was determined), 'path' (str or None), and 'configured_path_missing'
    (bool) — True only when CBM_BINARY_PATH is set but the target does not
    exist on disk.
    """
    result: dict = {
        "present": False,
        "source": "unresolved",
        "path": None,
        "configured_path_missing": False,
    }
    if CBM_BINARY_PATH:
        result["source"] = "CBM_BINARY_PATH"
        result["path"] = CBM_BINARY_PATH
        path = Path(CBM_BINARY_PATH)
        if path.exists():
            result["present"] = True
        else:
            result["configured_path_missing"] = True
        return result
    if _CBM_COMMAND_RAW:
        result["source"] = "CBM_COMMAND"
        cmd = shlex.split(_CBM_COMMAND_RAW)
        if cmd:
            result["path"] = cmd[0]
            if Path(cmd[0]).exists():
                result["present"] = True
        return result
    try:
        from codebase_memory_mcp import _cli

        bin_path = _cli._bin_path(_cli._version())
        result["source"] = "pip_managed"
        result["path"] = str(bin_path)
        if bin_path.exists():
            result["present"] = True
    except Exception:
        result["source"] = "pip_managed"
    return result


CBM_STARTUP_TIMEOUT = float(_safe_int("CBM_STARTUP_TIMEOUT", 60))
CBM_CALL_TIMEOUT = float(_safe_int("CBM_CALL_TIMEOUT", 300))

# ── Response bounding ──────────────────────────────────────────────
MAX_RESPONSE_BYTES = _safe_int("MARM_GRAPH_MAX_RESPONSE_BYTES", 900_000)

# ── Store location (informational) ─────────────────────────────────.
STORE_DIR = Path(
    os.environ.get("MARM_GRAPH_STORE_DIR", str(Path.home() / ".marm" / "graph"))
)

CBM_CWD = os.environ.get("CBM_CWD", "") or str(STORE_DIR)
