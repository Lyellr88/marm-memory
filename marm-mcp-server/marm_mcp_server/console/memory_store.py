"""Read-only SQLite queries used by MARM Console's initial overview."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


class MemoryStoreUnavailable(RuntimeError):
    """The MARM memory store has not been initialized yet."""


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise MemoryStoreUnavailable(
            f"MARM memory database was not found at {db_path}. Start marm-mcp-server first."
        )
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _concept_db_path() -> Path:
    configured = os.environ.get("MARM_CONCEPT_DB_PATH")
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".marm" / "index" / "marm_index.db"
    )


def _concept_link_counts(memory_ids: list[str]) -> dict[str, int]:
    if not memory_ids:
        return {}
    db_path = _concept_db_path()
    if not db_path.exists():
        return {}

    counts = dict.fromkeys(memory_ids, 0)
    try:
        with closing(sqlite3.connect(db_path)) as connection, connection:
            for memory_id, count in connection.execute(
                """
                SELECT memory_id, COUNT(*)
                FROM relationships
                WHERE memory_id IN (SELECT value FROM json_each(?))
                GROUP BY memory_id
                """,
                (json.dumps(memory_ids),),
            ).fetchall():
                counts[str(memory_id)] = counts.get(str(memory_id), 0) + count

            for memory_id, count in connection.execute(
                """
                SELECT CAST(source.value AS TEXT), COUNT(DISTINCT e.id)
                FROM entities e, json_each(e.source_memory_ids) AS source
                WHERE json_valid(e.source_memory_ids)
                  AND CAST(source.value AS TEXT) IN (SELECT value FROM json_each(?))
                GROUP BY CAST(source.value AS TEXT)
                """,
                (json.dumps(memory_ids),),
            ).fetchall():
                counts[str(memory_id)] = counts.get(str(memory_id), 0) + count
    except sqlite3.Error:
        return {}

    return counts


def overview(db_path: Path) -> dict:
    with closing(_connect(db_path)) as connection, connection:
        active_memories = connection.execute(
            "SELECT COUNT(*) FROM memories WHERE compaction_role IS NULL OR compaction_role != 'source'"
        ).fetchone()[0]
        compacted_sources = connection.execute(
            "SELECT COUNT(*) FROM memories WHERE compaction_role = 'source'"
        ).fetchone()[0]
        missing_embeddings = connection.execute(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NULL"
        ).fetchone()[0]
        sessions = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        log_entries = connection.execute("SELECT COUNT(*) FROM log_entries").fetchone()[
            0
        ]
        notebook_entries = connection.execute(
            "SELECT COUNT(*) FROM notebook_entries"
        ).fetchone()[0]
        pending_compaction = connection.execute(
            "SELECT COUNT(*) FROM compaction_staging WHERE status IN ('pending_summary', 'ready')"
        ).fetchone()[0]
        staged_compaction = connection.execute(
            "SELECT COUNT(*) FROM compaction_staging WHERE status = 'staged'"
        ).fetchone()[0]
        projects = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT project FROM memories WHERE project IS NOT NULL AND project != '' ORDER BY project COLLATE NOCASE"
            )
        ]
        platforms = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT platform FROM memories WHERE platform IS NOT NULL AND platform != '' ORDER BY platform COLLATE NOCASE"
            )
        ]
    return {
        "active_memories": active_memories,
        "compacted_sources": compacted_sources,
        "pending_compaction": pending_compaction,
        "staged_compaction": staged_compaction,
        "missing_embeddings": missing_embeddings,
        "sessions": sessions,
        "log_entries": log_entries,
        "notebook_entries": notebook_entries,
        "projects": projects,
        "platforms": platforms,
    }


def filters(db_path: Path) -> dict:
    with closing(_connect(db_path)) as connection, connection:
        sessions = [
            row[0]
            for row in connection.execute(
                """
                SELECT session_name FROM sessions
                UNION
                SELECT DISTINCT session_name FROM memories
                ORDER BY session_name COLLATE NOCASE
                """
            )
            if row[0]
        ]
        projects = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT project FROM memories WHERE project IS NOT NULL AND project != '' ORDER BY project COLLATE NOCASE"
            )
        ]
        platforms = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT platform FROM memories WHERE platform IS NOT NULL AND platform != '' ORDER BY platform COLLATE NOCASE"
            )
        ]
        context_types = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT context_type FROM memories WHERE context_type IS NOT NULL AND context_type != '' ORDER BY context_type COLLATE NOCASE"
            )
        ]
    return {
        "sessions": sessions,
        "projects": projects,
        "platforms": platforms,
        "context_types": context_types,
    }


def list_memories(
    db_path: Path,
    *,
    q: str | None = None,
    session: str | None = None,
    project: str | None = None,
    platform: str | None = None,
    context_type: str | None = None,
    compaction_role: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    clauses: list[str] = []
    params: list[object] = []
    if compaction_role is None:
        clauses.append("(compaction_role IS NULL OR compaction_role != 'source')")
    elif compaction_role == "none":
        clauses.append("(compaction_role IS NULL OR compaction_role = 'none')")
    elif compaction_role == "compacted":
        clauses.append("compaction_role = 'source'")
    else:
        clauses.append("compaction_role = ?")
        params.append(compaction_role)
    for column, value in (
        ("session_name", session),
        ("project", project),
        ("platform", platform),
        ("context_type", context_type),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if q:
        clauses.append("content LIKE ? ESCAPE '\\'")
        params.append(
            "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(_connect(db_path)) as connection, connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM memories{where}", params
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT m.id, m.content, m.session_name, m.project, m.platform,
                   m.context_type, m.metadata, m.content_hash, m.created_at,
                   m.compaction_role, m.embedding,
                   (SELECT COUNT(*) FROM memory_chunks c WHERE c.memory_id = m.id) AS chunk_count
            FROM memories m{where}
            ORDER BY m.timestamp DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    concept_counts = _concept_link_counts([str(row["id"]) for row in rows])
    items = [
        {
            "id": row["id"],
            "content": row["content"],
            "session_name": row["session_name"],
            "project": row["project"],
            "platform": row["platform"],
            "context_type": row["context_type"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
            "content_hash": row["content_hash"] or "",
            "created_at": row["created_at"],
            "compaction_role": row["compaction_role"] or "none",
            "chunk_count": row["chunk_count"],
            "has_embedding": row["embedding"] is not None,
            "concept_link_count": concept_counts.get(str(row["id"]), 0),
        }
        for row in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def get_memory(db_path: Path, memory_id: str) -> dict | None:
    with closing(_connect(db_path)) as connection, connection:
        row = connection.execute(
            """
            SELECT m.id, m.content, m.session_name, m.project, m.platform,
                   m.context_type, m.metadata, m.content_hash, m.created_at,
                   m.compaction_role, m.embedding,
                   (SELECT COUNT(*) FROM memory_chunks c WHERE c.memory_id = m.id) AS chunk_count
            FROM memories m WHERE m.id = ?
            """,
            (memory_id,),
        ).fetchone()
    if row is None:
        return None
    concept_counts = _concept_link_counts([str(row["id"])])
    return {
        "id": row["id"],
        "content": row["content"],
        "session_name": row["session_name"],
        "project": row["project"],
        "platform": row["platform"],
        "context_type": row["context_type"],
        "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
        "content_hash": row["content_hash"] or "",
        "created_at": row["created_at"],
        "compaction_role": row["compaction_role"] or "none",
        "chunk_count": row["chunk_count"],
        "has_embedding": row["embedding"] is not None,
        "concept_link_count": concept_counts.get(str(row["id"]), 0),
    }


def get_memories_by_ids(
    db_path: Path, memory_ids: list[str], limit: int = 50
) -> list[dict]:
    ids = list(dict.fromkeys(memory_ids))[: min(max(limit, 1), 50)]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with closing(_connect(db_path)) as connection, connection:
        rows = connection.execute(
            f"""SELECT id, content, session_name, project, created_at
                FROM memories WHERE id IN ({placeholders})""",
            ids,
        ).fetchall()
    by_id = {
        str(row["id"]): {
            "id": row["id"],
            "content": row["content"],
            "session_name": row["session_name"],
            "project": row["project"],
            "created_at": row["created_at"],
        }
        for row in rows
    }
    return [by_id[memory_id] for memory_id in ids if memory_id in by_id]


def list_sessions(db_path: Path) -> list[dict]:
    with closing(_connect(db_path)) as connection, connection:
        rows = connection.execute(
            """
            SELECT s.session_name, s.marm_active, s.created_at, s.last_accessed,
                   COUNT(DISTINCT m.id) AS memory_count,
                   COUNT(DISTINCT l.id) AS log_count,
                   COUNT(DISTINCT c.id) AS compaction_count
            FROM sessions s
            LEFT JOIN memories m ON m.session_name = s.session_name
            LEFT JOIN log_entries l ON l.session_name = s.session_name
            LEFT JOIN compaction_staging c ON c.session_name = s.session_name
            GROUP BY s.session_name
            ORDER BY s.last_accessed DESC
            """
        ).fetchall()
        return [
            {
                "name": row["session_name"],
                "active": bool(row["marm_active"]),
                "created_at": row["created_at"],
                "last_accessed_at": row["last_accessed"],
                "memory_count": row["memory_count"],
                "log_count": row["log_count"],
                "compaction_count": row["compaction_count"],
                "projects": [
                    item[0]
                    for item in connection.execute(
                        "SELECT DISTINCT project FROM memories WHERE session_name = ? AND project IS NOT NULL AND project != ''",
                        (row["session_name"],),
                    )
                ],
                "platforms": [
                    item[0]
                    for item in connection.execute(
                        "SELECT DISTINCT platform FROM memories WHERE session_name = ? AND platform IS NOT NULL AND platform != ''",
                        (row["session_name"],),
                    )
                ],
            }
            for row in rows
        ]


def list_logs(
    db_path: Path,
    *,
    q: str | None,
    session: str | None,
    limit: int,
    offset: int,
) -> dict:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    clauses: list[str] = []
    params: list[object] = []
    if session:
        clauses.append("session_name = ?")
        params.append(session)
    if q:
        clauses.append(
            "(topic LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' OR full_entry LIKE ? ESCAPE '\\')"
        )
        escaped = (
            "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        params.extend((escaped, escaped, escaped))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(_connect(db_path)) as connection, connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM log_entries{where}", params
        ).fetchone()[0]
        rows = connection.execute(
            f"""SELECT id, entry_date, topic, summary, full_entry, session_name, project, platform
                FROM log_entries{where} ORDER BY entry_date DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    items = [
        {
            "id": row["id"],
            "date": row["entry_date"],
            "topic": row["topic"],
            "summary": row["summary"],
            "entry": row["full_entry"],
            "session_name": row["session_name"],
            "project": row["project"],
            "platform": row["platform"],
        }
        for row in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def list_log_refs(db_path: Path) -> list[dict]:
    with closing(_connect(db_path)) as connection, connection:
        rows = connection.execute(
            "SELECT id, session_name FROM log_entries ORDER BY entry_date DESC"
        ).fetchall()
    return [{"id": str(row["id"]), "session_name": row["session_name"]} for row in rows]


def list_notebook(db_path: Path) -> list[dict]:
    with closing(_connect(db_path)) as connection, connection:
        rows = connection.execute(
            "SELECT name, data, session_name, project, platform, created_at, updated_at "
            "FROM notebook_entries ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {
            "name": row["name"],
            "content": row["data"],
            "session_name": row["session_name"],
            "project": row["project"],
            "platform": row["platform"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def get_summary(db_path: Path, session_name: str) -> dict:
    with closing(_connect(db_path)) as connection, connection:
        row = connection.execute(
            """SELECT summary_text, entry_count, dirty, updated_at
               FROM session_summary_cache WHERE session_name = ?""",
            (session_name,),
        ).fetchone()
    return {
        "session_name": session_name,
        "summary": row["summary_text"] if row else "",
        "entry_count": row["entry_count"] if row else 0,
        "is_dirty": bool(row["dirty"]) if row else False,
        "generated_at": row["updated_at"] if row else None,
    }


def _compaction_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "status": _console_compaction_status(row["status"]),
        "session_name": row["session_name"],
        "source_memory_ids": json.loads(row["source_memory_ids"]),
        "proposed_summary": row["suggested_summary"] or "Summary pending",
        "expected_reduction": 0,
        "expiry": row["expires_at"],
        "created_at": row["created_at"],
    }


def list_compaction(db_path: Path) -> list[dict]:
    with closing(_connect(db_path)) as connection, connection:
        rows = connection.execute(
            """SELECT id, status, session_name, source_memory_ids, suggested_summary, expires_at, created_at
               FROM compaction_staging ORDER BY created_at DESC LIMIT 200"""
        ).fetchall()
    return [_compaction_row_to_dict(row) for row in rows]


def get_compaction_candidate(db_path: Path, candidate_id: str) -> dict | None:
    """Direct by-ID lookup, unlike list_compaction's 200-row window."""
    with closing(_connect(db_path)) as connection, connection:
        row = connection.execute(
            """SELECT id, status, session_name, source_memory_ids, suggested_summary, expires_at, created_at
               FROM compaction_staging WHERE id = ?""",
            (candidate_id,),
        ).fetchone()
    return _compaction_row_to_dict(row) if row else None


def _console_compaction_status(status: str) -> str:
    return {"pending_summary": "pending", "ready": "pending"}.get(status, status)
