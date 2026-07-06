"""Shared CbmClient singleton.

One long-lived child process serves the whole server (many indexed projects,
one subprocess — matching the binary's own cached-project model). Lifespan
starts and closes it; endpoints fetch it via get_client().
"""

from __future__ import annotations

from typing import Optional

from ..config import settings
from .cbm_client import CbmClient

_client: Optional[CbmClient] = None


def get_client() -> CbmClient:
    global _client
    if _client is None:
        _client = CbmClient(
            command=settings.cbm_spawn_command(),
            cwd=settings.CBM_CWD,
            startup_timeout=settings.CBM_STARTUP_TIMEOUT,
            call_timeout=settings.CBM_CALL_TIMEOUT,
            client_version=settings.SERVER_VERSION,
        )
    return _client


def reset_client() -> None:
    """Close and drop the singleton (used by tests and shutdown)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
