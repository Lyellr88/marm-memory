"""Shared log-entry/notebook data operations used by both transports.

endpoints/logging.py (HTTP) and services/stdio_entry_tools.py (STDIO) call
into these three functions instead of each carrying their own copy of the
session-switch detection, SQL, and dual-write-to-semantic-memory logic.
Each transport wrapper supplies its own log_info/log_warning callables so
HTTP keeps its print()-to-stdout convention and STDIO keeps its
_stdio_log-to-stderr-and-file convention -- this module has no opinion on
logging destination, only on what to log.
"""

import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from ..config.settings import MARM_PLATFORM, MARM_PROJECT
from ..core.events import events
from ..core.memory import memory

_SESSION_PREFIXES = ("Session: ", "Topic: ")
_SESSION_INACTIVITY_NOTICE_SECONDS = 3600


async def create_log_entry(
    entry: str,
    session_name: Optional[str],
    *,
    log_info: Callable[[str], None] = print,
    log_warning: Callable[[str], None] = print,
) -> dict:
    try:
        formatted_entry = entry.strip()

        # Session-switch detection
        for prefix in _SESSION_PREFIXES:
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
                # The session row and marker entry above are already durably
                # committed -- an event-publish failure must not turn that
                # into a client-visible error (same principle as the
                # semantic-store try/except below: a retry on a false
                # "error" response would create a duplicate session_start
                # marker).
                try:
                    await events.emit("session_created", {"session": new_session})
                except Exception as event_error:
                    log_warning(f"session_created event failed: {event_error}")
                return {
                    "status": "session_switched",
                    "message": f"📂 Session switched to '{new_session}'",
                    "session_name": new_session,
                }

        # Resolve session — explicit > active > dated fallback
        if session_name:
            session = session_name
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
                if gap > _SESSION_INACTIVITY_NOTICE_SECONDS:
                    log_info(
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

        # Dual-write into semantic memory so marm_smart_recall can find it;
        # a store failure must never fail the log write itself.
        memory_id = None
        try:
            memory_id = await memory.store_memory_queued(
                formatted_entry,
                session,
                metadata={"source": "log_entry", "log_entry_id": entry_id},
            )
        except Exception as store_error:
            log_warning(
                f"Semantic store failed for log entry {entry_id}: {store_error}"
            )

        # Same reasoning as the session_created emit above -- the log_entries
        # row (and the semantic memory, if the dual-write above succeeded)
        # are already committed, so an event-publish failure here must not
        # turn an already-durable write into a client-visible error.
        try:
            await events.emit(
                "log_entry_created",
                {
                    "entry_id": entry_id,
                    "session": session,
                    "content": formatted_entry,
                },
            )
        except Exception as event_error:
            log_warning(f"log_entry_created event failed: {event_error}")

        return {
            "status": "success",
            "message": f"📝 Log entry added: {formatted_entry}",
            "entry_id": entry_id,
            "memory_id": memory_id,
            "formatted_entry": formatted_entry,
        }
    except sqlite3.Error as e:
        # Never return str(e) to the client -- can leak SQLite paths/schema
        # (same CWE-209 class as the marm_concept_recall fix). Log
        # server-side via the caller's injected logger instead.
        log_warning(f"Database error creating log entry: {e}")
        return {
            "status": "error",
            "message": "Database error while creating log entry.",
        }
    except Exception as e:
        log_warning(f"Unexpected error creating log entry: {e}")
        return {"status": "error", "message": "Log entry creation failed."}


async def list_log_entries(
    session_name: Optional[str],
    *,
    log_warning: Callable[[str], None] = print,
) -> dict:
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
        log_warning(f"Database error showing logs: {e}")
        return {"status": "error", "message": "Database error while showing logs."}
    except Exception as e:
        log_warning(f"Unexpected error showing logs: {e}")
        return {"status": "error", "message": "Log show failed."}


async def delete_log_or_notebook_entry(
    type: str,
    target: str,
    session_name: Optional[str],
    *,
    log_warning: Callable[[str], None] = print,
) -> dict:
    """type must already be validated as "log" or "notebook" by the caller
    -- transport-specific invalid-type handling (HTTP 422 vs. STDIO error
    dict) stays at the transport layer so this module has no FastAPI
    dependency."""
    try:
        with memory.get_connection() as conn:
            if type == "log":
                memories_deleted = 0
                if session_name:
                    # Dual-written semantic memories must not outlive their log entries
                    rows = conn.execute(
                        "SELECT id FROM log_entries WHERE session_name = ? AND (id = ? OR topic = ?)",
                        (session_name, target, target),
                    ).fetchall()
                    entry_ids = [r[0] for r in rows]
                    cursor = conn.execute(
                        "DELETE FROM log_entries WHERE session_name = ? AND (id = ? OR topic = ?)",
                        (session_name, target, target),
                    )
                    deleted = cursor.rowcount
                    if entry_ids:
                        placeholders = ",".join("?" * len(entry_ids))
                        memories_deleted = conn.execute(
                            "DELETE FROM memories WHERE json_extract(metadata, '$.source') = 'log_entry' "
                            f"AND json_extract(metadata, '$.log_entry_id') IN ({placeholders})",
                            entry_ids,
                        ).rowcount
                    if deleted:
                        try:
                            conn.execute(
                                "UPDATE session_summary_cache SET dirty = TRUE, updated_at = ? WHERE session_name = ?",
                                (datetime.now(timezone.utc).isoformat(), session_name),
                            )
                        except Exception:
                            pass
                else:
                    conn.execute(
                        "DELETE FROM sessions WHERE session_name = ?", (target,)
                    )
                    cursor = conn.execute(
                        "DELETE FROM log_entries WHERE session_name = ?", (target,)
                    )
                    deleted = cursor.rowcount
                    # Guarded like every other session_summary_cache touch in
                    # this module -- a missing/locked cache row must not
                    # abort the rest of the whole-session delete.
                    try:
                        conn.execute(
                            "DELETE FROM session_summary_cache WHERE session_name = ?",
                            (target,),
                        )
                    except Exception:
                        pass
                    memories_deleted = conn.execute(
                        "DELETE FROM memories WHERE session_name = ? "
                        "AND json_extract(metadata, '$.source') = 'log_entry'",
                        (target,),
                    ).rowcount
                conn.commit()
                # Flip the runtime pointer only after the delete durably
                # commits -- otherwise a failed commit leaves the process
                # thinking the active session is "main" while the target
                # session's rows are still intact in the DB.
                if not session_name and memory.active_log_session == target:
                    memory.active_log_session = "main"
                return {
                    "status": "success",
                    "message": f"🗑️ Deleted {deleted} items",
                    "deleted_count": deleted,
                    "memories_deleted": memories_deleted,
                }
            else:  # type == "notebook"
                cursor = conn.execute(
                    "DELETE FROM notebook_entries WHERE name = ?", (target,)
                )
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    memory.remove_active_notebook_entry(target)
                return {
                    "status": "success" if deleted > 0 else "not_found",
                    "message": f"🗑️ Deleted notebook entry '{target}'"
                    if deleted > 0
                    else f"Entry '{target}' not found",
                    "deleted": deleted > 0,
                }
    except sqlite3.Error as e:
        log_warning(f"Database error deleting: {e}")
        return {"status": "error", "message": "Database error while deleting."}
    except Exception as e:
        log_warning(f"Unexpected error deleting: {e}")
        return {"status": "error", "message": "Delete failed."}
