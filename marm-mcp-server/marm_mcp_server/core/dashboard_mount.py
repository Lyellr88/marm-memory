"""Optional marm-dashboard sub-app mount for the unified Docker image.

`marm-dashboard` is a docker-only extra (see pyproject.toml's `docker-image`
optional-dependencies group) — plain `pip install marm-mcp-server` never has
it installed. `get_dashboard_app()` returns None in that case so `server.py`
can skip the mount entirely instead of crashing on import.
"""

from typing import Optional

from fastapi import FastAPI


def get_dashboard_app() -> Optional[FastAPI]:
    try:
        from marm_dashboard.server import app as dashboard_app

        return dashboard_app
    except ImportError:
        return None  # not installed in this build variant
