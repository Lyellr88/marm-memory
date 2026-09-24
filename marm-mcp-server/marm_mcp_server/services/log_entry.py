import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from ..config.settings import MARM_PLATFORM, MARM_PROJECT
from ..core.events import events
from ..core.memory import memory
from ..core.memory_utils import _safe_print

_SESSION_PREFIXES = ("Session: ", "Topic: ")
_SESSION_INACTIVITY_NOTICE_SECONDS = 3600


async def create_log_entry(
    entry: str,
    session_name: Optional[str],
    *,
    project: Optional[str] = None,
    log_info: Callable[[str], None] = print,
    log_warning: Callable[[str], None] = print,
) -> dict:
    """Write a log entry, optionally scoped to a caller-chosen project.

    `project` is optional and falls back to the detected `MARM_PROJECT` when it
    is omitted, so existing callers keep their current behaviour. It matters on
    a shared HTTP runtime, where the detected value is the SERVER process's
    working directory rather than the caller's, and project-scoped recall then
    misses or misattributes the entry.
    """
    # One expression, used by the session-marker row, the normal row and the
    # semantic write, so the three cannot disagree about what scope means.
    scope = project or MARM_PROJECT or None
    explicit = bool(project)

    try:
        formatted_entry = entry.strip()

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
                    conn.execute("BEGIN IMMEDIATE")
                    try:
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
                                scope,
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
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                memory.active_log_session = new_session
                try:
                    await events.emit("session_created", {"session": new_session})
                except Exception as event_error:
                    log_warning(f"session_created event failed: {event_error}")
                return {
                    "status": "session_switched",
                    "message": f"📂 Session switched to '{new_session}'",
                    "session_name": new_session,
                }

        if session_name:
            session = session_name
        elif memory.active_log_session != "main":
            session = memory.active_log_session
        else:
            date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            session = f"session-{date_tag}"
            with memory.get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
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
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            memory.active_log_session = session

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
            conn.execute("BEGIN IMMEDIATE")
            try:
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
                        scope,
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
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        memory_id = None
        try:
            memory_id = await memory.store_memory_queued(
                formatted_entry,
                session,
                metadata={"source": "log_entry", "log_entry_id": entry_id},
                # The columns, not the metadata blob: scoped recall reads them.
                # The platform is the one the log row above records, so an
                # explicit project does not also erase where the entry came from.
                project=scope,
                platform=MARM_PLATFORM or None,
                explicit_scope=explicit,
            )
        except Exception as store_error:
            log_warning(
                f"Semantic store failed for log entry {entry_id}: {store_error}"
            )

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


async def _cleanup_concepts_for(memory_ids: list[str]) -> dict:
    """Remove concept entities left behind by deleted memories.

    Imported inside the function, as `services/notebook.py` does for the same
    helper: `endpoints/memory` imports from this package, so a module-level
    import would close the cycle.

    Never raises. A delete that has already committed must not be reported as
    a failure because its follow-up cleanup could not run -- the rows are
    gone either way, and `tools`-side sweeps can still find the strays.
    """
    if not memory_ids:
        return {"status": "skipped", "reason": "no memories deleted"}
    try:
        # Inside the try, not above it: an ImportError here is a cleanup
        # failure like any other, and the delete it follows has already
        # committed. Raising would report a completed delete as failed.
        from ..endpoints.memory import _cleanup_deleted_concepts_async

        return await _cleanup_deleted_concepts_async(memory_ids)
    except Exception as e:
        # Detail stays local; the response matches the memory endpoints'.
        _safe_print(f"Concept cleanup failed after log delete: {e}")
        return {"status": "failed", "error": "Concept cleanup failed."}


