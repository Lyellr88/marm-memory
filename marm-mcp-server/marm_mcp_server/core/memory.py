"""Advanced memory system with semantic search and MARM protocol support."""

import asyncio
import json
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

# Import configuration
from ..config.settings import (
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
)
from .consolidation import compute_content_hash, find_exact_duplicate, find_semantic_duplicate, normalize_content
from .compaction import trigger_compaction
from .write_queue import WriteQueue

# Try to import sentence transformer if available
if SEMANTIC_SEARCH_AVAILABLE:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        SEMANTIC_SEARCH_AVAILABLE = False


class SQLiteConnectionPool:
    """Simple SQLite connection pool for better performance under load"""
    
    def __init__(self, db_path: str, max_connections: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool = queue.Queue(maxsize=max_connections)
        self.created_connections = 0
        self.lock = threading.Lock()
        
        # Pre-create initial connections
        self._create_initial_connections()
    
    def _create_initial_connections(self):
        """Create initial pool of connections"""
        for _ in range(2):  # Start with 2 connections
            self._create_connection()
    
    def _create_connection(self):
        """Create a new SQLite connection with optimal settings"""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=20.0,  # 20 second timeout
            isolation_level=None  # autocommit mode
        )
        # Optimize SQLite settings for concurrent access
        conn.execute('PRAGMA journal_mode=WAL')  # Write-Ahead Logging
        conn.execute('PRAGMA synchronous=NORMAL')  # Balanced performance/safety
        conn.execute('PRAGMA cache_size=10000')  # Larger cache
        conn.execute('PRAGMA temp_store=MEMORY')  # In-memory temp tables
        
        self.pool.put(conn)
        self.created_connections += 1
    
    def get_connection(self):
        """Get a connection from the pool"""
        try:
            # Try to get existing connection
            return self.pool.get(block=False)
        except queue.Empty:
            # Create new connection if under limit
            with self.lock:
                if self.created_connections < self.max_connections:
                    self._create_connection()
                    return self.pool.get(block=False)
            
            # Wait for available connection
            return self.pool.get(block=True, timeout=10)
    
    def return_connection(self, conn):
        """Return connection to pool"""
        try:
            self.pool.put(conn, block=False)
        except queue.Full:
            # Pool is full, close the connection
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

    # Prevent ReDoS attacks by limiting input length for regex processing
    if len(content) > 10000:  # 10KB limit for safe regex processing
        content = content[:10000]

    # Remove or neutralize common XSS patterns first (before HTML escaping)
    sanitized = content

    sanitized = _strip_script_tags(sanitized)

    # Remove javascript: protocols
    sanitized = re.sub(r'javascript:', 'blocked-protocol:', sanitized, flags=re.IGNORECASE)

    # Remove on* event handlers (onclick, onload, etc.)
    sanitized = re.sub(r'\son\w+\s*=\s*["\'][^"\']*["\']', '', sanitized, flags=re.IGNORECASE)

    # Finally, HTML escape any remaining dangerous characters
    sanitized = html.escape(sanitized)

    return sanitized

