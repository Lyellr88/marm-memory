"""Notebook endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter
from datetime import datetime, timezone

# Import core components
from ..core.models import NotebookAddRequest, NotebookUseRequest
from ..core.memory import memory
from ..core.events import events

# Create router for notebook endpoints
router = APIRouter(prefix="", tags=["Notebook"])

@router.post("/marm_notebook_add", operation_id="marm_notebook_add")
async def marm_notebook_add(request: NotebookAddRequest):
    """
    📓 Add a new entry
    
    Equivalent to /notebook add: [name] [data] command
    """
    try:
        # Generate embedding if available
        embedding_bytes = None
        if memory.encoder:
            try:
                embedding = memory.encoder.encode(request.data)
                embedding_bytes = embedding.tobytes()
            except Exception as e:
                print(f"Failed to generate embedding: {e}")
        
        with memory.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (request.name, request.data, embedding_bytes, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        
        await events.emit('notebook_entry_added', {
            'name': request.name,
            'data': request.data
        })
        
        return {
            "status": "success",
            "message": f"📓 Notebook entry '{request.name}' added",
            "name": request.name
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add notebook entry: {str(e)}")

@router.post("/marm_notebook_use", operation_id="marm_notebook_use")
async def marm_notebook_use(request: NotebookUseRequest):
    """
    🔧 Activate entries as instructions
    
    Equivalent to /notebook use: [name1,name2] command
    """
    try:
        names = [n.strip() for n in request.names.split(',')]
        activated_entries = []
        
        with memory.get_connection() as conn:
            for name in names:
                cursor = conn.execute('SELECT name, data FROM notebook_entries WHERE name = ?', (name,))
                result = cursor.fetchone()
                if result:
                    activated_entries.append({"name": result[0], "data": result[1]})
        
        # Update active list in memory
        memory.active_notebook_entries = activated_entries
        
        return {
            "status": "success",
            "message": f"🔧 Activated {len(activated_entries)} notebook entries",
            "activated_entries": [e["name"] for e in activated_entries],
            "entries": activated_entries
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to activate notebook entries: {str(e)}")

@router.get("/marm_notebook_show", operation_id="marm_notebook_show")
async def marm_notebook_show():
    """
    📚 Display all saved keys and summaries
    
    Equivalent to /notebook show: command
    """
    try:
        with memory.get_connection() as conn:
            cursor = conn.execute('''
                SELECT name, data, created_at, updated_at 
                FROM notebook_entries 
                ORDER BY updated_at DESC
            ''')
            
            entries = []
            for row in cursor.fetchall():
                preview = row[1][:100] + "..." if len(row[1]) > 100 else row[1]
                entries.append({
                    "name": row[0],
                    "preview": preview,
                    "created_at": row[2],
                    "updated_at": row[3]
                })
        
        return {
            "status": "success",
            "message": f"📚 Found {len(entries)} notebook entries",
            "entries": entries,
            "total_count": len(entries)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to show notebook entries: {str(e)}")

@router.delete("/marm_notebook_clear", operation_id="marm_notebook_clear")
async def marm_notebook_clear():
    """
    🧹 Clear the active list
    
    Equivalent to /notebook clear: command
    """
    try:
        memory.active_notebook_entries = []
        
        return {
            "status": "success",
            "message": "🧹 Active notebook entries cleared",
            "active_count": 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear active entries: {str(e)}")

@router.get("/marm_notebook_status", operation_id="marm_notebook_status")
async def marm_notebook_status():
    """
    📊 Show the current active list
    
    Equivalent to /notebook status: command
    """
    try:
        active_names = [entry["name"] for entry in memory.active_notebook_entries]
        
        return {
            "status": "success",
            "message": f"📊 {len(active_names)} active notebook entries",
            "active_entries": active_names,
            "entries": memory.active_notebook_entries,
            "active_count": len(active_names)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get notebook status: {str(e)}")
