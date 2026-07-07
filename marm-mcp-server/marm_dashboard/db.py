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
        import fastembed  # noqa: F401

        return True
    except ImportError:
        return False


def _maybe_embedding(text: str) -> Optional[bytes]:
    global _ENCODER, _ENCODER_FAILED
    if _ENCODER_FAILED or not text.strip():
        return None
    try:
        if _ENCODER is None:
            from fastembed import TextEmbedding

            _ENCODER = TextEmbedding(
                model_name=f"sentence-transformers/{_SEMANTIC_MODEL}"
            )
        import numpy as np

        return next(iter(_ENCODER.embed([text]))).astype(np.float32).tobytes()
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

    # Exclude compacted source memories
    clauses.append("(compaction_role IS NULL OR compaction_role != 'source')")

    if session:
        clauses.append("session_name = ?")
        params.append(session)
    if q:
        clauses.append("content LIKE ? ESCAPE '\\'")
        params.append(_like_pattern(q))

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


# ==================== Compaction (Phase 1: Manual) ====================

# UUID validation pattern
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _validate_memory_ids(memory_ids: List[str]) -> None:
    """Validate that all provided IDs are valid UUIDs to prevent SQL injection."""
    for mem_id in memory_ids:
        if not _UUID_PATTERN.match(mem_id):
            raise ValueError(f"Invalid memory ID format: {mem_id}")


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
            SELECT id, session_name, content, timestamp, context_type, created_at
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
        preview = (raw[:150] + "…") if len(raw) > 150 else raw
        items.append(
            {
                "id": row["id"],
                "session_name": row["session_name"],
                "content": raw,
                "display_content": _for_display(raw),
                "timestamp": row["timestamp"],
                "context_type": row["context_type"],
                "created_at": row["created_at"],
                "preview": preview,
                "display_preview": _for_display(preview),
            }
        )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def generate_compaction_preview(memory_ids: List[str]) -> Dict[str, Any]:
    """Generate a preview of compacting selected memories."""
    if not memory_ids:
        raise ValueError("At least one memory ID required")
    if len(memory_ids) > 50:
        raise ValueError("Cannot compact more than 50 memories at once")

    # Validate UUIDs to prevent SQL injection
    _validate_memory_ids(memory_ids)

    with _connect() as conn:
        placeholders = ",".join("?" * len(memory_ids))
        rows = conn.execute(
            f"""
            SELECT id, session_name, content, timestamp
            FROM memories
            WHERE id IN ({placeholders})
              AND (compaction_role IS NULL OR compaction_role != 'source')
            ORDER BY timestamp ASC
            """,
            memory_ids,
        ).fetchall()

    if not rows:
        raise ValueError("No valid memories found for compaction")

    # Validate all from same session
    sessions = set(r["session_name"] for r in rows)
    if len(sessions) > 1:
        raise ValueError("All memories must be from the same session")

    # Build preview text
    source_texts = [r["content"] for r in rows if r["content"]]
    combined_text = "\n\n".join(source_texts)

    # Simple summary generation (token counting estimate)
    total_chars = len(combined_text)
    estimated_tokens_before = total_chars // 4  # rough estimate

    # Generate summary using LLM (if available) or fallback
    try:
        summary = _generate_summary_llm(source_texts)
        estimated_tokens_after = len(summary) // 4
    except Exception:
        # Fallback: extract first sentence from each memory
        summary = _generate_summary_fallback(source_texts)
        estimated_tokens_after = len(summary) // 4

    savings_pct = round(
        (1 - estimated_tokens_after / estimated_tokens_before) * 100
        if estimated_tokens_before > 0
        else 0
    )

    return {
        "summary": summary,
        "source_count": len(rows),
        "source_memory_ids": [r["id"] for r in rows],
        "session_name": rows[0]["session_name"],
        "token_savings_estimate": f"~{savings_pct}%",
        "original_char_count": total_chars,
        "summary_char_count": len(summary),
        "sources_preview": [
            {
                "id": r["id"],
                "content": r["content"][:200]
                + ("…" if len(r["content"]) > 200 else ""),
                "timestamp": r["timestamp"],
            }
            for r in rows
        ],
    }


def _generate_summary_llm(texts: List[str]) -> str:
    """Generate summary using sentence-transformers semantic model (if available)."""
    # For now, use a simple extractive summary
    # TODO: Add LLM call for better summaries in Phase 1.1
    return _generate_summary_fallback(texts)


def _generate_summary_fallback(texts: List[str]) -> str:
    """Fallback summary: concatenate first 2 sentences from each memory.

    Note: Uses naive sentence splitting which may not work well for code blocks,
    URLs, or technical content with abbreviations. Consider this a basic fallback
    when LLM summarization is unavailable.
    """
    summary_parts = []
    for text in texts[:10]:  # Limit to first 10 for brevity
        # Extract first 2 sentences (naive split on ., !, ?)
        # This may break on code, URLs, abbreviations - document known limitation
        sentences = re.split(r"[.!?]+", text.strip())
        first_two = ". ".join(s.strip() for s in sentences[:2] if s.strip())
        if first_two:
            summary_parts.append(first_two)

    summary = " | ".join(summary_parts)

    # Cap at 1000 chars
    if len(summary) > 1000:
        summary = summary[:1000] + "…"

    return summary or "Summary of selected memories."


