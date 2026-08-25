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
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = "not_started"
        self._ready = threading.Event()
        self._stopped = False

    def _ensure_started(self) -> None:
        """Idempotent lazy start. Never raises — failures leave is_available() False."""
        if self._ready.is_set() or self._stopped:
            return
        with self._lock:
            if self._ready.is_set() or self._stopped:
                return
            try:
                with self._state_lock:
                    self._state = "starting"
                if not mcp_settings.GRAPH_ENABLED:
                    logger.info("graph.disabled", reason="GRAPH_ENABLED=false")
                    with self._state_lock:
                        self._state = "disabled"
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
                    try:
                        client.close()
                    except Exception:
                        pass
                    with self._state_lock:
                        self._state = "error"
                    return
                with self._state_lock:
                    self._client = client
                    self._available = True
                    self._state = "ready"
            except Exception as e:
                logger.warning("graph.start_failed", error=str(e))
                with self._state_lock:
                    self._state = "error"
            finally:
                self._ready.set()

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
            pass

    def is_available(self) -> bool:
        self._ensure_started()
        return self._available

    def snapshot(self) -> dict:
        """Return process-local graph state without starting the child."""
        with self._state_lock:
            return {
                "state": "disabled" if not mcp_settings.GRAPH_ENABLED else self._state,
                "enabled": mcp_settings.GRAPH_ENABLED,
                "started": self._client is not None,
                "available": self._available,
            }

    def get_client(self) -> Optional[CbmClient]:
        """The client, but only while the supervisor still owns it.

        _available and _client are read together under _state_lock. Callers used
        to gate on a separate is_available() call, which leaves a window for
        stop() to complete in between and hand back None to code that has
        already decided the backend is up.
        """
        self._ensure_started()
        with self._state_lock:
            return self._client if self._available else None

    def stop(self) -> None:
        """Terminate the child process, if one was ever started.

        Must share _lock with _ensure_started(): without it, a stop() racing
        an in-flight lazy startup could interleave with that critical section
        and leave _ready set + _available True but _client None -- a caller's
        get_client() would then return None while is_available() just said
        the backend was up.
        """
        with self._lock:
            with self._state_lock:
                self._state = "stopping"
            try:
                if self._client is not None:
                    self._client.close()
            finally:
                with self._state_lock:
                    self._client = None
                    self._available = False
                    self._state = "not_started"
                self._stopped = True
                self._ready.clear()


graph_supervisor = GraphSupervisor()