class MARMMemory:
    """Advanced memory system with semantic search and MARM protocol support"""
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_lock = threading.Lock()
        
        # Initialize connection pool with configurable settings
        self.connection_pool = SQLiteConnectionPool(db_path, max_connections=MAX_DB_CONNECTIONS)
        
        # Lazy loading for semantic search model
        self.encoder = None
        self._encoder_loading = False
        self._encoder_failed = False
        self._encoder_lock = threading.Lock()
            
        self.init_database()
        
        # Active sessions and notebook state
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
            self._session_write_counts[session] = 0
        self._session_write_counts[session] = self._session_write_counts.get(session, 0) + 1
        if self._session_write_counts[session] >= COMPACTION_TRIGGER_COUNT:
            trigger_compaction(self, session)

    def get_active_notebook_entries(self, session_name: str = "main") -> list[dict]:
        """Return active notebook entries scoped to a session."""
        return self.active_notebook_entries_by_session.get(session_name, [])

    def set_active_notebook_entries(self, session_name: str, entries: list[dict]) -> None:
        """Set active notebook entries for one session."""
        self.active_notebook_entries_by_session[session_name] = entries

    def clear_active_notebook_entries(self, session_name: str = "main") -> None:
        """Clear active notebook entries for one session."""
        self.active_notebook_entries_by_session[session_name] = []

    def remove_active_notebook_entry(self, name: str) -> None:
        """Remove a deleted notebook entry from every active session scope."""
        for session_name, entries in list(self.active_notebook_entries_by_session.items()):
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
                        # Successful transaction
                        self.conn.commit()
                    else:
                        # Error occurred, rollback
                        self.conn.rollback()
                    self.pool.return_connection(self.conn)
        
        return ConnectionContext(self.connection_pool)
    
    def init_database(self):
        """Initialize SQLite database with all MARM tables"""
        with sqlite3.connect(self.db_path) as conn:
            # Main memories table
            conn.execute('''
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
            ''')
            
            # Sessions table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_name TEXT PRIMARY KEY,
                    marm_active BOOLEAN DEFAULT FALSE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_accessed TEXT DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT DEFAULT '{}'
                )
            ''')
            
            # Log entries table (MARM protocol specific)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS log_entries (
                    id TEXT PRIMARY KEY,
                    session_name TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    full_entry TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Notebook entries table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS notebook_entries (
                    name TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    embedding BLOB,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # User settings table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Doc index — tracks content hash + memory_id per source file to skip unchanged docs on restart
            conn.execute('''
                CREATE TABLE IF NOT EXISTS doc_index (
                    source_file TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    memory_id TEXT,
                    indexed_at TEXT NOT NULL
                )
            ''')
            # Idempotent migration: add memory_id column to existing doc_index tables that predate it
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(doc_index)").fetchall()}
            if "memory_id" not in existing_cols:
                conn.execute("ALTER TABLE doc_index ADD COLUMN memory_id TEXT")

            # Idempotent migration: add content_hash column for consolidation Layer 1
            mem_cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
            if "content_hash" not in mem_cols:
                conn.execute("ALTER TABLE memories ADD COLUMN content_hash TEXT")

            # Idempotent migrations: compaction Layer 3 metadata columns
            if "compaction_role" not in mem_cols:
                conn.execute("ALTER TABLE memories ADD COLUMN compaction_role TEXT")
            if "compacted_into" not in mem_cols:
                conn.execute("ALTER TABLE memories ADD COLUMN compacted_into TEXT")

            # V2: staging table for agent-driven summarization
            conn.execute('''
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
            ''')
            staging_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(compaction_staging)").fetchall()
            }
            if "nudge_count" not in staging_cols:
                conn.execute(
                    "ALTER TABLE compaction_staging "
                    "ADD COLUMN nudge_count INTEGER NOT NULL DEFAULT 0"
                )
            if "last_nudged_at" not in staging_cols:
                conn.execute("ALTER TABLE compaction_staging ADD COLUMN last_nudged_at TEXT")
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_compaction_staging_session_status '
                'ON compaction_staging(session_name, status)'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_compaction_staging_hash '
                'ON compaction_staging(candidate_hash)'
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
            _safe_print(f"Failed to load semantic search model: {e} — falling back to text search")
            self._encoder_failed = True
            return False
        finally:
            self._encoder_loading = False
    
    async def auto_classify_content(self, content: str) -> str:
        """Auto-classify content type based on keywords"""
        content_lower = content.lower()
        
        if any(word in content_lower for word in ['function', 'class', 'code', 'bug', 'debug', 'error', 'fix', 'implement']):
            return 'code'
        elif any(word in content_lower for word in ['project', 'milestone', 'deadline', 'goal', 'sprint', 'task']):
            return 'project'
        elif any(word in content_lower for word in ['character', 'story', 'plot', 'chapter', 'write', 'book']):
            return 'book'
        else:
            return 'general'
    
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
            merged_content = f"{existing_content}\n[merged] {new_content}"
            merged_at = datetime.now(timezone.utc).isoformat()
            if "merge_history" not in metadata:
                metadata["merge_history"] = []
            metadata["merge_history"].append({
                "merged_at": merged_at,
                "content_preview": new_content[:100],
            })

            merged_hash = compute_content_hash(merged_content)

            # Recompute embedding; if unavailable, clear the stale pre-merge vector.
            merged_embedding_bytes = None
            encoder_ok = merged_content.strip() and self._load_encoder_lazily()
            if encoder_ok:
                try:
                    merged_vec = await asyncio.to_thread(self._encode_sync, merged_content)
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

    async def store_memory(self, content: str, session: str, context_type: str = "general", metadata: Dict = None) -> str:
        """Store content with vector embedding for semantic search"""
        sanitized_content = sanitize_content(content)

        if context_type == "general":
            context_type = await self.auto_classify_content(sanitized_content)

        content_hash = compute_content_hash(sanitized_content)
        normalized_content = normalize_content(sanitized_content)

        # Layer 1: exact duplicate check — runs before embedding to avoid wasted model work
        if CONSOLIDATION_ENABLED:
            with self.get_connection() as conn:
                existing_id = find_exact_duplicate(conn, content_hash, session, normalized_content)
                if existing_id:
                    return existing_id

        # Pre-encode once — reused by Layer 2 dedup and storage to avoid a second encode
        pre_embedding = None
        pre_embedding_bytes = None
        if sanitized_content.strip() and self._load_encoder_lazily():
            try:
                pre_embedding = await asyncio.to_thread(self._encode_sync, sanitized_content)
                pre_embedding_bytes = pre_embedding.tobytes()
            except Exception as e:
                _safe_print(f"Failed to generate embedding: {e}")

        # Layer 2: semantic near-duplicate check — skipped gracefully if encoder unavailable
        if CONSOLIDATION_ENABLED:
            existing_id = await find_semantic_duplicate(
                self, sanitized_content, session, CONSOLIDATION_THRESHOLD, query_vec=pre_embedding
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
            # Re-check under write lock to close the check-then-insert race
            if CONSOLIDATION_ENABLED:
                under_lock_id = find_exact_duplicate(conn, content_hash, session, normalized_content)
                if under_lock_id:
                    conn.execute("ROLLBACK")
                    return under_lock_id

            conn.execute('''
                INSERT INTO memories (id, session_name, content, embedding, content_hash, timestamp, context_type, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (memory_id, session, sanitized_content, embedding_bytes, content_hash, timestamp, context_type, json.dumps(metadata)))

            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
            ''', (session, timestamp))

        self._on_memory_written(session)
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
    
    async def recall_similar(self, query: str, session: str = None, limit: int = 5, query_vec=None) -> List[Dict]:
        """Find semantically similar memories"""
        if query_vec is None:
            if not self._load_encoder_lazily():
                return await self.recall_text_search(query, session, limit)

        try:
            if query_vec is not None:
                query_embedding = query_vec
            else:
                query_embedding = await asyncio.to_thread(self._encode_sync, query)
            
            with self.get_connection() as conn:
                # If session is None, search all sessions
                if session is None:
                    cursor = conn.execute('''
                        SELECT id, session_name, content, embedding, timestamp, context_type, metadata
                        FROM memories
                        WHERE embedding IS NOT NULL
                          AND (compaction_role IS NULL OR compaction_role != 'source')
                        ORDER BY timestamp DESC
                        LIMIT 1000
                    ''')
                else:
                    cursor = conn.execute('''
                        SELECT id, session_name, content, embedding, timestamp, context_type, metadata
                        FROM memories
                        WHERE embedding IS NOT NULL
                          AND session_name = ?
                          AND (compaction_role IS NULL OR compaction_role != 'source')
                        ORDER BY timestamp DESC
                        LIMIT 1000
                    ''', (session,))
                
                memories = cursor.fetchall()
                similarities = []
                expected_dim = len(query_embedding)
                dim_skipped = 0

                for memory in memories:
                    try:
                        memory_embedding = np.frombuffer(memory[3], dtype=np.float32)
                        if len(memory_embedding) != expected_dim:
                            dim_skipped += 1
                            continue
                        similarity = np.dot(query_embedding, memory_embedding) / (
                            np.linalg.norm(query_embedding) * np.linalg.norm(memory_embedding)
                        )
                        similarities.append((memory, similarity))
                    except Exception:
                        continue

                if dim_skipped:
                    _safe_print(f"recall_similar: skipped {dim_skipped} memories with wrong embedding dimension (expected {expected_dim})")
                
                similarities.sort(key=lambda x: x[1], reverse=True)
                
                results = []
                for memory, similarity in similarities[:limit]:
                    results.append({
                        "id": memory[0],
                        "session_name": memory[1],
                        "content": memory[2],
                        "timestamp": memory[4],
                        "context_type": memory[5],
                        "metadata": json.loads(memory[6]) if memory[6] else {},
                        "similarity": float(similarity)
                    })
                
                return results
                
        except Exception as e:
            print(f"Semantic search failed: {e}")
            return await self.recall_text_search(query, session, limit)
    
    async def recall_text_search(self, query: str, session: str = None, limit: int = 5) -> List[Dict]:
        """Fallback text-based search"""
        with self.get_connection() as conn:
            # If session is None, search all sessions
            if session is None:
                cursor = conn.execute('''
                    SELECT id, session_name, content, timestamp, context_type, metadata
                    FROM memories
                    WHERE content LIKE ?
                      AND (compaction_role IS NULL OR compaction_role != 'source')
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (f"%{query}%", limit))
            else:
                cursor = conn.execute('''
                    SELECT id, session_name, content, timestamp, context_type, metadata
                    FROM memories
                    WHERE content LIKE ?
                      AND session_name = ?
                      AND (compaction_role IS NULL OR compaction_role != 'source')
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (f"%{query}%", session, limit))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    "id": row[0],
                    "session_name": row[1],
                    "content": row[2],
                    "timestamp": row[3],
                    "context_type": row[4],
                    "metadata": json.loads(row[5]) if row[5] else {},
                    "similarity": 0.8  # Default similarity for text matches
                })
            
            return results

# Global memory instance
memory = MARMMemory()
