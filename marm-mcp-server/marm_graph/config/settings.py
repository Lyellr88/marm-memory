"""Configuration for marm-graph.

Mirrors marm-mcp-server's settings idiom (env-driven, safe parsing, loopback-safe
auth default). Adds the codebase-memory-mcp subprocess spawn/pin configuration.
"""

import os
import shlex
import sys
from pathlib import Path

# The exact upstream PyPI version this wrapper was validated against. The binary
# it downloads self-reports a DIFFERENT version (see protocol-proof.md §3); the
# schema contract is the binary's, captured live at startup.
PINNED_CBM_VERSION = "0.8.1"


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
# Bind loopback by default. Listening on any other interface requires an
# explicit SERVER_HOST override AND (per auth_middleware) an API key.
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
# When set, every non-public route (including all UI-only REST endpoints)
# requires `Authorization: Bearer <key>`. When unset, access is loopback-only.
MARM_GRAPH_API_KEY = os.environ.get("MARM_GRAPH_API_KEY", "")

# ── codebase-memory-mcp subprocess ─────────────────────────────────
# Spawn command resolution order:
#   1. CBM_BINARY_PATH  — absolute path to the baked static binary (Docker).
#   2. CBM_COMMAND      — full shell-style command override.
#   3. default          — run the installed PyPI shim with THIS interpreter,
#                         which downloads (first run) then execs the binary.
CBM_BINARY_PATH = os.environ.get("CBM_BINARY_PATH", "")
_CBM_COMMAND_RAW = os.environ.get("CBM_COMMAND", "")


def cbm_spawn_command() -> list[str]:
    if CBM_BINARY_PATH:
        return [CBM_BINARY_PATH]
    if _CBM_COMMAND_RAW:
        return shlex.split(_CBM_COMMAND_RAW)
    return [sys.executable, "-m", "codebase_memory_mcp"]


# Handshake / call timeouts (seconds).
CBM_STARTUP_TIMEOUT = float(_safe_int("CBM_STARTUP_TIMEOUT", 60))
CBM_CALL_TIMEOUT = float(_safe_int("CBM_CALL_TIMEOUT", 300))

# ── Response bounding ──────────────────────────────────────────────
# Defensive cap on marm-graph's own tool responses. Set below the MCP 1MB
# ceiling, not equal to it: transport wrappers serialize the bounded dict inside
# a content[0].text envelope, and that escaping (quotes, backslashes, unicode) can add
# several percent on top of the raw payload size. ~10% headroom keeps a
# just-under-cap response from crossing 1MB on the wire.
MAX_RESPONSE_BYTES = _safe_int("MARM_GRAPH_MAX_RESPONSE_BYTES", 900_000)

# ── Store location (informational) ─────────────────────────────────
# The wrapped binary owns all storage. Kept for logging/hardening checks.
# NOT created here: this module is imported at process-import time (including
# by marm-mcp-server's embedded graph_supervisor, even when GRAPH_ENABLED=false
# and no graph tool is ever called), so an invalid/unwritable
# MARM_GRAPH_STORE_DIR must not crash import. backend.verify_and_start()
# creates it lazily, right before the child actually needs it.
STORE_DIR = Path(
    os.environ.get("MARM_GRAPH_STORE_DIR", str(Path.home() / ".marm" / "graph"))
)

# Working directory for the child (repo_path args may be relative to it).
# Defaults to STORE_DIR, NOT the server's own CWD: if the server happened to
# be launched from a directory that is itself an indexed project, the binary's
# session-detection would derive a project from that CWD and silently start
# its own git watcher on it (mcp.c:5078-5158) — see auto-index-spec.md §2.
CBM_CWD = os.environ.get("CBM_CWD", "") or str(STORE_DIR)
