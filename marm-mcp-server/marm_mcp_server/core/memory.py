"""Advanced memory system with semantic search and MARM protocol support."""

import asyncio
import importlib.util
import json
import math
import os
import sqlite3
import sys
import threading
import uuid
import queue
from datetime import datetime, timezone
from typing import List, Dict, Optional
import numpy as np
import html
import re


def _safe_print(msg: str) -> None:
    """Write diagnostics to stderr so STDIO stdout stays JSON-RPC clean."""
    stderr_buffer = getattr(sys.stderr, "buffer", None)
    if stderr_buffer is not None:
        stderr_buffer.write((msg + "\n").encode("utf-8", errors="replace"))
        stderr_buffer.flush()
    else:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()


_RECALL_DEBUG = os.environ.get("MARM_RECALL_DEBUG", "0") == "1"


def _recall_debug(msg: str) -> None:
    """Lightweight debug logging for recall-path observability.

    Only emits when MARM_RECALL_DEBUG=1. Writes to stderr to keep
    STDIO stdout JSON-RPC clean.
    """
    if _RECALL_DEBUG:
        _safe_print(f"[recall-debug] {msg}")


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


def _temporal_score(timestamp: str, half_life_days: float) -> float:
    """Return a recency score in [0, 1]: 1.0 for brand-new, 0.5 at half_life_days."""
    try:
        ts = datetime.fromisoformat(timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
        return min(1.0, math.exp(-age_days * math.log(2) / half_life_days))
    except Exception:
        return 0.5


def _safe_fts_query(query: str) -> str | None:
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return None
    return " ".join(f'"{t}"' for t in tokens)


CHUNK_TOKEN_LIMIT = 150
CHUNK_OVERLAP_TOKENS = 50
CHUNK_THRESHOLD_WORDS = 180


def _chunk_text(text: str) -> list[str]:
    words = text.split()
    if len(words) <= CHUNK_THRESHOLD_WORDS:
        return []
    step = CHUNK_TOKEN_LIMIT - CHUNK_OVERLAP_TOKENS
    chunks = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + CHUNK_TOKEN_LIMIT]))
        i += step
    return chunks


