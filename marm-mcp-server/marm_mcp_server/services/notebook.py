"""Shared notebook action dispatcher for MARM MCP Server."""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from ..core.memory import memory
from ..core.events import events


async def _add(name: Optional[str], data: Optional[str], **_) -> dict:
    if not name or not name.strip() or not data or not data.strip():
        return {"status": "error", "message": "name and data are required for action='add'"}
    name = name.strip()
    embedding_bytes = None
    if memory.encoder:
        try:
            embedding = await asyncio.to_thread(memory._encode_sync, data)
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


async def _use(names: Optional[str], session_name: str = "main", **_) -> dict:
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
    memory.set_active_notebook_entries(session_name, activated_entries)
    return {
        "status": "success",
        "message": f"🔧 Activated {len(activated_entries)} notebook entries",
        "activated_entries": [e["name"] for e in activated_entries],
        "entries": activated_entries,
    }


async def _show(**_) -> dict:
    with memory.get_connection() as conn:
        cursor = conn.execute(
            "SELECT name, data, created_at, updated_at FROM notebook_entries ORDER BY updated_at DESC"
        )
        entries = []
        for row in cursor.fetchall():
            preview = row[1][:100] + "..." if len(row[1]) > 100 else row[1]
            entries.append({"name": row[0], "preview": preview, "created_at": row[2], "updated_at": row[3]})
    return {"status": "success", "message": f"📚 Found {len(entries)} notebook entries", "entries": entries, "total_count": len(entries)}


async def _status(session_name: str = "main", **_) -> dict:
    active_entries = memory.get_active_notebook_entries(session_name)
    active_names = [entry["name"] for entry in active_entries]
    return {
        "status": "success",
        "message": f"📊 {len(active_names)} active notebook entries",
        "active_entries": active_names,
        "entries": active_entries,
        "active_count": len(active_names),
    }


async def _clear(session_name: str = "main", **_) -> dict:
    memory.clear_active_notebook_entries(session_name)
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
    session_name: str = "main",
) -> dict:
    session_name = "main" if session_name is None else session_name.strip()
    if not session_name:
        return {"status": "error", "message": "session_name must be a non-empty string"}

    handler = _ACTION_HANDLERS.get(action)
    if handler is None:
        return {"status": "error", "message": f"Unknown action '{action}'. Must be: add, use, show, status, clear"}
    return await handler(name=name, data=data, names=names, session_name=session_name)
