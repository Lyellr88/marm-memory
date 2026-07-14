"""STDIO log-entry/notebook data operations with real inline SQL (not
thin service-call wrappers)."""

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..config.settings import MARM_PLATFORM, MARM_PROJECT
from ..core.events import events
from ..core.memory import memory
from ..core.stdio_logging import _stdio_log


_SESSION_PREFIXES = ("Session: ", "Topic: ")
_SESSION_INACTIVITY_NOTICE_SECONDS = 3600


async def create_log_entry_stdio(entry: str, session_name: Optional[str]) -> dict:
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
                await events.emit("session_created", {"session": new_session})
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
            _stdio_log.warning(
                "semantic store failed for log entry %s: %s", entry_id, store_error
            )

        await events.emit(
            "log_entry_created",
            {"entry_id": entry_id, "session": session, "content": formatted_entry},
        )

        return {
            "status": "success",
            "message": f"📝 Log entry added: {formatted_entry}",
            "entry_id": entry_id,
            "memory_id": memory_id,
            "formatted_entry": formatted_entry,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error creating log entry: {e!s}"}


async def list_log_entries_stdio(session_name: Optional[str]) -> dict:
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
    except Exception as e:
        return {"status": "error", "message": f"Error retrieving log entries: {e!s}"}
