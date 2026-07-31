import asyncio
import signal

import structlog

from ..config.settings import CHUNK_DRAIN_TIMEOUT_SECONDS
from .graph_supervisor import graph_supervisor
from .memory import memory
from .memory_utils import drain_chunk_writes

logger = structlog.get_logger()


class ShutdownManager:
    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.shutdown_initiated = False
        self._cleanup_complete = False

    async def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        try:
            loop = asyncio.get_event_loop()

            for sig in [signal.SIGTERM, signal.SIGINT]:
                loop.add_signal_handler(sig, self._signal_handler, sig)

            logger.info("Signal handlers configured for graceful shutdown")

        except NotImplementedError:
            logger.info("Signal handlers not available on this platform")
            pass

    def _signal_handler(self, sig):
        """Handle shutdown signals"""
        logger.info("Shutdown signal received", signal=sig.name)

        if not self.shutdown_initiated:
            self.shutdown_initiated = True
            self.shutdown_event.set()

    def request_shutdown(self) -> None:
        """Request the same graceful path used by process signals."""
        if not self.shutdown_initiated:
            self.shutdown_initiated = True
            self.shutdown_event.set()

    async def wait_for_shutdown(self):
        """Wait for shutdown signal"""
        await self.shutdown_event.wait()

    async def graceful_shutdown(self):
        """Perform graceful shutdown of all connections and services"""
        if self._cleanup_complete:
            return
        self._cleanup_complete = True
        logger.info("Initiating graceful shutdown")

        try:
            pending_scans = list(memory._pending_compaction_scans.values())
            for task in pending_scans:
                if not task.done():
                    task.cancel()
            if pending_scans:
                await asyncio.gather(*pending_scans, return_exceptions=True)
            memory._pending_compaction_scans.clear()
        except Exception:
            logger.exception("Failed to cancel pending compaction scans")

        try:
            await memory.stop_write_queue()
            logger.info("Serialized write queue drained")
        except Exception:
            logger.exception("Failed to drain serialized write queue")

        # Must follow the write-queue stop: draining the queue runs the remaining
        # writes, and a long one spawns a chunk task, so a drain taken before this
        # point can miss tasks that do not exist yet. Must precede the pool close:
        # a chunk task holding BEGIN IMMEDIATE would otherwise race teardown.
        try:
            await drain_chunk_writes(memory, CHUNK_DRAIN_TIMEOUT_SECONDS, logger.info)
        except Exception:
            logger.exception("Failed to drain pending chunk writes")

        try:
            await asyncio.to_thread(graph_supervisor.stop)
            logger.info("Graph child stopped")
        except Exception:
            logger.exception("Failed to stop graph child")

        try:
            memory.connection_pool.close_all()
            logger.info("SQLite connection pool closed")
        except Exception:
            logger.exception("Failed to close SQLite connection pool")

        logger.info("Graceful shutdown complete")


shutdown_manager = ShutdownManager()
