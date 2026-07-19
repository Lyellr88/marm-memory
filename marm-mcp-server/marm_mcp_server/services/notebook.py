"""Shared notebook action dispatcher for MARM MCP Server."""

import threading
from datetime import datetime, timezone
from typing import Optional

from ..config.settings import MARM_PLATFORM, MARM_PROJECT
from ..core.docs_db import DocsDB
from ..core.events import events
from ..core.memory import memory
from ..core.memory_utils import _safe_print

_RESERVED_SESSION_NAME = "marm_system"

_docs_db: Optional[DocsDB] = None
_docs_db_lock = threading.Lock()


def _get_docs_db() -> DocsDB:
    """Lazy singleton, mirrors endpoints/concepts.py's _get_concept_db() --
    the docs DB file is only created on first real save, and the lock
    guards against two concurrent first saves each building (and one
    leaking) a DocsDB/connection pool."""
    global _docs_db
    if _docs_db is not None:
        return _docs_db
    with _docs_db_lock:
        if _docs_db is None:
            _docs_db = DocsDB()
    return _docs_db


def _scope_or_detected(value: Optional[str], detected: Optional[str]) -> Optional[str]:
    if value is None:
        return detected or None
    value = value.strip()
    return value or None


async def _add(
    name: Optional[str],
    data: Optional[str],
    session_name: str = "main",
    project: Optional[str] = None,
    platform: Optional[str] = None,
    **_,
) -> dict:
    if not name or not name.strip() or not data or not data.strip():
        return {
            "status": "error",
            "message": "name and data are required for action='add'",
        }
    name = name.strip()
    project = _scope_or_detected(project, MARM_PROJECT)
    platform = _scope_or_detected(platform, MARM_PLATFORM)
    now = datetime.now(timezone.utc).isoformat()
    with memory.get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.execute(
                """
                UPDATE notebook_entries
                SET data = ?, updated_at = ?
                WHERE name = ? AND session_name = ? AND project IS ? AND platform IS ?
                """,
                (data, now, name, session_name, project, platform),
            )
            if cursor.rowcount == 0:
                conn.execute(
                    """
                    INSERT INTO notebook_entries
                        (name, data, session_name, updated_at, project, platform)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, data, session_name, now, project, platform),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    await events.emit("notebook_entry_added", {"name": name, "data": data})
    return {
        "status": "success",
        "message": f"📓 Notebook entry '{name}' added",
        "name": name,
    }


async def _use(names: Optional[str], session_name: str = "main", **_) -> dict:
    if not names or not names.strip():
        return {"status": "error", "message": "names is required for action='use'"}
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if not name_list:
        return {"status": "error", "message": "names is required for action='use'"}
    project = MARM_PROJECT or None
    platform = MARM_PLATFORM or None
    activated_entries = []
    with memory.get_connection() as conn:
        for n in name_list:
            cursor = conn.execute(
                """
                SELECT name, data FROM notebook_entries
                WHERE name = ? AND session_name = ? AND project IS ? AND platform IS ?
                """,
                (n, session_name, project, platform),
            )
            result = cursor.fetchone()
            if result is None and (project is not None or platform is not None):
                result = conn.execute(
                    """
                    SELECT name, data FROM notebook_entries
                    WHERE name = ? AND session_name = ? AND project IS NULL AND platform IS NULL
                    """,
                    (n, session_name),
                ).fetchone()
            if result:
                activated_entries.append({"name": result[0], "data": result[1]})
    memory.set_active_notebook_entries(session_name, activated_entries)
    return {
        "status": "success",
        "message": f"🔧 Activated {len(activated_entries)} notebook entries",
        "activated_entries": [e["name"] for e in activated_entries],
        "entries": activated_entries,
    }


async def _show(session_name: str = "main", **_) -> dict:
    with memory.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT name, data, created_at, updated_at FROM notebook_entries
            WHERE session_name = ? ORDER BY updated_at DESC
            """,
            (session_name,),
        )
        entries = []
        for row in cursor.fetchall():
            preview = row[1][:100] + "..." if len(row[1]) > 100 else row[1]
            entries.append(
                {
                    "name": row[0],
                    "preview": preview,
                    "created_at": row[2],
                    "updated_at": row[3],
                }
            )
    return {
        "status": "success",
        "message": f"📚 Found {len(entries)} notebook entries",
        "entries": entries,
        "total_count": len(entries),
    }


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
    return {
        "status": "success",
        "message": "🧹 Active notebook entries cleared",
        "active_count": 0,
    }


