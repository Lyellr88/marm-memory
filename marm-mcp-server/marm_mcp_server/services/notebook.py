"""Shared notebook action dispatcher for MARM MCP Server."""

from datetime import datetime, timezone
from typing import Optional

from ..core.memory import memory
from ..core.events import events


async def _add(name: Optional[str], data: Optional[str], **_) -> dict:
    """
    Add or replace a notebook entry in the database and emit a "notebook_entry_added" event.
    
    If an encoder is available, an embedding is generated and stored alongside the entry.
    
    Parameters:
        name (Optional[str]): The entry name; must be non-empty after trimming.
        data (Optional[str]): The entry content; must be non-empty after trimming.
    
    Returns:
        dict: On success, a dict with "status": "success", a human-readable "message", and "name" set to the stored entry name. On validation failure, a dict with "status": "error" and a "message" explaining the missing parameters.
    """
    if not name or not name.strip() or not data or not data.strip():
        return {"status": "error", "message": "name and data are required for action='add'"}
    name = name.strip()
    embedding_bytes = None
    if memory.encoder:
        try:
            embedding = memory.encoder.encode(data)
            embedding_bytes = embedding.tobytes()
        except Exception:
            pass
    with memory.get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at) VALUES (?, ?, ?, ?)",
            (name, data, embedding_bytes, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    await events.emit("notebook_entry_added", {"name": name, "data": data})
    return {"status": "success", "message": f"📓 Notebook entry '{name}' added", "name": name}


async def _use(names: Optional[str], **_) -> dict:
    """
    Activate notebook entries by name and store the selected entries in memory.
    
    Parameters:
        names (Optional[str]): Comma-separated notebook entry names to activate; whitespace around names is ignored.
    
    Returns:
        dict: On success, a dictionary with "status": "success", a human-readable "message", "activated_entries" (list of activated names), and "entries" (list of objects with "name" and "data"). If `names` is missing or contains no valid names, returns {"status": "error", "message": "..."}.
    """
    if not names or not names.strip():
        return {"status": "error", "message": "names is required for action='use'"}
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if not name_list:
        return {"status": "error", "message": "names is required for action='use'"}
    activated_entries = []
    with memory.get_connection() as conn:
        for n in name_list:
            cursor = conn.execute("SELECT name, data FROM notebook_entries WHERE name = ?", (n,))
            result = cursor.fetchone()
            if result:
                activated_entries.append({"name": result[0], "data": result[1]})
    memory.active_notebook_entries = activated_entries
    return {
        "status": "success",
        "message": f"🔧 Activated {len(activated_entries)} notebook entries",
        "activated_entries": [e["name"] for e in activated_entries],
        "entries": activated_entries,
    }


async def _show(**_) -> dict:
    """
    List stored notebook entries ordered by most recently updated, each with a truncated preview.
    
    Returns:
        result (dict): Contains:
            - "status" (str): Operation status, typically "success".
            - "message" (str): Human-readable summary including the number of found entries.
            - "entries" (List[dict]): List of entry objects with keys:
                - "name" (str): Entry name.
                - "preview" (str): Up to the first 100 characters of the entry's data, followed by "..." if truncated.
                - "created_at" (str): Creation timestamp.
                - "updated_at" (str): Last-update timestamp.
            - "total_count" (int): Number of entries returned.
    """
    with memory.get_connection() as conn:
        cursor = conn.execute(
            "SELECT name, data, created_at, updated_at FROM notebook_entries ORDER BY updated_at DESC"
        )
        entries = []
        for row in cursor.fetchall():
            preview = row[1][:100] + "..." if len(row[1]) > 100 else row[1]
            entries.append({"name": row[0], "preview": preview, "created_at": row[2], "updated_at": row[3]})
    return {"status": "success", "message": f"📚 Found {len(entries)} notebook entries", "entries": entries, "total_count": len(entries)}


async def _status(**_) -> dict:
    """
    Report currently active notebook entries held in memory.
    
    Returns:
        result (dict): A dictionary with:
            - status: "success".
            - message: Human-readable summary of how many entries are active.
            - active_entries: List of active entry names (strings).
            - entries: Full active notebook entry objects as stored in memory.
            - active_count: Integer count of active entries.
    """
    active_names = [entry["name"] for entry in memory.active_notebook_entries]
    return {
        "status": "success",
        "message": f"📊 {len(active_names)} active notebook entries",
        "active_entries": active_names,
        "entries": memory.active_notebook_entries,
        "active_count": len(active_names),
    }


async def _clear(**_) -> dict:
    """
    Clear all active notebook entries stored in memory.
    
    Returns:
        result (dict): Operation result with keys:
            - "status": "success"
            - "message": human-readable confirmation
            - "active_count": 0
    """
    memory.active_notebook_entries = []
    return {"status": "success", "message": "🧹 Active notebook entries cleared", "active_count": 0}


_ACTION_HANDLERS = {
    "add": _add,
    "use": _use,
    "show": _show,
    "status": _status,
    "clear": _clear,
}


async def notebook_dispatch(
    action: str,
    name: Optional[str] = None,
    data: Optional[str] = None,
    names: Optional[str] = None,
) -> dict:
    """
    Dispatches a notebook action to the corresponding handler.
    
    Parameters:
        action (str): The action to perform. Valid values are "add", "use", "show", "status", and "clear".
        name (Optional[str]): Optional single entry name used by handlers that accept `name`.
        data (Optional[str]): Optional entry data used by handlers that accept `data`.
        names (Optional[str]): Optional comma-separated names string used by handlers that accept `names`.
    
    Returns:
        dict: The result returned by the invoked handler. If `action` is not one of the valid values, returns an error dict with `"status": "error"` and a descriptive `"message"`.
    """
    handler = _ACTION_HANDLERS.get(action)
    if handler is None:
        return {"status": "error", "message": f"Unknown action '{action}'. Must be: add, use, show, status, clear"}
    return await handler(name=name, data=data, names=names)
