"""Singleton supervisor for the embedded marm-graph code-structure engine.

Owns one marm_graph CbmClient for the process lifetime. Startup is lazy — the
first graph-tool call triggers it, not FastAPI lifespan — and never raises:
any failure (no network for the first-run binary download, disk full, schema
drift, GRAPH_ENABLED=false, ...) leaves is_available() False so core memory
tools are never affected. Mirrors marm-graph's own core/deps.py singleton.
"""

import threading
from typing import Optional

import structlog
from marm_graph.config import settings as graph_settings
from marm_graph.core import backend
from marm_graph.core.cbm_client import CbmClient

from ..config import settings as mcp_settings

logger = structlog.get_logger()


class GraphSupervisor:
    def __init__(self) -> None:
        self._client: Optional[CbmClient] = None
        self._available: bool = False
        self._start_attempted: bool = False
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        """Idempotent lazy start. Never raises — failures leave is_available() False."""
        if self._start_attempted:
            return
        with self._lock:
            if self._start_attempted:
                return
            self._start_attempted = True
            if not mcp_settings.GRAPH_ENABLED:
                logger.info("graph.disabled", reason="GRAPH_ENABLED=false")
                return
            self._log_first_run_download()
            client = CbmClient(
                command=graph_settings.cbm_spawn_command(),
                cwd=graph_settings.CBM_CWD,
                startup_timeout=graph_settings.CBM_STARTUP_TIMEOUT,
                call_timeout=graph_settings.CBM_CALL_TIMEOUT,
                client_name="marm-mcp-server",
            )
            try:
                backend.verify_and_start(client)
            except Exception as e:
                logger.warning("graph.backend_start_failed", error=str(e))
                return
            self._client = client
            self._available = True

    @staticmethod
    def _log_first_run_download() -> None:
        """Log a visible INFO line before the one-time binary download starts.

        Independent of the child's own stderr, which CbmClient._drain_stderr
        already routes to DEBUG — this is the user-visible signal instead.
        """
        try:
            from codebase_memory_mcp import _cli

            if not _cli._bin_path(_cli._version()).exists():
                logger.info("MARM: downloading graph engine (~269MB, one-time)...")
        except Exception:
            pass  # best-effort; must never block startup

    def is_available(self) -> bool:
        self._ensure_started()
        return self._available

    def get_client(self) -> Optional[CbmClient]:
        self._ensure_started()
        return self._client

    def stop(self) -> None:
        """Terminate the child process, if one was ever started."""
        if self._client is not None:
            self._client.close()
        self._client = None
        self._available = False
        self._start_attempted = False


graph_supervisor = GraphSupervisor()
