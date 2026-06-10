"""Direct SQLite access to the MARM memory database."""

from __future__ import annotations

import html
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
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
        start = lower.find("<script", i)
        if start == -1:
            result.append(text[i:])
            break
        after = start + 7
        if after < len(text) and text[after] not in (" ", "\t", "\n", "\r", ">"):
            result.append(text[i:after])
            i = after
            continue
        result.append(text[i:start])
        open_end = text.find(">", start)
        if open_end == -1:
            break
        j = open_end + 1
        close_end = -1
        while j < len(text):
            cs = lower.find("</script", j)
            if cs == -1:
                break
            close_end = text.find(">", cs)
            if close_end != -1:
                i = close_end + 1
                break
            j = cs + 8
        if close_end == -1:
            result.append(text[open_end + 1 :])
            break
    return "".join(result)


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
    sanitized = re.sub(
        r"javascript:", "blocked-protocol:", sanitized, flags=re.IGNORECASE
    )
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

    # Check if compaction_role column exists (only in databases with compaction support)
    with _connect() as conn:
        columns = conn.execute("PRAGMA table_info(memories)").fetchall()
        has_compaction = any(col[1] == "compaction_role" for col in columns)
    
    if has_compaction:
        clauses.append("(compaction_role IS NULL OR compaction_role != 'source')")

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
        raise ValueError(
            f"context_type must be one of: {', '.join(sorted(_CONTEXT_TYPES))}"
        )

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
        raise ValueError(
            f"context_type must be one of: {', '.join(sorted(_CONTEXT_TYPES))}"
        )
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
            cur = conn.execute(
                "DELETE FROM memories WHERE session_name = ?", (session,)
            )
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
        cur = conn.execute(
            "DELETE FROM sessions WHERE session_name = ?", (session_name,)
        )
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


# ==================== Compaction Functions ====================


