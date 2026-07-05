"""Shared fixtures. Integration tests use the REAL codebase-memory-mcp binary.

If the binary can't be resolved (not downloaded / offline CI), integration tests
skip cleanly — a genuinely-unavailable dependency, per the project's skip-guard
policy. Pure-logic tests run regardless.
"""

import os
import sys
from pathlib import Path

import pytest

_PKG_ROOT = Path(__file__).resolve().parents[1]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

# Auth tests need a key set before settings is imported.
os.environ.setdefault("MARM_GRAPH_API_KEY", "testkey")


def _resolve_binary() -> str | None:
    env = os.environ.get("CBM_BINARY_PATH")
    if env and os.path.exists(env):
        return env
    try:
        from codebase_memory_mcp import _cli

        bp = _cli._bin_path(_cli._version())
        if bp.exists():
            return str(bp)
    except Exception:
        pass
    return None


_BINARY = _resolve_binary()
if _BINARY:
    os.environ.setdefault("CBM_BINARY_PATH", _BINARY)

requires_binary = pytest.mark.skipif(
    _BINARY is None,
    reason="codebase-memory-mcp binary not available (offline / not downloaded)",
)


@pytest.fixture(scope="session")
def binary() -> str:
    if _BINARY is None:
        pytest.skip("binary unavailable")
    return _BINARY


@pytest.fixture(scope="session")
def client(binary):
    from marm_graph.core.cbm_client import CbmClient

    c = CbmClient(command=[binary], startup_timeout=90, call_timeout=180)
    c.start()
    yield c
    c.close()


@pytest.fixture(scope="session")
def project(client) -> str:
    """Index this package's own source and return the derived project name."""
    result = client.call_tool(
        "index_repository", {"repo_path": str(_PKG_ROOT), "mode": "moderate"}
    )
    name = result.get("project")
    assert name, f"index_repository returned no project name: {result}"
    return name
