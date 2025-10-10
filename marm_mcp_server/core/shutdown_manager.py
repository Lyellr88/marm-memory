"""Graceful shutdown manager for MARM MCP Server."""

import signal
import asyncio
import structlog
from typing import Set
from core.websocket_manager import websocket_manager

logger = structlog.get_logger()

class ShutdownManager:
    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.shutdown_initiated = False

    async def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        try:
            # Setup signal handlers for Unix systems
            loop = asyncio.get_event_loop()

            for sig in [signal.SIGTERM, signal.SIGINT]:
                loop.add_signal_handler(sig, self._signal_handler, sig)

            logger.info("Signal handlers configured for graceful shutdown")

        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            logger.info("Signal handlers not available on this platform")
            pass

    def _signal_handler(self, sig):
        """Handle shutdown signals"""
        logger.info("Shutdown signal received", signal=sig.name)

        if not self.shutdown_initiated:
            self.shutdown_initiated = True
            self.shutdown_event.set()

    async def wait_for_shutdown(self):
        """Wait for shutdown signal"""
        await self.shutdown_event.wait()

    async def graceful_shutdown(self):
        """Perform graceful shutdown of all connections and services"""
        logger.info("Initiating graceful shutdown")

        # Close all WebSocket connections
        connection_count = websocket_manager.get_connection_count()
        if connection_count > 0:
            logger.info("Closing WebSocket connections", count=connection_count)

            # Use the WebSocket manager's shutdown method
            await websocket_manager.shutdown_all_connections()

            # Wait a moment for connections to close cleanly
            await asyncio.sleep(1)

            logger.info("All WebSocket connections closed")

        logger.info("Graceful shutdown complete")

# Global shutdown manager instance
shutdown_manager = ShutdownManager()