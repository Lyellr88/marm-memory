"""Optional marm-dashboard sub-app mount for the unified server.

The dashboard package is bundled with marm-mcp-server. `get_dashboard_app()`
still degrades to None on import failure so a dashboard issue cannot take down
the memory/graph MCP server.
"""

from typing import Optional

import structlog
from fastapi import FastAPI

logger = structlog.get_logger()


def get_dashboard_app() -> Optional[FastAPI]:
    try:
        from marm_dashboard.server import app as dashboard_app

        return dashboard_app
    except ImportError:
        return None  # not installed in this build variant
    except Exception as e:
        # Any other import-time failure (bad config, unwritable DB path, etc.)
        # must not take memory/graph down with it -- same degrade-not-crash
        # posture as graph_supervisor's own failure handling.
        logger.warning("dashboard.mount_failed", error=str(e))
        return None
