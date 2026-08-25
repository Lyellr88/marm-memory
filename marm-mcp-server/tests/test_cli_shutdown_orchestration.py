import asyncio

import pytest
import uvicorn

from marm_mcp_server.cli import run_server_with_shutdown
from marm_mcp_server.core.shutdown_manager import ShutdownManager, shutdown_manager


class _SimulatedStartupCrash(RuntimeError):
    pass


def test_server_task_crash_propagates_instead_of_silent_exit(monkeypatch):
    """Old code only handled the `shutdown_task in done` branch of the
    asyncio.wait race. If server_task completed first instead (e.g. uvicorn
    crashes on startup with a port conflict), that branch was skipped
    entirely: shutdown_task was left pending forever and server_task's
    exception was never awaited/observed, so the process would exit 0
    instead of surfacing the startup failure.

    Real orchestration under test -- only uvicorn's socket binding is
    stubbed (to avoid a real port conflict/bind in CI), and signal-handler
    registration is stubbed (module-level ShutdownManager singleton
    shouldn't register process signal handlers repeatedly across the test
    session). asyncio.wait, task cancellation, and exception propagation
    are all real.
    """
    shutdown_manager.shutdown_event = asyncio.Event()
    shutdown_manager.shutdown_initiated = False

    async def _crashing_serve(self):
        raise _SimulatedStartupCrash("simulated uvicorn startup crash")

    monkeypatch.setattr(uvicorn.Server, "serve", _crashing_serve)

    async def _noop_signal_handlers(self):
        return None

    monkeypatch.setattr(ShutdownManager, "setup_signal_handlers", _noop_signal_handlers)

    with pytest.raises(_SimulatedStartupCrash):
        asyncio.run(run_server_with_shutdown())
