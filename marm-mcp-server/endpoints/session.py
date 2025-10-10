"""Session endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter
import sqlite3
from datetime import datetime, timezone
from typing import Optional

# Import core components
from core.models import SessionRequest
from core.memory import memory
from core.events import events
from utils.helpers import read_protocol_file

# Create router for session endpoints
router = APIRouter(prefix="", tags=["MARM Protocol"])

@router.post("/marm_start", operation_id="marm_start")
async def marm_start(request: SessionRequest):
    """
    🚀 Activates MARM memory and accuracy layers
    
    Equivalent to /start marm command
    """
    try:
        with memory.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, marm_active, last_accessed)
                VALUES (?, TRUE, ?)
            ''', (request.session_name, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        
        # Read the current protocol from file
        protocol_content = await read_protocol_file()
        
        await events.emit('marm_started', {'session': request.session_name})
        
        return {
            "status": "success",
            "message": f"🚀 MARM protocol activated for session '{request.session_name}'",
            "session_name": request.session_name,
            "marm_active": True,
            "protocol_content": protocol_content,
            "instructions": "The complete MARM protocol documentation has been loaded and is available for reference."
        }
    except sqlite3.Error as e:
        print(f"Database error in marm_start: {e}")
        raise HTTPException(status_code=500, detail="Database error during MARM start.")
    except Exception as e:
        print(f"Unexpected error in marm_start: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during MARM start.")

@router.post("/marm_refresh", operation_id="marm_refresh")
async def marm_refresh(request: SessionRequest):
    """
    🔄 Refreshes active session state and reaffirms protocol adherence
    
    Equivalent to /refresh marm command
    """
    try:
        with memory.get_connection() as conn:
            conn.execute('''
                UPDATE sessions SET last_accessed = ? WHERE session_name = ?
            ''', (datetime.now(timezone.utc).isoformat(), request.session_name))
            conn.commit()
        
        # Read the current protocol from file to reaffirm adherence
        protocol_content = await read_protocol_file()
        
        await events.emit('marm_refreshed', {'session': request.session_name})
        
        return {
            "status": "success", 
            "message": f"🔄 MARM session '{request.session_name}' refreshed - protocol adherence reaffirmed",
            "session_name": request.session_name,
            "protocol_content": protocol_content,
            "instructions": "Protocol documentation refreshed. Please review the current MARM protocol specifications above."
        }
    except sqlite3.Error as e:
        print(f"Database error in marm_refresh: {e}")
        raise HTTPException(status_code=500, detail="Database error during MARM refresh.")
    except Exception as e:
        print(f"Unexpected error in marm_refresh: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during MARM refresh.")