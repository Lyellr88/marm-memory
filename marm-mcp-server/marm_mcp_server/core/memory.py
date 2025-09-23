"""Advanced memory system with semantic search and MARM protocol support."""

import json
import sqlite3
import threading
import uuid
import queue
from datetime import datetime, timezone
from typing import List, Dict, Optional
import numpy as np
import html
import re

# Import configuration
from config.settings import (
    SEMANTIC_SEARCH_AVAILABLE, 
    DEFAULT_DB_PATH, 
    MAX_DB_CONNECTIONS,
    DEFAULT_SEMANTIC_MODEL
)

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

    # Remove or neutralize common XSS patterns first (before HTML escaping)
    sanitized = content

    # Remove script tags entirely
    sanitized = re.sub(r'<script[^>]*>.*?</script>', '', sanitized, flags=re.IGNORECASE | re.DOTALL)

    # Remove javascript: protocols
    sanitized = re.sub(r'javascript:', 'blocked-javascript:', sanitized, flags=re.IGNORECASE)

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
            
        self.init_database()
        
        # Active sessions and notebook state
        self.active_sessions = {}
        self.active_notebook_entries = []
    
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
            
            conn.commit()
    
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
            print(f"🔄 Loading semantic search model ({DEFAULT_SEMANTIC_MODEL}) for memory system...")
            
            from sentence_transformers import SentenceTransformer
            self.encoder = SentenceTransformer(DEFAULT_SEMANTIC_MODEL)
            
            print("✅ Semantic search model loaded successfully")
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to load semantic search model: {e}")
            print("🔄 Falling back to text-based search")
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
    
    async def store_memory(self, content: str, session: str, context_type: str = "general", metadata: Dict = None) -> str:
        """Store content with vector embedding for semantic search"""
        # Sanitize content to prevent XSS attacks
        sanitized_content = sanitize_content(content)
        
        if context_type == "general":
            context_type = await self.auto_classify_content(sanitized_content)
            
        memory_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}
        
        # Generate embedding for semantic search (lazy load encoder if needed)
        embedding_bytes = None
        if sanitized_content.strip() and self._load_encoder_lazily():
            try:
                embedding = self.encoder.encode(sanitized_content)
                embedding_bytes = embedding.tobytes()
            except Exception as e:
                print(f"Failed to generate embedding: {e}")
        
        with self.get_connection() as conn:
            # Store sanitized memory
            conn.execute('''
                INSERT INTO memories (id, session_name, content, embedding, timestamp, context_type, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (memory_id, session, sanitized_content, embedding_bytes, timestamp, context_type, json.dumps(metadata)))
            
            # Update session access time
            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
            ''', (session, timestamp))
        
        # Note: events system will be handled by the main application
        # We don't import it here to avoid circular dependencies
        
        return memory_id
    
    async def recall_similar(self, query: str, session: str = None, limit: int = 5) -> List[Dict]:
        """Find semantically similar memories"""
        if not self._load_encoder_lazily():
            return await self.recall_text_search(query, session, limit)
        
        try:
            query_embedding = self.encoder.encode(query)
            
            with self.get_connection() as conn:
                # If session is None, search all sessions
                if session is None:
                    cursor = conn.execute('''
                        SELECT id, session_name, content, embedding, timestamp, context_type, metadata
                        FROM memories
                        WHERE embedding IS NOT NULL
                        ORDER BY timestamp DESC
                        LIMIT 1000
                    ''')
                else:
                    cursor = conn.execute('''
                        SELECT id, session_name, content, embedding, timestamp, context_type, metadata
                        FROM memories
                        WHERE embedding IS NOT NULL
                        AND session_name = ?
                        ORDER BY timestamp DESC
                        LIMIT 1000
                    ''', (session,))
                
                memories = cursor.fetchall()
                similarities = []
                
                for memory in memories:
                    try:
                        memory_embedding = np.frombuffer(memory[3], dtype=np.float32)
                        similarity = np.dot(query_embedding, memory_embedding) / (
                            np.linalg.norm(query_embedding) * np.linalg.norm(memory_embedding)
                        )
                        similarities.append((memory, similarity))
                    except Exception:
                        continue
                
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
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (f"%{query}%", limit))
            else:
                cursor = conn.execute('''
                    SELECT id, session_name, content, timestamp, context_type, metadata
                    FROM memories
                    WHERE content LIKE ?
                    AND session_name = ?
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