def list_memories_for_compaction(
    session: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List memories eligible for compaction (excludes compacted sources and summaries)."""
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    clauses: List[str] = ["compaction_role IS NULL"]
    params: List[Any] = []

    if session:
        clauses.append("session_name = ?")
        params.append(session)

    where = f"WHERE {' AND '.join(clauses)}"

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


def _validate_memory_ids(memory_ids: List[str]) -> None:
    """Validate that all memory IDs are safe strings (allowing test IDs)."""
    for mid in memory_ids:
        if not mid or not isinstance(mid, str):
            raise ValueError(f"Invalid memory ID format: {mid}")
        # Allow alphanumeric, hyphens, and underscores (covers UUIDs and test IDs)
        if not re.match(r'^[a-zA-Z0-9_-]+$', mid):
            raise ValueError(f"Invalid memory ID format: {mid}")


def _generate_summary_fallback(memories: List[Dict[str, Any]]) -> str:
    """Generate a simple summary by extracting first sentences from memories."""
    sentences = []
    for mem in memories[:5]:  # Limit to first 5 memories
        content = mem["content"].strip()
        # Extract first sentence (naive approach)
        match = re.match(r"^[^.!?]+[.!?]", content)
        if match:
            sentences.append(match.group(0))
        else:
            # No sentence ending found, take first 100 chars
            sentences.append((content[:100] + "…") if len(content) > 100 else content)
    return " ".join(sentences)


def generate_compaction_preview(memory_ids: List[str]) -> Dict[str, Any]:
    """Generate preview of compacting selected memories with token savings estimate."""
    _validate_memory_ids(memory_ids)

    with _connect() as conn:
        placeholders = ",".join("?" * len(memory_ids))
        rows = conn.execute(
            f"""
            SELECT id, session_name, content, timestamp
            FROM memories
            WHERE id IN ({placeholders})
            ORDER BY timestamp ASC
            """,
            memory_ids,
        ).fetchall()

    if not rows:
        raise ValueError("No memories found for the provided IDs")

    memories = [
        {
            "id": row["id"],
            "session_name": row["session_name"],
            "content": row["content"] or "",
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]

    # Generate fallback summary
    summary = _generate_summary_fallback(memories)

    # Calculate token savings estimate (rough approximation: 4 chars per token)
    total_chars = sum(len(m["content"]) for m in memories)
    summary_chars = len(summary)
    savings_pct = (
        round((1 - summary_chars / total_chars) * 100) if total_chars > 0 else 0
    )

    return {
        "source_count": len(memories),
        "summary": summary,
        "token_savings_estimate": f"{savings_pct}%",
        "sources_preview": [
            {
                "id": m["id"],
                "preview": (m["content"][:100] + "…")
                if len(m["content"]) > 100
                else m["content"],
            }
            for m in memories
        ],
    }


def apply_manual_compaction(
    memory_ids: List[str], summary_content: str, session_name: str
) -> str:
    """
    Apply manual compaction: create summary memory, mark sources as compacted,
    and create staging record for tracking.
    """
    _validate_memory_ids(memory_ids)

    if not summary_content.strip():
        raise ValueError("Summary content cannot be empty")
    if not session_name.strip():
        raise ValueError("Session name is required")

    # Verify all memories belong to the same session
    with _connect() as conn:
        placeholders = ",".join("?" * len(memory_ids))
        sessions = conn.execute(
            f"""
            SELECT DISTINCT session_name
            FROM memories
            WHERE id IN ({placeholders})
            """,
            memory_ids,
        ).fetchall()

        if len(sessions) == 0:
            raise ValueError("No memories found for the provided IDs")
        if len(sessions) > 1:
            raise ValueError(
                "Cannot compact memories from different sessions. All memories must belong to the same session."
            )
        if sessions[0][0] != session_name.strip():
            raise ValueError(
                f"Memories belong to session '{sessions[0][0]}', not '{session_name}'"
            )

    # Create summary memory
    summary_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    sanitized_summary = _sanitize_memory(summary_content.strip())
    embedding = _maybe_embedding(sanitized_summary)

    with _connect() as conn:
        # Insert summary memory
        conn.execute(
            """
            INSERT INTO memories (id, session_name, content, embedding, timestamp, context_type, metadata, compaction_role)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary_id,
                session_name.strip(),
                sanitized_summary,
                embedding,
                timestamp,
                "general",
                "{}",
                "summary",
            ),
        )

        # Mark source memories as compacted
        conn.execute(
            f"""
            UPDATE memories
            SET compaction_role = 'source',
                compacted_into = ?
            WHERE id IN ({placeholders})
            """,
            [summary_id, *memory_ids],
        )

        # Create staging record for tracking (manual compaction goes straight to 'applied')
        staging_id = str(uuid.uuid4())
        expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        conn.execute(
            """
            INSERT INTO compaction_staging (
                id, session_name, source_memory_ids, preview, suggested_summary,
                status, candidate_hash, source_updated_at_snapshot, expires_at,
                created_at, updated_at, reviewed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                staging_id,
                session_name.strip(),
                json.dumps([summary_id]),  # Store summary_id for manual compactions
                "Manual compaction",
                sanitized_summary,
                "applied",
                "manual-" + str(uuid.uuid4())[:8],
                "{}",
                expires_at,
                timestamp,
                timestamp,
                timestamp,
            ),
        )

        _touch_session(conn, session_name.strip(), timestamp)
        conn.commit()

    return summary_id


def get_compaction_summary() -> Dict[str, int]:
    """Get counts of compaction candidates grouped by status."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) as count
            FROM compaction_staging
            GROUP BY status
            """
        ).fetchall()

    # Initialize all statuses to 0
    summary = {
        "pending_summary": 0,
        "summary_staged": 0,
        "applied": 0,
        "stale": 0,
        "discarded": 0,
    }

    # Update with actual counts
    for row in rows:
        status = row["status"]
        count = row["count"]
        if status in summary:
            summary[status] = count

    return summary


def list_compaction_candidates(
    session: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List compaction candidates with optional filters."""
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    clauses: List[str] = []
    params: List[Any] = []

    if session:
        clauses.append("session_name = ?")
        params.append(session)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with _connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM compaction_staging {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT id, session_name, source_memory_ids, preview, suggested_summary,
                   status, created_at, updated_at, reviewed_at, nudge_count
            FROM compaction_staging
            {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    items = []
    for row in rows:
        # Parse source_memory_ids JSON
        try:
            source_ids = json.loads(row["source_memory_ids"])
            if not isinstance(source_ids, list):
                source_ids = []
        except (json.JSONDecodeError, TypeError):
            source_ids = []

        items.append(
            {
                "id": row["id"],
                "session_name": row["session_name"],
                "source_memory_ids": source_ids,
                "source_count": len(source_ids),
                "preview": row["preview"],
                "suggested_summary": row["suggested_summary"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "reviewed_at": row["reviewed_at"],
                "nudge_count": row["nudge_count"],
            }
        )

    return {"total": total, "limit": limit, "offset": offset, "items": items}


def discard_compaction_candidate(candidate_id: str) -> bool:
    """Mark a compaction candidate as discarded."""
    timestamp = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE compaction_staging
            SET status = 'discarded',
                reviewed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, candidate_id),
        )
        conn.commit()
        return cur.rowcount > 0
