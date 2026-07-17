"""STDIO log-entry/notebook tool wrappers.

Thin transport-specific glue over services/log_entry.py's shared
business logic -- supplies STDIO's own logger (stderr +
~/.marm/logs/marm-stdio.log via _stdio_log) and STDIO's own
invalid-type error shape for marm_delete (a dict, not an HTTPException).
"""

from typing import Optional

from ..core.stdio_logging import _stdio_log
from .log_entry import create_log_entry, delete_log_or_notebook_entry, list_log_entries


async def create_log_entry_stdio(entry: str, session_name: Optional[str]) -> dict:
    return await create_log_entry(
        entry, session_name, log_info=_stdio_log.info, log_warning=_stdio_log.warning
    )


async def list_log_entries_stdio(session_name: Optional[str]) -> dict:
    return await list_log_entries(session_name, log_warning=_stdio_log.warning)


async def delete_entry_stdio(
    type: str, target: str, session_name: Optional[str]
) -> dict:
    if type not in ("log", "notebook"):
        return {
            "status": "error",
            "message": f"Invalid type '{type}'. Must be 'log' or 'notebook'.",
        }
    return await delete_log_or_notebook_entry(
        type, target, session_name, log_warning=_stdio_log.warning
    )
