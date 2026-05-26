"""Tests for marm_mcp_server/core/shutdown_manager.py changes in this PR.

Covers:
- graceful_shutdown() calls memory.connection_pool.close_all()
- graceful_shutdown() catches exceptions from close_all() without re-raising
"""

import sys

import pytest


@pytest.fixture
def isolated_shutdown(monkeypatch, tmp_path):
    """Return a fresh ShutdownManager with a temporary DB."""
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            del sys.modules[name]

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "shutdown-test.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "shutdown-analytics.db"))

    from marm_mcp_server.core.shutdown_manager import ShutdownManager

    return ShutdownManager()


@pytest.mark.asyncio
async def test_graceful_shutdown_calls_connection_pool_close_all(monkeypatch, tmp_path):
    """Regression: graceful_shutdown must close the SQLite connection pool."""
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            del sys.modules[name]

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "sd-closeall.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "sd-closeall-analytics.db"))

    from marm_mcp_server.core.shutdown_manager import ShutdownManager
    from marm_mcp_server.core import memory as memory_mod

    close_all_called = []

    def fake_close_all():
        close_all_called.append(True)

    monkeypatch.setattr(memory_mod.memory.connection_pool, "close_all", fake_close_all)

    manager = ShutdownManager()
    await manager.graceful_shutdown()

    assert close_all_called == [True], (
        "graceful_shutdown() must call memory.connection_pool.close_all()"
    )


@pytest.mark.asyncio
async def test_graceful_shutdown_does_not_raise_when_close_all_fails(monkeypatch, tmp_path):
    """close_all() failure must be swallowed, not propagated as an exception."""
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            del sys.modules[name]

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "sd-exc.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "sd-exc-analytics.db"))

    from marm_mcp_server.core.shutdown_manager import ShutdownManager
    from marm_mcp_server.core import memory as memory_mod

    def exploding_close_all():
        raise RuntimeError("simulated pool failure")

    monkeypatch.setattr(memory_mod.memory.connection_pool, "close_all", exploding_close_all)

    manager = ShutdownManager()
    # Must not raise — the exception is caught internally
    await manager.graceful_shutdown()


@pytest.mark.asyncio
async def test_graceful_shutdown_closes_actual_pool(tmp_path, monkeypatch):
    """Integration: after graceful_shutdown the connection pool must be empty."""
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            del sys.modules[name]

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "sd-real.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "sd-real-analytics.db"))

    from marm_mcp_server.core.shutdown_manager import ShutdownManager
    from marm_mcp_server.core.memory import memory

    # Acquire then return a connection so the pool has at least one entry
    with memory.get_connection():
        pass

    assert not memory.connection_pool.pool.empty(), (
        "Pool should have a connection before shutdown"
    )

    manager = ShutdownManager()
    await manager.graceful_shutdown()

    assert memory.connection_pool.pool.empty(), (
        "Pool must be drained after graceful_shutdown()"
    )