async def _write_chunks(
    mem_instance, db_path: str, memory_id: str, chunks: list[str]
) -> None:
    embeddings = []
    for chunk in chunks:
        try:
            vec = await asyncio.to_thread(mem_instance._encode_sync, chunk)
            embeddings.append(vec.tobytes())
        except Exception as e:
            _safe_print(f"Chunk encoding failed for memory {memory_id}: {e}")
            return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executemany(
            "INSERT INTO memory_chunks (memory_id, chunk_index, chunk_text, embedding)"
            " VALUES (?, ?, ?, ?)",
            [
                (memory_id, i, chunk, emb)
                for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _score_embedding_rows(rows, query_embedding, limit: int):
    """Score embedding rows in one NumPy batch instead of a Python cosine loop."""
    if limit <= 0:
        return [], 0

    query_vec = np.asarray(query_embedding, dtype=np.float32)
    expected_dim = query_vec.shape[0]
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return [], 0
    normalized_query = query_vec / query_norm

    vectors = []
    kept_rows = []
    dim_skipped = 0

    for row in rows:
        try:
            vector = np.frombuffer(row[3], dtype=np.float32)
        except Exception:
            continue
        if vector.shape[0] != expected_dim:
            dim_skipped += 1
            continue
        vectors.append(vector)
        kept_rows.append(row)

    if not vectors:
        return [], dim_skipped

    matrix = np.vstack(vectors).astype(np.float32, copy=False)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / (norms + 1e-12)
    scores = matrix @ normalized_query

    top_count = min(limit, scores.shape[0])
    if top_count == 0:
        return [], dim_skipped

    top_indices = np.argpartition(scores, -top_count)[-top_count:]
    top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
    return [
        (kept_rows[index], float(scores[index])) for index in top_indices
    ], dim_skipped


def _score_chunk_aware(
    memories,
    chunks_by_id: dict,
    query_embedding,
) -> tuple[list[tuple], int]:
    """Score memories using chunk embeddings where available, parent embedding otherwise.

    Deduplicates to one (memory_row, best_score) per memory_id before returning.
    """
    query_vec = np.asarray(query_embedding, dtype=np.float32)
    expected_dim = query_vec.shape[0]
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return [], 0
    normalized_query = query_vec / query_norm

    dim_skipped = 0
    results = []

    for mem in memories:
        mem_id = mem["id"]
        chunk_embs = chunks_by_id.get(mem_id)

        if chunk_embs:
            best_score = None
            for emb_bytes in chunk_embs:
                try:
                    vec = np.frombuffer(emb_bytes, dtype=np.float32)
                except Exception:
                    continue
                if vec.shape[0] != expected_dim:
                    dim_skipped += 1
                    continue
                norm = np.linalg.norm(vec)
                if norm == 0:
                    continue
                score = float(np.dot(vec / norm, normalized_query))
                if best_score is None or score > best_score:
                    best_score = score
            if best_score is not None:
                results.append((mem, best_score))
        else:
            emb_bytes = mem["embedding"]
            if emb_bytes is None:
                continue
            try:
                vec = np.frombuffer(emb_bytes, dtype=np.float32)
            except Exception:
                continue
            if vec.shape[0] != expected_dim:
                dim_skipped += 1
                continue
            norm = np.linalg.norm(vec)
            if norm == 0:
                continue
            results.append((mem, float(np.dot(vec / norm, normalized_query))))

    results.sort(key=lambda x: x[1], reverse=True)
    return results, dim_skipped


def _fetch_and_score_embedding_rows(
    db_path: str,
    session: str | None,
    scan_limit: int,
    query_embedding,
    limit: int,
):
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        if session is None:
            memories = conn.execute(
                """
                SELECT id, session_name, content, embedding, timestamp, context_type, metadata
                FROM memories
                WHERE embedding IS NOT NULL
                  AND (compaction_role IS NULL OR compaction_role != 'source')
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (scan_limit + 1,),
            ).fetchall()
        else:
            memories = conn.execute(
                """
                SELECT id, session_name, content, embedding, timestamp, context_type, metadata
                FROM memories
                WHERE embedding IS NOT NULL
                  AND session_name = ?
                  AND (compaction_role IS NULL OR compaction_role != 'source')
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session, scan_limit + 1),
            ).fetchall()

        scan_truncated = len(memories) > scan_limit
        memories = memories[:scan_limit]

        chunks_by_id: dict[str, list] = {}
        if memories:
            ids = [m["id"] for m in memories]
            placeholders = ",".join("?" * len(ids))
            for row in conn.execute(
                f"SELECT memory_id, embedding FROM memory_chunks WHERE memory_id IN ({placeholders})",
                ids,
            ).fetchall():
                chunks_by_id.setdefault(row[0], []).append(row[1])
    finally:
        conn.close()

    similarities, dim_skipped = _score_chunk_aware(
        memories, chunks_by_id, query_embedding
    )
    return similarities[:limit], dim_skipped, scan_truncated


def _fetch_and_score_fts_rows(
    db_path: str,
    session: str | None,
    fts_query: str,
    limit: int,
) -> list[tuple]:
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        base = """
            SELECT m.id, m.session_name, m.content, m.timestamp,
                   m.context_type, m.metadata,
                   bm25(memories_fts) AS score
            FROM memories_fts
            JOIN memories m ON memories_fts.rowid = m.rowid
            WHERE memories_fts MATCH ?
              AND (m.compaction_role IS NULL OR m.compaction_role != 'source')
        """
        params: list = [fts_query]
        if session is not None:
            base += " AND m.session_name = ?"
            params.append(session)
        base += " ORDER BY score LIMIT ?"
        params.append(limit)
        rows = conn.execute(base, params).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    raw_scores = [row["score"] for row in rows]
    min_s, max_s = min(raw_scores), max(raw_scores)
    if max_s == min_s:
        normalized = [1.0 for _ in raw_scores]
    else:
        span = max_s - min_s
        normalized = [(max_s - s) / span for s in raw_scores]
    return list(zip(rows, normalized))


def _fetch_fts_candidate_ids(
    db_path: str,
    session: str | None,
    fts_query: str,
    limit: int,
) -> list[str]:
    """Return top N memory IDs from FTS5 by BM25 rank. No scoring needed."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        base = """
            SELECT m.id
            FROM memories_fts
            JOIN memories m ON memories_fts.rowid = m.rowid
            WHERE memories_fts MATCH ?
              AND (m.compaction_role IS NULL OR m.compaction_role != 'source')
        """
        params: list = [fts_query]
        if session is not None:
            base += " AND m.session_name = ?"
            params.append(session)
        base += " ORDER BY bm25(memories_fts) LIMIT ?"
        params.append(limit)
        rows = conn.execute(base, params).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def _fetch_and_score_by_ids(
    db_path: str,
    memory_ids: list[str],
    query_embedding,
) -> tuple[list[tuple], int]:
    """Fetch specific memories by ID and score their embeddings.

    Returns (similarities, dim_skipped). No scan_truncated -- ID-bounded
    fetch has no truncation concept.
    """
    if not memory_ids:
        return [], 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" * len(memory_ids))
        memories = conn.execute(
            f"""
            SELECT id, session_name, content, embedding, timestamp, context_type, metadata
            FROM memories
            WHERE id IN ({placeholders})
              AND (compaction_role IS NULL OR compaction_role != 'source')
            """,
            memory_ids,
        ).fetchall()

        chunks_by_id: dict[str, list] = {}
        for row in conn.execute(
            f"SELECT memory_id, embedding FROM memory_chunks WHERE memory_id IN ({placeholders})",
            memory_ids,
        ).fetchall():
            chunks_by_id.setdefault(row[0], []).append(row[1])
    finally:
        conn.close()

    return _score_chunk_aware(memories, chunks_by_id, query_embedding)


from ..config.settings import (  # noqa: E402
    SEMANTIC_SEARCH_AVAILABLE,
    DEFAULT_DB_PATH,
    MAX_DB_CONNECTIONS,
    DEFAULT_SEMANTIC_MODEL,
    MAX_QUEUE_SIZE,
    WRITE_QUEUE_ENABLED,
    CONSOLIDATION_ENABLED,
    CONSOLIDATION_THRESHOLD,
    COMPACTION_ENABLED,
    COMPACTION_TRIGGER_COUNT,
    RECALL_SCAN_LIMIT,
    TEMPORAL_WEIGHT,
    TEMPORAL_HALF_LIFE_DAYS,
    FTS_CANDIDATE_LIMIT,
)
from .consolidation import (  # noqa: E402
    compute_content_hash,
    find_exact_duplicate,
    find_semantic_duplicate,
    normalize_content,
)
from .compaction import trigger_compaction  # noqa: E402
from .write_queue import WriteQueue  # noqa: E402

if SEMANTIC_SEARCH_AVAILABLE:
    if importlib.util.find_spec("sentence_transformers") is None:
        SEMANTIC_SEARCH_AVAILABLE = False


class SQLiteConnectionPool:
    """Simple SQLite connection pool for better performance under load"""

    def __init__(self, db_path: str, max_connections: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool = queue.Queue(maxsize=max_connections)
        self.created_connections = 0
        self.lock = threading.Lock()

        self._create_initial_connections()

    def _create_initial_connections(self):
        """Create initial pool of connections"""
        for _ in range(min(2, self.max_connections)):
            self._create_connection()

    def _create_connection(self):
        """Create a new SQLite connection with optimal settings"""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=20.0,
            isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA foreign_keys=ON")

        self.pool.put(conn)
        self.created_connections += 1

    def get_connection(self):
        """Get a connection from the pool"""
        try:
            return self.pool.get(block=False)
        except queue.Empty:
            with self.lock:
                if self.created_connections < self.max_connections:
                    self._create_connection()
                    return self.pool.get(block=False)

            return self.pool.get(block=True, timeout=10)

    def return_connection(self, conn):
        """Return connection to pool"""
        try:
            self.pool.put(conn, block=False)
        except queue.Full:
            conn.close()

    def close_all(self):
        """Close all connections in the pool"""
        while not self.pool.empty():
            try:
                conn = self.pool.get(block=False)
                conn.close()
            except queue.Empty:
                break


def sanitize_content(content: str) -> str:
    """Sanitize content to prevent XSS attacks while preserving readability"""
    if not content:
        return content

    if len(content) > 10000:
        content = content[:10000]

    sanitized = content

    sanitized = _strip_script_tags(sanitized)

    sanitized = re.sub(
        r"javascript:", "blocked-protocol:", sanitized, flags=re.IGNORECASE
    )

    sanitized = re.sub(
        r'\son\w+\s*=\s*["\'][^"\']*["\']', "", sanitized, flags=re.IGNORECASE
    )

    sanitized = html.escape(sanitized)

    return sanitized


class MARMMemory:
    """Advanced memory system with semantic search and MARM protocol support"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_lock = threading.Lock()

        self.connection_pool = SQLiteConnectionPool(
            db_path, max_connections=MAX_DB_CONNECTIONS
        )

        self.encoder = None
        self._encoder_loading = False
        self._encoder_failed = False
        self._encoder_lock = threading.Lock()

        self.init_database()

        self.active_sessions = {}
        self.active_notebook_entries_by_session: dict[str, list[dict]] = {}
        self.active_log_session: str = "main"
        self._write_queue: WriteQueue | None = None
        self._session_write_counts: dict = {}
        self._pending_compaction_scans: dict = {}

    async def start_write_queue(self) -> None:
        """Start the serialized write queue when enabled."""
        if not WRITE_QUEUE_ENABLED:
            return
        if self._write_queue is None:
            self._write_queue = WriteQueue(self, max_size=MAX_QUEUE_SIZE)
        await self._write_queue.start()

    async def stop_write_queue(self) -> None:
        """Drain and stop the serialized write queue."""
        if self._write_queue is None:
            return
        await self._write_queue.stop()
        self._write_queue = None

    def _on_memory_written(self, session: str) -> None:
        """Increment compaction write counter and fire trigger when threshold is reached.

        Called on every real memory write: new inserts and Layer 2 merges.
        Layer 1 exact-duplicate skips do not call this — DB was not changed.
        If a pending scan exists for the session, cancel it (new write resets the grace window).
        """
        if not COMPACTION_ENABLED:
            return
        pending = self._pending_compaction_scans.get(session)
        if pending is not None and not pending.done():
            pending.cancel()
            self._pending_compaction_scans.pop(session, None)
            self._set_compaction_write_count(session, 0)
        count = self._increment_compaction_write_count(session)
        if count >= COMPACTION_TRIGGER_COUNT:
            trigger_compaction(self, session)

    def _get_compaction_write_count(self, session: str) -> int:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT write_count FROM compaction_session_state WHERE session_name = ?",
                (session,),
            ).fetchone()
        count = int(row[0]) if row else 0
        self._session_write_counts[session] = count
        return count

    def _set_compaction_write_count(self, session: str, count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO compaction_session_state
                    (session_name, write_count, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_name)
                DO UPDATE SET write_count = excluded.write_count,
                              updated_at = excluded.updated_at
                """,
                (session, count, now),
            )
        self._session_write_counts[session] = count

    def _increment_compaction_write_count(self, session: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO compaction_session_state
                    (session_name, write_count, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(session_name)
                DO UPDATE SET write_count = write_count + 1,
                              updated_at = excluded.updated_at
                """,
                (session, now),
            )
            row = conn.execute(
                "SELECT write_count FROM compaction_session_state WHERE session_name = ?",
                (session,),
            ).fetchone()
        count = int(row[0]) if row else 0
        self._session_write_counts[session] = count
        return count

    def get_active_notebook_entries(self, session_name: str = "main") -> list[dict]:
        """Return active notebook entries scoped to a session."""
        return self.active_notebook_entries_by_session.get(session_name, [])

    def set_active_notebook_entries(
        self, session_name: str, entries: list[dict]
    ) -> None:
        """Set active notebook entries for one session."""
        self.active_notebook_entries_by_session[session_name] = entries

    def clear_active_notebook_entries(self, session_name: str = "main") -> None:
        """Clear active notebook entries for one session."""
        self.active_notebook_entries_by_session[session_name] = []

    def remove_active_notebook_entry(self, name: str) -> None:
        """Remove a deleted notebook entry from every active session scope."""
        for session_name, entries in list(
            self.active_notebook_entries_by_session.items()
        ):
            self.active_notebook_entries_by_session[session_name] = [
                entry for entry in entries if entry.get("name") != name
            ]

    def get_connection(self):
        """Context manager for getting database connections from pool"""

        class ConnectionContext:
            def __init__(self, pool):
                self.pool = pool
                self.conn = None

            def __enter__(self):
                self.conn = self.pool.get_connection()
                return self.conn

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.conn:
                    if exc_type is None:
                        self.conn.commit()
                    else:
                        self.conn.rollback()
                    self.pool.return_connection(self.conn)

        return ConnectionContext(self.connection_pool)

    def init_database(self):
        """Initialize SQLite database with all MARM tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    session_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB,
                    timestamp TEXT NOT NULL,
                    context_type TEXT DEFAULT 'general',
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_name TEXT PRIMARY KEY,
                    marm_active BOOLEAN DEFAULT FALSE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_accessed TEXT DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT DEFAULT '{}'
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS log_entries (
                    id TEXT PRIMARY KEY,
                    session_name TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    full_entry TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS notebook_entries (
                    name TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    embedding BLOB,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS doc_index (
                    source_file TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    memory_id TEXT,
                    indexed_at TEXT NOT NULL
                )
            """)
            existing_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(doc_index)").fetchall()
            }
            if "memory_id" not in existing_cols:
                conn.execute("ALTER TABLE doc_index ADD COLUMN memory_id TEXT")

            mem_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
            }
            if "content_hash" not in mem_cols:
                conn.execute("ALTER TABLE memories ADD COLUMN content_hash TEXT")

            if "compaction_role" not in mem_cols:
                conn.execute("ALTER TABLE memories ADD COLUMN compaction_role TEXT")
            if "compacted_into" not in mem_cols:
                conn.execute("ALTER TABLE memories ADD COLUMN compacted_into TEXT")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS compaction_staging (
                    id TEXT PRIMARY KEY,
                    session_name TEXT NOT NULL,
                    source_memory_ids TEXT NOT NULL,
                    preview TEXT NOT NULL,
                    suggested_summary TEXT,
                    status TEXT NOT NULL DEFAULT 'pending_summary',
                    candidate_hash TEXT NOT NULL,
                    source_updated_at_snapshot TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    nudge_count INTEGER NOT NULL DEFAULT 0,
                    last_nudged_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS compaction_session_state (
                    session_name TEXT PRIMARY KEY,
                    write_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
            """)
            staging_cols = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(compaction_staging)"
                ).fetchall()
            }
            if "nudge_count" not in staging_cols:
                conn.execute(
                    "ALTER TABLE compaction_staging "
                    "ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0"
                )
            if "last_nudged_at" not in staging_cols:
                conn.execute(
                    "ALTER TABLE compaction_staging ADD COLUMN last_nudged_at TEXT"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_compaction_staging_session_status "
                "ON compaction_staging(session_name, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_compaction_staging_hash "
                "ON compaction_staging(candidate_hash)"
            )

            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(content, content='memories', content_rowid='rowid',
                               tokenize='porter ascii')
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS memories_ai
                    AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS memories_au
                    AFTER UPDATE OF content ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                        VALUES ('delete', old.rowid, old.content);
                    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS memories_ad
                    AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                        VALUES ('delete', old.rowid, old.content);
                END
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO memories_fts(rowid, content) "
                "SELECT rowid, content FROM memories"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_chunks_memory_id"
                " ON memory_chunks(memory_id)"
            )
            conn.commit()

    def _encode_sync(self, text: str):
        """Encode text with the shared encoder, serialized to prevent concurrent-use hangs."""
        with self._encoder_lock:
            return self.encoder.encode(text)

    def _load_encoder_lazily(self) -> bool:
        """Lazy load the semantic search model only when needed"""
        if self.encoder is not None or self._encoder_failed:
            return self.encoder is not None

        if self._encoder_loading:
            return False

        if not SEMANTIC_SEARCH_AVAILABLE:
            self._encoder_failed = True
            return False

        try:
            self._encoder_loading = True
            _safe_print(f"Loading semantic search model ({DEFAULT_SEMANTIC_MODEL})...")

            from sentence_transformers import SentenceTransformer

            self.encoder = SentenceTransformer(DEFAULT_SEMANTIC_MODEL)

            _safe_print("Semantic search model loaded successfully")
            return True

        except Exception as e:
            _safe_print(
                f"Failed to load semantic search model: {e} — falling back to text search"
            )
            self._encoder_failed = True
            return False
        finally:
            self._encoder_loading = False

    async def auto_classify_content(self, content: str) -> str:
        """Auto-classify content type based on keywords"""
        content_lower = content.lower()

        if any(
            word in content_lower
            for word in [
                "function",
                "class",
                "code",
                "bug",
                "debug",
                "error",
                "fix",
                "implement",
            ]
        ):
            return "code"
        elif any(
            word in content_lower
            for word in ["project", "milestone", "deadline", "goal", "sprint", "task"]
        ):
            return "project"
        elif any(
            word in content_lower
            for word in ["character", "story", "plot", "chapter", "write", "book"]
        ):
            return "book"
        else:
            return "general"

    async def update_memory(self, memory_id: str, new_content: str) -> None:
        """Append new_content into an existing memory and record the merge in metadata.

        Recomputes content_hash and embedding so Layer 1 dedup and semantic recall
        stay accurate after the merge.
        """
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT content, metadata FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return
            existing_content, metadata_json = row
            metadata = json.loads(metadata_json) if metadata_json else {}
            _MAX = 10000
            _MARKER = "\n[merged] "
            _new_budget = _MAX - len(_MARKER)
            if len(new_content) > _new_budget:
                new_content = new_content[:_new_budget]
            _existing_budget = _MAX - len(_MARKER) - len(new_content)
            existing_content = existing_content[: max(0, _existing_budget)]
            merged_content = f"{existing_content}{_MARKER}{new_content}"
            merged_at = datetime.now(timezone.utc).isoformat()
            if "merge_history" not in metadata:
                metadata["merge_history"] = []
            metadata["merge_history"].append(
                {
                    "merged_at": merged_at,
                    "content_preview": new_content[:100],
                }
            )

            merged_hash = compute_content_hash(merged_content)

            merged_embedding_bytes = None
            encoder_ok = merged_content.strip() and self._load_encoder_lazily()
            if encoder_ok:
                try:
                    merged_vec = await asyncio.to_thread(
                        self._encode_sync, merged_content
                    )
                    merged_embedding_bytes = merged_vec.tobytes()
                except Exception as e:
                    _safe_print(f"Failed to regenerate embedding after merge: {e}")

            if merged_embedding_bytes is not None:
                conn.execute(
                    "UPDATE memories SET content = ?, metadata = ?, content_hash = ?, embedding = ?, timestamp = ? WHERE id = ?",
                    (
                        merged_content,
                        json.dumps(metadata),
                        merged_hash,
                        merged_embedding_bytes,
                        merged_at,
                        memory_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE memories SET content = ?, metadata = ?, content_hash = ?, embedding = NULL, timestamp = ? WHERE id = ?",
                    (
                        merged_content,
                        json.dumps(metadata),
                        merged_hash,
                        merged_at,
                        memory_id,
                    ),
                )

        with self.get_connection() as conn:
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (memory_id,))

        chunks = _chunk_text(merged_content)
        if chunks and self._load_encoder_lazily():
            _chunk_task = asyncio.create_task(_write_chunks(self, self.db_path, memory_id, chunks))  # noqa: RUF006

    async def store_memory(
        self,
        content: str,
        session: str,
        context_type: str = "general",
        metadata: Dict = None,
    ) -> str:
        """Store content with vector embedding for semantic search"""
        sanitized_content = sanitize_content(content)

        if context_type == "general":
            context_type = await self.auto_classify_content(sanitized_content)

        content_hash = compute_content_hash(sanitized_content)
        normalized_content = normalize_content(sanitized_content)

        if CONSOLIDATION_ENABLED:
            with self.get_connection() as conn:
                existing_id = find_exact_duplicate(
                    conn, content_hash, session, normalized_content
                )
                if existing_id:
                    return existing_id

        pre_embedding = None
        pre_embedding_bytes = None
        if sanitized_content.strip() and self._load_encoder_lazily():
            try:
                pre_embedding = await asyncio.to_thread(
                    self._encode_sync, sanitized_content
                )
                pre_embedding_bytes = pre_embedding.tobytes()
            except Exception as e:
                _safe_print(f"Failed to generate embedding: {e}")

        if CONSOLIDATION_ENABLED:
            existing_id = await find_semantic_duplicate(
                self,
                sanitized_content,
                session,
                CONSOLIDATION_THRESHOLD,
                query_vec=pre_embedding,
            )
            if existing_id:
                await self.update_memory(existing_id, sanitized_content)
                self._on_memory_written(session)
                return existing_id

        memory_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}

        embedding_bytes = pre_embedding_bytes

        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if CONSOLIDATION_ENABLED:
                under_lock_id = find_exact_duplicate(
                    conn, content_hash, session, normalized_content
                )
                if under_lock_id:
                    conn.execute("ROLLBACK")
                    return under_lock_id

            conn.execute(
                """
                INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    memory_id,
                    session,
                    sanitized_content,
                    embedding_bytes,
                    content_hash,
                    timestamp,
                    context_type,
                    json.dumps(metadata),
                ),
            )

            conn.execute(
                """
                INSERT OR REPLACE INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
            """,
                (session, timestamp),
            )

        self._on_memory_written(session)

        chunks = _chunk_text(sanitized_content)
        if chunks and self._load_encoder_lazily():
            _chunk_task = asyncio.create_task(_write_chunks(self, self.db_path, memory_id, chunks))  # noqa: RUF006

        return memory_id

    async def store_memory_queued(
        self,
        content: str,
        session: str,
        context_type: str = "general",
        metadata: Dict = None,
        queue_enabled: Optional[bool] = None,
    ) -> str:
        """Store memory through the write queue unless explicitly disabled."""
        if queue_enabled is None:
            queue_enabled = WRITE_QUEUE_ENABLED
        if queue_enabled and self._write_queue is None:
            await self.start_write_queue()
        if self._write_queue is not None:
            return await self._write_queue.put(content, session, context_type, metadata)
        return await self.store_memory(content, session, context_type, metadata)

    async def recall_similar(
        self,
        query: str,
        session: str = None,
        limit: int = 5,
        query_vec=None,
        include_scan_metadata: bool = False,
    ):
        """Find semantically similar memories.

        When include_scan_metadata=True, returns (List[Dict], dict) where the second
        element contains recall_scan_truncated and recall_scan_limit. All other callers
        receive List[Dict] as before.
        """
        scan_limit = RECALL_SCAN_LIMIT

        def _wrap(results, truncated):
            if include_scan_metadata:
                return results, {
                    "recall_scan_truncated": truncated,
                    "recall_scan_limit": scan_limit,
                }
            return results

        if query_vec is None:
            if not self._load_encoder_lazily():
                _recall_debug("semantic model unavailable → text-search fallback")
                return _wrap(
                    await self.recall_text_search(query, session, limit), False
                )

        try:
            if query_vec is not None:
                query_embedding = query_vec
            else:
                query_embedding = await asyncio.to_thread(self._encode_sync, query)

            fts_query = _safe_fts_query(query)
            candidate_ids: list[str] = []
            if fts_query:
                try:
                    candidate_ids = await asyncio.to_thread(
                        _fetch_fts_candidate_ids,
                        self.db_path,
                        session,
                        fts_query,
                        max(limit, FTS_CANDIDATE_LIMIT),
                    )
                    _recall_debug(
                        f"FTS filter: {len(candidate_ids)} candidates for '{fts_query}'"
                    )
                except Exception as e:
                    _safe_print(
                        f"FTS5 filter failed, falling back to bounded semantic recall: {e}"
                    )
                    _recall_debug("FTS filter failed → semantic fallback")

            use_semantic_fallback = True
            if candidate_ids:
                similarities, dim_skipped = await asyncio.to_thread(
                    _fetch_and_score_by_ids,
                    self.db_path,
                    candidate_ids,
                    query_embedding,
                )
                if similarities:
                    scan_truncated = False
                    use_semantic_fallback = False
                    _recall_debug(
                        f"filter->rerank: scored {len(similarities)} candidates"
                    )
                else:
                    _recall_debug(
                        "filter->rerank: no scoreable embeddings in FTS candidates, falling back to semantic scan"
                    )

            if use_semantic_fallback:
                similarities, dim_skipped, scan_truncated = await asyncio.to_thread(
                    _fetch_and_score_embedding_rows,
                    self.db_path,
                    session,
                    scan_limit,
                    query_embedding,
                    limit,
                )
                _recall_debug(
                    f"semantic fallback: {len(similarities)} candidates, scan_truncated={scan_truncated}"
                )

            if dim_skipped:
                _safe_print(
                    f"recall_similar: skipped {dim_skipped} memories with wrong embedding dimension (expected {len(query_embedding)})"
                )

            combined: dict[str, tuple] = {}
            for mem, vec_score in similarities:
                t_score = _temporal_score(mem["timestamp"], TEMPORAL_HALF_LIFE_DAYS)
                combined[mem["id"]] = (
                    mem,
                    (1 - TEMPORAL_WEIGHT) * vec_score + TEMPORAL_WEIGHT * t_score,
                )

            ranked = sorted(combined.values(), key=lambda x: x[1], reverse=True)[:limit]

            results = []
            for memory, similarity in ranked:
                results.append(
                    {
                        "id": memory["id"],
                        "session_name": memory["session_name"],
                        "content": memory["content"],
                        "timestamp": memory["timestamp"],
                        "context_type": memory["context_type"],
                        "metadata": json.loads(memory["metadata"])
                        if memory["metadata"]
                        else {},
                        "similarity": float(similarity),
                    }
                )

            return _wrap(results, scan_truncated)

        except Exception as e:
            _safe_print(f"Semantic search failed: {e}")
            _recall_debug(f"semantic search exception → text-search fallback: {e}")
            return _wrap(await self.recall_text_search(query, session, limit), False)

    async def recall_text_search(
        self, query: str, session: str = None, limit: int = 5
    ) -> List[Dict]:
        """Text search via FTS5 BM25 ranking, with LIKE fallback for unsanitizable queries."""
        _recall_debug(f"text-search path: query='{query[:50]}', session={session}")
        fts_query = _safe_fts_query(query)
        if fts_query is not None:
            try:
                fts_rows = await asyncio.to_thread(
                    _fetch_and_score_fts_rows, self.db_path, session, fts_query, limit
                )
                if fts_rows:
                    _recall_debug(f"FTS5 returned {len(fts_rows)} results")
                    return [
                        {
                            "id": row["id"],
                            "session_name": row["session_name"],
                            "content": row["content"],
                            "timestamp": row["timestamp"],
                            "context_type": row["context_type"],
                            "metadata": json.loads(row["metadata"])
                            if row["metadata"]
                            else {},
                            "similarity": float(score),
                        }
                        for row, score in fts_rows
                    ]
            except Exception as e:
                _safe_print(f"FTS5 search failed, falling back to LIKE: {e}")
                _recall_debug("FTS5 failed → LIKE fallback")

        _recall_debug("FTS5 returned 0 or query unsanitizable → LIKE fallback")

        with self.get_connection() as conn:
            if session is None:
                cursor = conn.execute(
                    """
                    SELECT id, session_name, content, timestamp, context_type, metadata
                    FROM memories
                    WHERE content LIKE ?
                      AND (compaction_role IS NULL OR compaction_role != 'source')
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (f"%{query}%", limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT id, session_name, content, timestamp, context_type, metadata
                    FROM memories
                    WHERE content LIKE ?
                      AND session_name = ?
                      AND (compaction_role IS NULL OR compaction_role != 'source')
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (f"%{query}%", session, limit),
                )

            results = []
            for row in cursor.fetchall():
                results.append(
                    {
                        "id": row[0],
                        "session_name": row[1],
                        "content": row[2],
                        "timestamp": row[3],
                        "context_type": row[4],
                        "metadata": json.loads(row[5]) if row[5] else {},
                        "similarity": 0.8,
                    }
                )

            return results


memory = MARMMemory()
