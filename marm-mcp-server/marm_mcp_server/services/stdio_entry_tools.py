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
    type: str,
    target: str,
    session_name: Optional[str],
    project: Optional[str] = None,
    platform: Optional[str] = None,
) -> dict:
    if type not in ("log", "notebook"):
        return {
            "status": "error",
            "message": f"Invalid type '{type}'. Must be 'log' or 'notebook'.",
        }
    return await delete_log_or_notebook_entry(
        type,
        target,
        session_name,
        project=project,
        platform=platform,
        scoped_notebook=project is not None or platform is not None,
        log_warning=_stdio_log.warning,
    )