async def _save(
    name: Optional[str],
    data: Optional[str],
    session_name: str = "main",
    project: Optional[str] = None,
    platform: Optional[str] = None,
    **_,
) -> dict:
    """Promote a scratch entry (or new inline content) into the permanent
    docs store. Copy, not move -- the source scratch entry is left
    untouched. The docs row commits first and is the source of truth; the
    memories mirror that gives the concept graph reach is best-effort --
    a failed mirror sync never rolls back the durable save, it just
    reports mirror_status='pending' so a later save can repair it.
    """
    if not name or not name.strip():
        return {"status": "error", "message": "name is required for action='save'"}
    name = name.strip()
    if session_name == _RESERVED_SESSION_NAME:
        return {
            "status": "error",
            "message": (
                f"session_name '{_RESERVED_SESSION_NAME}' is reserved and "
                "cannot be used for action='save'"
            ),
        }
    scoped_project = _scope_or_detected(project, MARM_PROJECT)
    scoped_platform = _scope_or_detected(platform, MARM_PLATFORM)

    source_notebook_name = None
    content = data.strip() if data and data.strip() else None
    if content is None:
        with memory.get_connection() as conn:
            row = conn.execute(
                """
                SELECT data FROM notebook_entries
                WHERE name = ? AND session_name = ? AND project IS ? AND platform IS ?
                """,
                (name, session_name, scoped_project, scoped_platform),
            ).fetchone()
        if row is None:
            return {
                "status": "error",
                "message": (
                    f"No scratch entry named '{name}' found to promote; "
                    "pass data= to save new content directly"
                ),
            }
        content = row[0]
        source_notebook_name = name

    docs_db = _get_docs_db()
    with docs_db.get_connection() as conn:
        doc_row, was_created = docs_db.save_doc(
            conn,
            name=name,
            content=content,
            session_name=session_name,
            project=scoped_project,
            platform=scoped_platform,
            source_notebook_name=source_notebook_name,
        )

    mirror_status = "synced"
    memory_id = doc_row.memory_id
    try:
        memory_id = await memory.store_doc_mirror(
            content,
            session_name,
            scoped_project,
            scoped_platform,
            {
                "doc_type": "promoted_doc",
                "doc_id": doc_row.id,
                "source_notebook_name": source_notebook_name,
            },
            existing_memory_id=doc_row.memory_id,
        )
    except Exception as e:
        _safe_print(f"Doc mirror write failed for doc {doc_row.id}: {e}")
        mirror_status = "pending"

    if mirror_status == "synced":
        with docs_db.get_connection() as conn:
            docs_db.set_memory_id(conn, doc_row.id, memory_id)

    verb = "saved" if was_created else "updated"
    promoted_note = " (promoted from scratch)" if source_notebook_name else ""
    return {
        "status": "success",
        "message": f"📄 Doc '{name}' {verb}{promoted_note}",
        "doc_id": doc_row.id,
        "memory_id": memory_id if mirror_status == "synced" else doc_row.memory_id,
        "mirror_status": mirror_status,
    }


_ACTION_HANDLERS = {
    "add": _add,
    "use": _use,
    "show": _show,
    "status": _status,
    "clear": _clear,
    "save": _save,
}


async def notebook_dispatch(
    action: str,
    name: Optional[str] = None,
    data: Optional[str] = None,
    names: Optional[str] = None,
    session_name: str = "main",
    project: Optional[str] = None,
    platform: Optional[str] = None,
) -> dict:
    session_name = "main" if session_name is None else session_name.strip()
    if not session_name:
        return {"status": "error", "message": "session_name must be a non-empty string"}

    handler = _ACTION_HANDLERS.get(action)
    if handler is None:
        return {
            "status": "error",
            "message": f"Unknown action '{action}'. Must be: add, use, show, status, clear, save",
        }
    return await handler(
        name=name,
        data=data,
        names=names,
        session_name=session_name,
        project=project,
        platform=platform,
    )