def apply_manual_compaction(
    memory_ids: List[str],
    summary_content: str,
    session_name: str,
) -> str:
    """Apply manual compaction: create summary memory, mark sources as compacted."""
    if not memory_ids:
        raise ValueError("At least one memory ID required")
    if not summary_content.strip():
        raise ValueError("Summary content cannot be empty")
    if not session_name.strip():
        raise ValueError("Session name required")

    # Validate UUIDs to prevent SQL injection
    _validate_memory_ids(memory_ids)

    sanitized_summary = _sanitize_memory(summary_content.strip())
    summary_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    embedding = _maybe_embedding(sanitized_summary)

    # Compute candidate hash for staging record
    import hashlib

    sorted_ids = sorted(memory_ids)
    candidate_hash = hashlib.sha256("|".join(sorted_ids).encode("utf-8")).hexdigest()[
        :16
    ]

    with _connect() as conn:
        # Verify all sources exist and are not already compacted
        placeholders = ",".join("?" * len(memory_ids))
        sources = conn.execute(
            f"""
            SELECT id, session_name, content, timestamp
            FROM memories
            WHERE id IN ({placeholders})
              AND (compaction_role IS NULL OR compaction_role != 'source')
            """,
            memory_ids,
        ).fetchall()

        if len(sources) != len(memory_ids):
            raise ValueError("Some memories not found or already compacted")

        # Validate all from same session
        sessions = set(r["session_name"] for r in sources)
        if len(sessions) > 1:
            raise ValueError("All memories must be from the same session")

        # Insert summary memory
        conn.execute(
            """
            INSERT INTO memories
                (id, session_name, content, embedding, timestamp,
                 context_type, metadata, compaction_role, created_at)
            VALUES (?, ?, ?, ?, ?, 'general', '{}', 'summary', ?)
            """,
            (summary_id, session_name.strip(), sanitized_summary, embedding, now, now),
        )

        # Mark sources as compacted
        for mem_id in memory_ids:
            conn.execute(
                """
                UPDATE memories
                SET compaction_role = 'source', compacted_into = ?
                WHERE id = ?
                """,
                (summary_id, mem_id),
            )

        # Create staging record (status='applied')
        source_snapshot = json.dumps(
            {
                row["id"]: {
                    "content": row["content"][:100],
                    "timestamp": row["timestamp"],
                }
                for row in sources
            }
        )

        preview_data = json.dumps(
            [{"id": row["id"], "snippet": row["content"][:100]} for row in sources]
        )

        conn.execute(
            """
            INSERT INTO compaction_staging
                (id, session_name, source_memory_ids, preview, suggested_summary,
                 status, candidate_hash, source_updated_at_snapshot,
                 expires_at, created_at, updated_at, reviewed_at)
            VALUES (?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                session_name.strip(),
                json.dumps(sorted_ids),
                preview_data,
                sanitized_summary,
                candidate_hash,
                source_snapshot,
                now,  # expires_at (not relevant for applied)
                now,  # created_at
                now,  # updated_at
                now,  # reviewed_at
            ),
        )

        conn.commit()

    return summary_id


# ==================== Maintenance (Phase 2) ====================


def get_compaction_summary() -> Dict[str, int]:
    """Get counts by compaction status for dashboard overview."""
    conn = _connect()

    counts = {
        "pending_summary": 0,
        "summary_staged": 0,
        "applied": 0,
        "discarded": 0,
        "stale": 0,
        "nudge_exhausted": 0,
    }

    rows = conn.execute("""
        SELECT status, COUNT(*) as count
        FROM compaction_staging
        GROUP BY status
    """).fetchall()

    for row in rows:
        status = row["status"]
        count = row["count"]
        if status in counts:
            counts[status] = count

    return counts


def list_compaction_candidates(
    session: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List compaction candidates with optional filters."""
    conn = _connect()

    where_clauses = []
    params: List[Any] = []

    if session:
        where_clauses.append("session_name = ?")
        params.append(session)

    if status:
        where_clauses.append("status = ?")
        params.append(status)

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    # Get total count
    count_query = f"SELECT COUNT(*) as total FROM compaction_staging{where_sql}"
    total = conn.execute(count_query, params).fetchone()["total"]

    # Get paginated items
    query = f"""
        SELECT
            id,
            session_name,
            source_memory_ids,
            preview,
            suggested_summary,
            status,
            created_at,
            updated_at,
            expires_at,
            nudge_count,
            last_nudged_at
        FROM compaction_staging
        {where_sql}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()

    items = []
    for row in rows:
        # Parse source_memory_ids JSON safely
        try:
            source_ids = json.loads(row["source_memory_ids"])
        except (json.JSONDecodeError, TypeError):
            source_ids = []

        items.append(
            {
                "id": row["id"],
                "session_name": row["session_name"],
                "source_memory_ids": source_ids,
                "source_count": len(source_ids),
                "preview": row["preview"][:200] if row["preview"] else "",
                "suggested_summary": row["suggested_summary"][:200]
                if row["suggested_summary"]
                else None,
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "expires_at": row["expires_at"],
                "nudge_count": row["nudge_count"],
                "last_nudged_at": row["last_nudged_at"],
            }
        )

    return {"total": total, "items": items}


def discard_compaction_candidate(candidate_id: str) -> bool:
    """Mark a compaction candidate as discarded."""
    # Validate UUID format
    try:
        uuid.UUID(candidate_id)
    except ValueError:
        return False

    conn = _connect()
    now = datetime.now(timezone.utc).isoformat()

    cursor = conn.execute(
        """
        UPDATE compaction_staging
        SET status = 'discarded', reviewed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, now, candidate_id),
    )

    conn.commit()
    return cursor.rowcount > 0
