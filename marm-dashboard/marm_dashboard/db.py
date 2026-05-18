"""Direct SQLite access to the MARM memory database."""

from __future__ import annotations

import html
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_db_path

_ENCODER = None
_ENCODER_FAILED = False
_SEMANTIC_MODEL = "all-MiniLM-L6-v2"
_CONTEXT_TYPES = frozenset({"general", "code", "project", "book"})

def _strip_script_tags(text: str) -> str:
    lower = text.lower()
    result = []
    i = 0
    while i < len(text):
        start = lower.find('<script', i)
        if start == -1:
            result.append(text[i:])
            break
        after = start + 7
        if after < len(text) and text[after] not in (' ', '\t', '\n', '\r', '>'):
            result.append(text[i:after])
            i = after
            continue
        result.append(text[i:start])
        open_end = text.find('>', start)
        if open_end == -1:
            break
        j = open_end + 1
        close_end = -1
        while j < len(text):
            cs = lower.find('</script', j)
            if cs == -1:
                break
            close_end = text.find('>', cs)
            if close_end != -1:
                i = close_end + 1
                break
            j = cs + 8
        if close_end == -1:
            result.append(text[open_end + 1:])
            break
    return ''.join(result)


def _parse_metadata(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _for_display(text: str) -> str:
    """Undo stored HTML entities for human-readable UI (MCP stores escaped content)."""
    if not text:
        return text
    return html.unescape(text)


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _strip_scripts(content: str) -> str:
    """Notebook parity with MCP: store raw text, only strip obvious script blocks."""
    if not content:
        return content
    if len(content) > 500_000:
        content = content[:500_000]
    return _strip_script_tags(content)


def _sanitize_memory(content: str) -> str:
    """Match marm-mcp-server memory storage (escaped for XSS)."""
    if not content:
        return content
    if len(content) > 10_000:
        content = content[:10_000]
    sanitized = _strip_scripts(content)
    sanitized = re.sub(r"javascript:", "blocked-protocol:", sanitized, flags=re.IGNORECASE)
    return html.escape(sanitized)


def _connect() -> sqlite3.Connection:
    path = get_db_path()
    if not Path(path).exists():
        raise FileNotFoundError(
            f"MARM database not found at {path}. Start marm-mcp-server once or set MARM_DB_PATH."
        )
    conn = sqlite3.connect(path, check_same_thread=False, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def _touch_session(conn: sqlite3.Connection, session_name: str, timestamp: str) -> None:
    cur = conn.execute(
        "UPDATE sessions SET last_accessed = ? WHERE session_name = ?",
        (timestamp, session_name),
    )
    if cur.rowcount == 0:
        conn.execute(
            "INSERT INTO sessions (session_name, last_accessed) VALUES (?, ?)",
            (session_name, timestamp),
        )


def embeddings_package_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


def _maybe_embedding(text: str) -> Optional[bytes]:
    global _ENCODER, _ENCODER_FAILED
    if _ENCODER_FAILED or not text.strip():
        return None
    try:
        if _ENCODER is None:
            from sentence_transformers import SentenceTransformer

            _ENCODER = SentenceTransformer(_SEMANTIC_MODEL)
        import numpy as np

        return _ENCODER.encode(text).astype(np.float32).tobytes()
    except Exception:
        _ENCODER_FAILED = True
        return None


def get_summary() -> Dict[str, Any]:
    with _connect() as conn:
        memories = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        logs = conn.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0]
        notebook = conn.execute("SELECT COUNT(*) FROM notebook_entries").fetchone()[0]
        active = conn.execute(
            "SELECT session_name FROM sessions WHERE marm_active = 1 LIMIT 1"
        ).fetchone()
    return {
        "db_path": get_db_path(),
        "counts": {
            "memories": memories,
            "sessions": sessions,
            "log_entries": logs,
            "notebook_entries": notebook,
        },
        "active_session": active[0] if active else None,
        "embeddings_package_available": embeddings_package_available(),
        "semantic_model_loaded": _ENCODER is not None and not _ENCODER_FAILED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def list_session_names() -> List[str]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT session_name FROM sessions
            UNION
            SELECT DISTINCT session_name FROM memories
            UNION
            SELECT DISTINCT session_name FROM log_entries
            ORDER BY session_name COLLATE NOCASE
            """
        ).fetchall()
    return [r[0] for r in rows if r[0]]


def list_sessions(q: Optional[str] = None) -> List[Dict[str, Any]]:
    params: List[Any] = []
    where = ""
    if q:
        where = "WHERE s.session_name LIKE ? ESCAPE '\\'"
        params.append(_like_pattern(q))
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT s.session_name, s.marm_active, s.last_accessed,
                   (SELECT COUNT(*) FROM memories m WHERE m.session_name = s.session_name) AS memory_count,
                   (SELECT COUNT(*) FROM log_entries l WHERE l.session_name = s.session_name) AS log_count
            FROM sessions s
            {where}
            ORDER BY s.last_accessed DESC
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def list_memories(
    session: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    clauses: List[str] = []
    params: List[Any] = []

    if session:
        clauses.append("session_name = ?")
        params.append(session)
    if q:
        clauses.append("content LIKE ? ESCAPE '\\'")
        params.append(_like_pattern(q))

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with _connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM memories {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT id, session_name, content, timestamp, context_type, metadata, created_at
            FROM memories
            {where}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    items = []
    for row in rows:
        raw = row["content"] or ""
        preview = (raw[:240] + "…") if len(raw) > 240 else raw
        items.append(
            {
                "id": row["id"],
                "session_name": row["session_name"],
                "content": raw,
                "display_content": _for_display(raw),
                "timestamp": row["timestamp"],
                "context_type": row["context_type"],
                "metadata": _parse_metadata(row["metadata"]),
                "created_at": row["created_at"],
                "preview": preview,
                "display_preview": _for_display(preview),
            }
        )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def add_memory(content: str, session_name: str, context_type: str = "general") -> str:
    if context_type not in _CONTEXT_TYPES:
        raise ValueError(f"context_type must be one of: {', '.join(sorted(_CONTEXT_TYPES))}")

    sanitized = _sanitize_memory(content.strip())
    if not sanitized:
        raise ValueError("Content cannot be empty")
    if not session_name.strip():
        raise ValueError("Session name is required")

    memory_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    embedding = _maybe_embedding(sanitized)

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO memories (id, session_name, content, embedding, timestamp, context_type, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                session_name.strip(),
                sanitized,
                embedding,
                timestamp,
                context_type,
                "{}",
            ),
        )
        _touch_session(conn, session_name.strip(), timestamp)
        conn.commit()
    return memory_id


def update_memory(memory_id: str, content: str, context_type: str) -> bool:
    if context_type not in _CONTEXT_TYPES:
        raise ValueError(f"context_type must be one of: {', '.join(sorted(_CONTEXT_TYPES))}")
    sanitized = _sanitize_memory(content.strip())
    if not sanitized:
        raise ValueError("Content cannot be empty")
    embedding = _maybe_embedding(sanitized)
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE memories SET content = ?, context_type = ?, embedding = ? WHERE id = ?",
            (sanitized, context_type, embedding, memory_id),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_memory(memory_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        return cur.rowcount > 0


def delete_all_memories(session: Optional[str] = None) -> int:
    with _connect() as conn:
        if session:
            cur = conn.execute("DELETE FROM memories WHERE session_name = ?", (session,))
        else:
            cur = conn.execute("DELETE FROM memories")
        conn.commit()
        return cur.rowcount


def list_logs(
    session: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    clauses: List[str] = []
    params: List[Any] = []
    if session:
        clauses.append("session_name = ?")
        params.append(session)
    if q:
        pattern = _like_pattern(q)
        clauses.append("(topic LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\')")
        params.extend([pattern, pattern])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with _connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM log_entries {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT id, session_name, entry_date, topic, summary, full_entry, created_at
            FROM log_entries
            {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        item["display_summary"] = _for_display(item.get("summary") or "")
        item["display_full_entry"] = _for_display(item.get("full_entry") or "")
        items.append(item)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def delete_all_logs() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM log_entries")
        conn.commit()
        return cur.rowcount


def delete_log(log_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM log_entries WHERE id = ?", (log_id,))
        conn.commit()
        return cur.rowcount > 0


def add_session(session_name: str) -> None:
    name = session_name.strip()
    if not name:
        raise ValueError("Session name is required")
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM sessions WHERE session_name = ?", (name,)
        ).fetchone()
        if existing:
            raise ValueError(f"Session '{name}' already exists")
        conn.execute(
            "INSERT INTO sessions (session_name, last_accessed) VALUES (?, ?)",
            (name, timestamp),
        )
        conn.commit()


def delete_session(session_name: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE session_name = ?", (session_name,))
        conn.commit()
        return cur.rowcount > 0


def delete_all_sessions() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM sessions")
        conn.commit()
        return cur.rowcount


def list_notebook(q: Optional[str] = None) -> List[Dict[str, Any]]:
    params: List[Any] = []
    where = ""
    if q:
        pattern = _like_pattern(q)
        where = "WHERE (name LIKE ? ESCAPE '\\' OR data LIKE ? ESCAPE '\\')"
        params = [pattern, pattern]
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT name, data, created_at, updated_at
            FROM notebook_entries
            {where}
            ORDER BY updated_at DESC
            """,
            params,
        ).fetchall()
    out = []
    for row in rows:
        data = row["data"] or ""
        preview = (data[:200] + "…") if len(data) > 200 else data
        out.append(
            {
                "name": row["name"],
                "data": data,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "preview": preview,
                "display_preview": _for_display(preview),
                "size_chars": len(data),
            }
        )
    return out


def upsert_notebook(name: str, data: str) -> None:
    if not name.strip():
        raise ValueError("Name is required")
    clean_name = name.strip()
    clean_data = _strip_scripts(data)
    now = datetime.now(timezone.utc).isoformat()
    embedding = _maybe_embedding(clean_data)

    with _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM notebook_entries WHERE name = ?", (clean_name,)
        ).fetchone()
        if exists:
            conn.execute(
                """
                UPDATE notebook_entries
                SET data = ?, embedding = ?, updated_at = ?
                WHERE name = ?
                """,
                (clean_data, embedding, now, clean_name),
            )
        else:
            conn.execute(
                """
                INSERT INTO notebook_entries (name, data, embedding, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (clean_name, clean_data, embedding, now),
            )
        conn.commit()


def delete_notebook(name: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM notebook_entries WHERE name = ?", (name,))
        conn.commit()
        return cur.rowcount > 0


def delete_all_notebook() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM notebook_entries")
        conn.commit()
        return cur.rowcount
