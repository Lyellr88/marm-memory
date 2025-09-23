"""Logging endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter, Query
import sqlite3
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict

# Import core components
from core.models import SessionRequest, LogEntryRequest
from core.memory import memory
from core.events import events
from endpoints.system import marm_current_context

# Create router for logging endpoints
router = APIRouter(prefix="", tags=["Logging"])

@router.post("/marm_log_session", operation_id="marm_log_session")
async def marm_log_session(request: SessionRequest):
    """
    📂 Create or switch to named session container
    
    Equivalent to /log session: [name] command
    """
    try:
        # Get current context from marm_current_context background tool
        context_info = await marm_current_context()
        current_timestamp = datetime.now(timezone.utc).isoformat()

        with memory.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
            ''', (request.session_name, current_timestamp))
            conn.commit()
        
        await events.emit('session_created', {'session': request.session_name})
        
        return {
            "status": "success",
            "message": f"📂 Session '{request.session_name}' created/activated",
            "session_name": request.session_name
        }
    except sqlite3.Error as e:
        print(f"Database error in marm_log_session: {e}")
        raise HTTPException(status_code=500, detail="Database error during session creation.")
    except Exception as e:
        print(f"Unexpected error in marm_log_session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during session creation.")

@router.post("/marm_log_entry", operation_id="marm_log_entry")
async def marm_log_entry(request: LogEntryRequest):
    """
    📝 Add structured log entry for milestones or decisions
    
    Equivalent to /log entry: [YYYY-MM-DD-topic-summary] command
    """
    try:
        # Store user entry exactly as provided - no auto-date formatting
        formatted_entry = request.entry.strip()

        # Parse entry for database storage (optional date extraction)
        entry_pattern = r'^(\d{4}-\d{2}-\d{2})-(.*?)-(.*?)$'
        match = re.match(entry_pattern, formatted_entry)

        if match:
            # Entry has date format - extract components
            entry_date, topic, summary = match.groups()
        else:
            # Entry has no date - store as-is with null date
            entry_date = None
            topic = "general"
            summary = formatted_entry
        
        entry_id = str(uuid.uuid4())
        with memory.get_connection() as conn:
            conn.execute('''
                INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (entry_id, request.session_name, entry_date, topic, summary, formatted_entry))
            conn.commit()
        
        await events.emit('log_entry_created', {
            'entry_id': entry_id,
            'session': request.session_name,
            'content': formatted_entry
        })
        
        return {
            "status": "success",
            "message": f"📝 Log entry added: {formatted_entry}",
            "entry_id": entry_id,
            "formatted_entry": formatted_entry
        }
    except sqlite3.Error as e:
        print(f"Database error in marm_log_entry: {e}")
        raise HTTPException(status_code=500, detail="Database error while creating log entry.")
    except Exception as e:
        print(f"Unexpected error in marm_log_entry: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while creating log entry.")

@router.get("/marm_log_show", operation_id="marm_log_show")
async def marm_log_show(
    session_name: Optional[str] = Query(None, description="Session to show logs for. If omitted, lists all sessions.")
):
    """
    📋 Display all entries and sessions logged
    
    Equivalent to /log show: [session] command
    """
    try:
        with memory.get_connection() as conn:
            if session_name:
                cursor = conn.execute('''
                    SELECT id, entry_date, topic, summary, full_entry
                    FROM log_entries WHERE session_name = ?
                    ORDER BY entry_date DESC
                ''', (session_name,))
                entries = [{"id": r[0], "entry_date": r[1], "topic": r[2], 
                          "summary": r[3], "full_entry": r[4]} for r in cursor.fetchall()]
                
                return {
                    "status": "success",
                    "session_name": session_name,
                    "entries": entries,
                    "total_entries": len(entries)
                }
            else:
                cursor = conn.execute('SELECT session_name, COUNT(*) FROM log_entries GROUP BY session_name')
                sessions = [{"session_name": r[0], "entry_count": r[1]} for r in cursor.fetchall()]
                
                return {
                    "status": "success",
                    "sessions": sessions,
                    "total_sessions": len(sessions)
                }
    except sqlite3.Error as e:
        print(f"Database error in marm_log_show: {e}")
        raise HTTPException(status_code=500, detail="Database error while showing logs.")
    except Exception as e:
        print(f"Unexpected error in marm_log_show: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while showing logs.")

@router.delete("/marm_log_delete", operation_id="marm_log_delete")
async def marm_log_delete(
    target: str = Query(..., description="The ID or topic of the entry to delete, or the session name to delete."),
    session_name: Optional[str] = Query(None, description="The session to delete from. If omitted, 'target' is assumed to be a session name.")
):
    """
    🗑️ Delete specified session or entry
    
    Equivalent to /log delete: [session/entry name] command
    """
    try:
        with memory.get_connection() as conn:
            if session_name:
                # Delete specific entry from session
                cursor = conn.execute('''
                    DELETE FROM log_entries 
                    WHERE session_name = ? AND (id = ? OR topic = ?)
                ''', (session_name, target, target))
                deleted = cursor.rowcount
            else:
                # Delete entire session
                conn.execute('DELETE FROM sessions WHERE session_name = ?', (target,))
                cursor = conn.execute('DELETE FROM log_entries WHERE session_name = ?', (target,))
                deleted = cursor.rowcount
            
            conn.commit()
            
            return {
                "status": "success",
                "message": f"🗑️ Deleted {deleted} items",
                "deleted_count": deleted
            }
    except sqlite3.Error as e:
        print(f"Database error in marm_log_delete: {e}")
        raise HTTPException(status_code=500, detail="Database error while deleting.")
    except Exception as e:
        print(f"Unexpected error in marm_log_delete: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while deleting.")
