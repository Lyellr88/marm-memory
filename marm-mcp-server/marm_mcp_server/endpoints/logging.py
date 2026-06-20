"""Logging endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter, Query
import sqlite3
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..core.models import LogEntryRequest, DeleteRequest
from ..core.memory import memory
from ..core.events import events
from ..config.settings import MARM_PROJECT, MARM_PLATFORM

router = APIRouter(prefix="", tags=["Logging"])

SESSION_PREFIXES = ("Session: ", "Topic: ")
SESSION_INACTIVITY_NOTICE_SECONDS = 3600


@router.post("/marm_log_entry", operation_id="marm_log_entry")
async def marm_log_entry(request: LogEntryRequest):
    """
    📝 Add structured log entry for milestones or decisions

    Start with "Session: [name]" or "Topic: [name]" to switch active session.
    The backend auto-tags the date. All subsequent entries route to that session.
    Equivalent to /log entry: [YYYY-MM-DD-topic-summary] command
    """
    try:
        formatted_entry = request.entry.strip()

        # Session-switch detection
        for prefix in SESSION_PREFIXES:
            if formatted_entry.startswith(prefix):
                base_name = formatted_entry[len(prefix) :].strip()
                if not base_name:
                    return {
                        "status": "error",
                        "message": "Session name cannot be empty.",
                    }
                date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                new_session = f"{base_name}-{date_tag}"
                marker_id = str(uuid.uuid4())
                with memory.get_connection() as conn:
                    conn.execute("UPDATE sessions SET marm_active = FALSE")
                    conn.execute(
                        """
                        INSERT INTO sessions (session_name, last_accessed, marm_active)
                        VALUES (?, ?, TRUE)
                        ON CONFLICT(session_name) DO UPDATE SET
                            last_accessed = excluded.last_accessed,
                            marm_active = TRUE
                        """,
                        (new_session, datetime.now(timezone.utc).isoformat()),
                    )
                    conn.execute(
                        """
                        INSERT INTO log_entries
                            (id, session_name, entry_date, topic, summary, full_entry, project, platform)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            marker_id,
                            new_session,
                            date_tag,
                            "session_start",
                            base_name,
                            formatted_entry,
                            MARM_PROJECT or None,
                            MARM_PLATFORM or None,
                        ),
                    )
                    try:
                        conn.execute(
                            "UPDATE session_summary_cache SET dirty = TRUE, updated_at = ? WHERE session_name = ?",
                            (datetime.now(timezone.utc).isoformat(), new_session),
                        )
                    except Exception:
                        pass
                    conn.commit()
                memory.active_log_session = new_session
                await events.emit("session_created", {"session": new_session})
                return {
                    "status": "session_switched",
                    "message": f"📂 Session switched to '{new_session}'",
                    "session_name": new_session,
                }

        # Resolve session — explicit > active > dated fallback
        if request.session_name:
            session = request.session_name
        elif memory.active_log_session != "main":
            session = memory.active_log_session
        else:
            date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            session = f"session-{date_tag}"
            with memory.get_connection() as conn:
                conn.execute("UPDATE sessions SET marm_active = FALSE")
                conn.execute(
                    """
                    INSERT INTO sessions (session_name, last_accessed, marm_active)
                    VALUES (?, ?, TRUE)
                    ON CONFLICT(session_name) DO UPDATE SET
                        last_accessed = excluded.last_accessed,
                        marm_active = TRUE
                    """,
                    (session, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
            memory.active_log_session = session

        # Chunk boundary check
        with memory.get_connection() as conn:
            row = conn.execute(
                "SELECT last_accessed FROM sessions WHERE session_name = ?", (session,)
            ).fetchone()
        if row and row[0]:
            try:
                last_dt = datetime.fromisoformat(row[0])
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                gap = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if gap > SESSION_INACTIVITY_NOTICE_SECONDS:
                    print(
                        f"[MARM] Chunk boundary detected for '{session}' — {gap:.0f}s since last write"
                    )
            except Exception:
                pass

        entry_pattern = r"^(\d{4}-\d{2}-\d{2})-(.*?)-(.*?)$"
        match = re.match(entry_pattern, formatted_entry)

        if match:
            entry_date, topic, summary = match.groups()
        else:
            entry_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            topic = "general"
            summary = formatted_entry

        entry_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        with memory.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry, project, platform)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    session,
                    entry_date,
                    topic,
                    summary,
                    formatted_entry,
                    MARM_PROJECT or None,
                    MARM_PLATFORM or None,
                ),
            )
            conn.execute(
                """
                INSERT INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
                ON CONFLICT(session_name) DO UPDATE SET last_accessed = excluded.last_accessed
                """,
                (session, now_iso),
            )
            try:
                conn.execute(
                    "UPDATE session_summary_cache SET dirty = TRUE, updated_at = ? WHERE session_name = ?",
                    (now_iso, session),
                )
            except Exception:
                pass
            conn.commit()

        await events.emit(
            "log_entry_created",
            {"entry_id": entry_id, "session": session, "content": formatted_entry},
        )

        return {
            "status": "success",
            "message": f"📝 Log entry added: {formatted_entry}",
            "entry_id": entry_id,
            "formatted_entry": formatted_entry,
        }
    except sqlite3.Error as e:
        print(f"Database error in marm_log_entry: {e}")
        return {
            "status": "error",
            "message": "Database error while creating log entry.",
        }
    except Exception as e:
        print(f"Unexpected error in marm_log_entry: {e}")
        return {"status": "error", "message": "Log entry creation failed."}


