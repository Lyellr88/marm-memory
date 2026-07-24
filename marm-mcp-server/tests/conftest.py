"""Test helpers for isolated MARM server imports."""

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _resolve_cbm_binary() -> str | None:
    env = os.environ.get("CBM_BINARY_PATH")
    if env and os.path.exists(env):
        return env
    try:
        from codebase_memory_mcp import _cli

        binary_path = _cli._bin_path(_cli._version())
        if binary_path.exists():
            return str(binary_path)
    except Exception:
        pass
    return None


_CBM_BINARY = _resolve_cbm_binary()
if _CBM_BINARY:
    os.environ.setdefault("CBM_BINARY_PATH", _CBM_BINARY)

requires_binary = pytest.mark.skipif(
    _CBM_BINARY is None,
    reason="codebase-memory-mcp binary not available (offline / not downloaded)",
)


def pytest_collection_modifyitems(items):
    opt_in_markers = {
        "smoke_docker": "MARM_SMOKE_DOCKER",
        "smoke_destructive": "MARM_SMOKE_DESTRUCTIVE",
    }
    for item in items:
        for marker, environment_name in opt_in_markers.items():
            if (
                item.get_closest_marker(marker)
                and os.environ.get(environment_name) != "1"
            ):
                item.add_marker(
                    pytest.mark.skip(reason=f"{marker} requires {environment_name}=1")
                )


@pytest.fixture(autouse=True, scope="session")
def isolated_cbm_store(tmp_path_factory):
    """Keep test indexes out of the developer's real code graph.

    The binary stores each project in ~/.cache/codebase-memory-mcp regardless
    of MARM_GRAPH_STORE_DIR, so any test that reaches index_repository used to
    add a permanent entry to the machine's real project list. It resolves that
    directory from HOME (POSIX) or USERPROFILE (Windows), both verified to
    redirect it, so pointing them at a session temp directory isolates the
    store without changing how the child is invoked.
    """
    sandbox = tmp_path_factory.mktemp("cbm-home")
    previous = {name: os.environ.get(name) for name in ("HOME", "USERPROFILE")}
    for name in previous:
        os.environ[name] = str(sandbox)
    yield sandbox
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def load_isolated_server(monkeypatch, tmp_path, api_key="", write_queue_enabled=False):
    """Import the server after pointing global state at a temporary database.

    Modules are dropped via monkeypatch.delitem, not a bare del, so the original
    module objects are restored at teardown. Otherwise the isolated re-import
    below leaves a new module generation in sys.modules for the rest of the
    session, and later tests that bound symbols (e.g. MARMMemory) at import time
    would silently reference the stale generation.
    """
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            monkeypatch.delitem(sys.modules, name)

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "marm_memory.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("WRITE_QUEUE_ENABLED", "1" if write_queue_enabled else "0")
    if api_key:
        monkeypatch.setenv("MARM_API_KEY", api_key)
    else:
        monkeypatch.delenv("MARM_API_KEY", raising=False)

    server = importlib.import_module("marm_mcp_server.server")

    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    monkeypatch.setattr(memory_module.memory, "_encoder_failed", True)
    monkeypatch.setattr(memory_module.memory, "active_notebook_entries_by_session", {})
    monkeypatch.setattr(memory_module.memory, "active_log_session", "main")

    rate_limiter_module = importlib.import_module("marm_mcp_server.core.rate_limiter")
    rate_limiter_module.rate_limiter.request_buckets.clear()
    rate_limiter_module.rate_limiter.blocked_ips.clear()

    return server


def local_client(app):
    return TestClient(app, client=("127.0.0.1", 50000))


def remote_client(app):
    return TestClient(app, client=("10.0.0.25", 50000))


@pytest.fixture(scope="session")
def binary() -> str:
    if _CBM_BINARY is None:
        pytest.skip("binary unavailable")
    return _CBM_BINARY


@pytest.fixture(scope="session")
def graph_client(binary):
    from marm_graph.core.cbm_client import CbmClient
    from marm_graph.config import settings as graph_settings

    graph_settings.STORE_DIR.mkdir(parents=True, exist_ok=True)
    client = CbmClient(
        command=[binary],
        cwd=graph_settings.CBM_CWD,
        startup_timeout=90,
        call_timeout=180,
    )
    client.start()
    yield client
    client.close()


@pytest.fixture(scope="session")
def graph_project(graph_client) -> str:
    """Index the packaged marm_graph source and return the derived project name."""
    package_root = Path(__file__).resolve().parents[1] / "marm_graph"
    result = graph_client.call_tool(
        "index_repository", {"repo_path": str(package_root), "mode": "moderate"}
    )
    name = result.get("project")
    assert name, f"index_repository returned no project name: {result}"
    return name


@pytest.fixture(scope="session")
def client(graph_client):
    """Compatibility alias for tests moved from the standalone marm-graph suite."""
    return graph_client


@pytest.fixture(scope="session")
def project(graph_project):
    """Compatibility alias for tests moved from the standalone marm-graph suite."""
    return graph_project
