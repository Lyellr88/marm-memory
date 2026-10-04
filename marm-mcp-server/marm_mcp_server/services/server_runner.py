from __future__ import annotations

import asyncio

import structlog
import uvicorn

from ..config.settings import SERVER_HOST, SERVER_PORT

logger = structlog.get_logger()


async def run_server_with_shutdown() -> None:
    """Run the HTTP server with MARM's shared graceful-shutdown path."""
    from ..core.shutdown_manager import shutdown_manager
    from ..server import app

    shutdown_manager.shutdown_event = asyncio.Event()
    shutdown_manager.shutdown_initiated = False
    shutdown_manager._cleanup_complete = False
    await shutdown_manager.setup_signal_handlers()
    server = uvicorn.Server(
        uvicorn.Config(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info")
    )
    server_task = asyncio.create_task(server.serve())
    shutdown_task = asyncio.create_task(shutdown_manager.wait_for_shutdown())
    done, _pending = await asyncio.wait(
        [server_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
    )
    graceful_shutdown_signaled = shutdown_task in done
    if graceful_shutdown_signaled:
        logger.info("Shutdown signal received, closing server")
        server.should_exit = True
        await server_task
    for task in (shutdown_task,):
        if task.done():
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if server_task in done and not graceful_shutdown_signaled:
        await server_task
    if graceful_shutdown_signaled:
        logger.info("Server shutdown complete")