@router.get("/marm_log_show", operation_id="marm_log_show")
async def marm_log_show(
    session_name: Optional[str] = Query(
        None, description="Session to show logs for. If omitted, lists all sessions."
    ),
):
    """
    📋 Display all entries and sessions logged

    Equivalent to /log show: [session] command
    """
    try:
        with memory.get_connection() as conn:
            if session_name:
                cursor = conn.execute(
                    """
                    SELECT id, entry_date, topic, summary, full_entry
                    FROM log_entries WHERE session_name = ?
                    ORDER BY entry_date DESC
                """,
                    (session_name,),
                )
                entries = [
                    {
                        "id": r[0],
                        "entry_date": r[1],
                        "topic": r[2],
                        "summary": r[3],
                        "full_entry": r[4],
                    }
                    for r in cursor.fetchall()
                ]

                return {
                    "status": "success",
                    "session_name": session_name,
                    "entries": entries,
                    "total_entries": len(entries),
                }
            else:
                cursor = conn.execute(
                    "SELECT session_name, COUNT(*) FROM log_entries GROUP BY session_name"
                )
                sessions = [
                    {"session_name": r[0], "entry_count": r[1]}
                    for r in cursor.fetchall()
                ]

                return {
                    "status": "success",
                    "sessions": sessions,
                    "total_sessions": len(sessions),
                }
    except sqlite3.Error as e:
        print(f"Database error in marm_log_show: {e}")
        return {"status": "error", "message": "Database error while showing logs."}
    except Exception as e:
        print(f"Unexpected error in marm_log_show: {e}")
        return {"status": "error", "message": "Log show failed."}


@router.post("/marm_delete", operation_id="marm_delete")
async def marm_delete(request: DeleteRequest):
    """
    🗑️ Delete a log session, log entry, or notebook entry

    type="log" + session_name: delete specific entry by id or topic
    type="log" (no session_name): delete entire session and all its entries
    type="notebook": delete notebook entry by name
    """
    try:
        with memory.get_connection() as conn:
            if request.type == "log":
                if request.session_name:
                    cursor = conn.execute(
                        "DELETE FROM log_entries WHERE session_name = ? AND (id = ? OR topic = ?)",
                        (request.session_name, request.target, request.target),
                    )
                    deleted = cursor.rowcount
                    if deleted:
                        try:
                            conn.execute(
                                "UPDATE session_summary_cache SET dirty = TRUE, updated_at = ? WHERE session_name = ?",
                                (
                                    datetime.now(timezone.utc).isoformat(),
                                    request.session_name,
                                ),
                            )
                        except Exception:
                            pass
                else:
                    conn.execute(
                        "DELETE FROM sessions WHERE session_name = ?", (request.target,)
                    )
                    cursor = conn.execute(
                        "DELETE FROM log_entries WHERE session_name = ?",
                        (request.target,),
                    )
                    deleted = cursor.rowcount
                    conn.execute(
                        "DELETE FROM session_summary_cache WHERE session_name = ?",
                        (request.target,),
                    )
                    if memory.active_log_session == request.target:
                        memory.active_log_session = "main"
                conn.commit()
                return {
                    "status": "success",
                    "message": f"🗑️ Deleted {deleted} items",
                    "deleted_count": deleted,
                }
            elif request.type == "notebook":
                cursor = conn.execute(
                    "DELETE FROM notebook_entries WHERE name = ?", (request.target,)
                )
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    memory.remove_active_notebook_entry(request.target)
                return {
                    "status": "success" if deleted > 0 else "not_found",
                    "message": f"🗑️ Deleted notebook entry '{request.target}'"
                    if deleted > 0
                    else f"Entry '{request.target}' not found",
                    "deleted": deleted > 0,
                }
            else:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid type '{request.type}'. Must be 'log' or 'notebook'.",
                )
    except HTTPException:
        raise
    except sqlite3.Error as e:
        print(f"Database error in marm_delete: {e}")
        return {"status": "error", "message": "Database error while deleting."}
    except Exception as e:
        print(f"Unexpected error in marm_delete: {e}")
        return {"status": "error", "message": "Delete failed."}
