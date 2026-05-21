"""Notebook endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter
from datetime import datetime, timezone

from ..core.models import NotebookRequest
from ..core.memory import memory
from ..core.events import events

router = APIRouter(prefix="", tags=["Notebook"])


@router.post("/marm_notebook", operation_id="marm_notebook")
async def marm_notebook(request: NotebookRequest):
    """
    📔 Unified notebook — add, use, show, status, or clear

    action="add": save or update an entry (name + data required)
    action="use": activate entries as instructions (names required, comma-separated)
    action="show": list all saved entries with previews
    action="status": show currently active entries
    action="clear": clear the active entry list
    """
    try:
        if request.action == "add":
            if request.name is None or request.data is None:
                raise HTTPException(status_code=400, detail="name and data are required for action='add'")
            embedding_bytes = None
            if memory.encoder:
                try:
                    embedding = memory.encoder.encode(request.data)
                    embedding_bytes = embedding.tobytes()
                except Exception:
                    pass
            with memory.get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at) VALUES (?, ?, ?, ?)",
                    (request.name, request.data, embedding_bytes, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
            await events.emit("notebook_entry_added", {"name": request.name, "data": request.data})
            return {"status": "success", "message": f"📓 Notebook entry '{request.name}' added", "name": request.name}

        elif request.action == "use":
            if request.names is None:
                raise HTTPException(status_code=400, detail="names is required for action='use'")
            name_list = [n.strip() for n in request.names.split(",")]
            activated_entries = []
            with memory.get_connection() as conn:
                for name in name_list:
                    cursor = conn.execute("SELECT name, data FROM notebook_entries WHERE name = ?", (name,))
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

        elif request.action == "show":
            with memory.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT name, data, created_at, updated_at FROM notebook_entries ORDER BY updated_at DESC"
                )
                entries = []
                for row in cursor.fetchall():
                    preview = row[1][:100] + "..." if len(row[1]) > 100 else row[1]
                    entries.append({"name": row[0], "preview": preview, "created_at": row[2], "updated_at": row[3]})
            return {"status": "success", "message": f"📚 Found {len(entries)} notebook entries", "entries": entries, "total_count": len(entries)}

        elif request.action == "status":
            active_names = [entry["name"] for entry in memory.active_notebook_entries]
            return {
                "status": "success",
                "message": f"📊 {len(active_names)} active notebook entries",
                "active_entries": active_names,
                "entries": memory.active_notebook_entries,
                "active_count": len(active_names),
            }

        elif request.action == "clear":
            memory.active_notebook_entries = []
            return {"status": "success", "message": "🧹 Active notebook entries cleared", "active_count": 0}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Notebook operation failed: {str(e)}")
