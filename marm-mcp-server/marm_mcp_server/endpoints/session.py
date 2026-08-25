import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..core.events import events
from ..core.memory import memory
from ..core.models import SessionRequest
from ..services.documentation import docs_are_loaded, load_marm_documentation
from ..utils.helpers import read_protocol_file

router = APIRouter(prefix="", tags=["MARM Protocol"])


@router.post("/marm_start", operation_id="marm_start", include_in_schema=False)
async def marm_start(request: SessionRequest) -> dict:
    """
    🚀 Activates MARM memory and accuracy layers

    Equivalent to /start marm command
    """
    try:
        with memory.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("UPDATE sessions SET marm_active = FALSE")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions (session_name, marm_active, last_accessed)
                    VALUES (?, TRUE, ?)
                """,
                    (request.session_name, datetime.now(timezone.utc).isoformat()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        if not docs_are_loaded():
            await load_marm_documentation()

        protocol_content = await read_protocol_file()

        await events.emit("marm_started", {"session": request.session_name})

        return {
            "status": "success",
            "message": f"🚀 MARM protocol activated for session '{request.session_name}'",
            "session_name": request.session_name,
            "marm_active": True,
            "protocol_content": protocol_content,
            "instructions": "The complete MARM protocol documentation has been loaded and is available for reference.",
        }
    except sqlite3.Error as e:
        print(f"Database error in marm_start: {e}")
        raise HTTPException(
            status_code=500, detail="Database error during MARM start."
        ) from e
    except Exception as e:
        print(f"Unexpected error in marm_start: {e}")
        raise HTTPException(
            status_code=500, detail="Internal server error during MARM start."
        ) from e


@router.post("/marm_refresh", operation_id="marm_refresh", include_in_schema=False)
async def marm_refresh(request: SessionRequest) -> dict:
    """
    🔄 Refreshes active session state and reaffirms protocol adherence

    Equivalent to /refresh marm command
    """
    try:
        with memory.get_connection() as conn:
            conn.execute(
                """
                UPDATE sessions SET last_accessed = ? WHERE session_name = ?
            """,
                (datetime.now(timezone.utc).isoformat(), request.session_name),
            )
            conn.commit()

        protocol_content = await read_protocol_file()

        await events.emit("marm_refreshed", {"session": request.session_name})

        return {
            "status": "success",
            "message": f"🔄 MARM session '{request.session_name}' refreshed - protocol adherence reaffirmed",
            "session_name": request.session_name,
            "protocol_content": protocol_content,
            "instructions": "Protocol documentation refreshed. Please review the current MARM protocol specifications above.",
        }
    except sqlite3.Error as e:
        print(f"Database error in marm_refresh: {e}")
        raise HTTPException(
            status_code=500, detail="Database error during MARM refresh."
        ) from e
    except Exception as e:
        print(f"Unexpected error in marm_refresh: {e}")
        raise HTTPException(
            status_code=500, detail="Internal server error during MARM refresh."
        ) from e
