"""Usage analytics tracking for MARM MCP Server."""

import sqlite3
from datetime import datetime

import structlog

from ..config.settings import ANALYTICS_DB_PATH

logger = structlog.get_logger()


def track_usage(event_type: str, endpoint: str = None, user_data: dict = None):
    """Track MCP usage events for launch analytics"""
    try:
        usage_db = ANALYTICS_DB_PATH

        with sqlite3.connect(usage_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    endpoint TEXT,
                    user_agent TEXT,
                    ip_address TEXT,
                    session_id TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute(
                """
                INSERT INTO usage_events (timestamp, event_type, endpoint, user_agent, ip_address, session_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    datetime.now().isoformat(),
                    event_type,
                    endpoint,
                    user_data.get("user_agent", "unknown") if user_data else "unknown",
                    user_data.get("ip_address", "unknown") if user_data else "unknown",
                    user_data.get("session_id", "unknown") if user_data else "unknown",
                    str(user_data) if user_data else "{}",
                ),
            )

        logger.info("Usage tracked", event_type=event_type, endpoint=endpoint)
    except Exception as e:
        logger.warning("Analytics tracking failed", error=str(e))