async def delete_log_or_notebook_entry(
    type: str,
    target: str,
    session_name: Optional[str],
    *,
    project: Optional[str] = None,
    platform: Optional[str] = None,
    scoped_notebook: bool = False,
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
                # Ids of the memories this delete removes, so their concept
                # entities can be cleaned up after the commit. The memory
                # endpoints already do this; this path did not, which is the
                # whole of the inconsistency -- the same rows removed through
                # bulk-delete were cleaned and removed through marm_delete
                # were not, leaving entities that keep their relationships and
                # go on steering concept recall with nothing evidencing them.
                deleted_memory_ids: list[str] = []
                if session_name:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
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
                            # Collected BEFORE the delete: afterwards the rows
                            # are gone and the ids are unrecoverable.
                            deleted_memory_ids = [
                                r[0]
                                for r in conn.execute(
                                    "SELECT id FROM memories WHERE json_extract(metadata, '$.source') = 'log_entry' "
                                    f"AND json_extract(metadata, '$.log_entry_id') IN ({placeholders})",
                                    entry_ids,
                                ).fetchall()
                            ]
                            memories_deleted = conn.execute(
                                "DELETE FROM memories WHERE json_extract(metadata, '$.source') = 'log_entry' "
                                f"AND json_extract(metadata, '$.log_entry_id') IN ({placeholders})",
                                entry_ids,
                            ).rowcount
                        if deleted:
                            try:
                                conn.execute(
                                    "UPDATE session_summary_cache SET dirty = TRUE, updated_at = ? WHERE session_name = ?",
                                    (
                                        datetime.now(timezone.utc).isoformat(),
                                        session_name,
                                    ),
                                )
                            except Exception:
                                pass
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                else:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        conn.execute(
                            "DELETE FROM sessions WHERE session_name = ?", (target,)
                        )
                        cursor = conn.execute(
                            "DELETE FROM log_entries WHERE session_name = ?", (target,)
                        )
                        deleted = cursor.rowcount
                        try:
                            conn.execute(
                                "DELETE FROM session_summary_cache WHERE session_name = ?",
                                (target,),
                            )
                        except Exception:
                            pass
                        deleted_memory_ids = [
                            r[0]
                            for r in conn.execute(
                                "SELECT id FROM memories WHERE session_name = ? "
                                "AND json_extract(metadata, '$.source') = 'log_entry'",
                                (target,),
                            ).fetchall()
                        ]
                        memories_deleted = conn.execute(
                            "DELETE FROM memories WHERE session_name = ? "
                            "AND json_extract(metadata, '$.source') = 'log_entry'",
                            (target,),
                        ).rowcount
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                if not session_name and memory.active_log_session == target:
                    memory.active_log_session = "main"
                # Built here, returned after the connection is released: the
                # cleanup below awaits on the CONCEPT database, and holding a
                # pooled memory connection across that await lets concurrent
                # deletes exhaust the pool and fail unrelated queries.
                log_result = {
                    "status": "success",
                    "message": f"🗑️ Deleted {deleted} items",
                    "deleted_count": deleted,
                    "memories_deleted": memories_deleted,
                }
            else:
                notebook_session = (session_name or "main").strip() or "main"
                conn.execute("BEGIN IMMEDIATE")
                try:
                    if scoped_notebook or project is not None or platform is not None:
                        cursor = conn.execute(
                            """
                            DELETE FROM notebook_entries
                            WHERE name = ? AND session_name = ? AND project IS ? AND platform IS ?
                            """,
                            (target, notebook_session, project, platform),
                        )
                        deleted = cursor.rowcount
                    else:
                        matches = conn.execute(
                            "SELECT project, platform FROM notebook_entries "
                            "WHERE name = ? AND session_name = ?",
                            (target, notebook_session),
                        ).fetchall()
                        if len(matches) > 1:
                            conn.execute("ROLLBACK")
                            return {
                                "status": "error",
                                "message": (
                                    f"Multiple notebook entries named '{target}' exist "
                                    f"in session '{notebook_session}' across different "
                                    "project/platform scopes; pass project and/or "
                                    "platform to disambiguate."
                                ),
                            }
                        cursor = conn.execute(
                            "DELETE FROM notebook_entries WHERE name = ? AND session_name = ?",
                            (target, notebook_session),
                        )
                        deleted = cursor.rowcount
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                if deleted > 0:
                    memory.remove_active_notebook_entry(target, notebook_session)
                # Returns from inside the connection context, which is fine:
                # the notebook branch deletes no memories and so awaits
                # nothing here.
                return {
                    "status": "success" if deleted > 0 else "not_found",
                    "message": (
                        f"🗑️ Deleted notebook entry '{target}'"
                        if deleted > 0
                        else f"Entry '{target}' not found"
                    ),
                    "deleted": deleted > 0,
                }
        log_result["concept_cleanup"] = await _cleanup_concepts_for(deleted_memory_ids)
        return log_result
    except sqlite3.Error as e:
        log_warning(f"Database error deleting: {e}")
        return {"status": "error", "message": "Database error while deleting."}
    except Exception as e:
        log_warning(f"Unexpected error deleting: {e}")
        return {"status": "error", "message": "Delete failed."}
