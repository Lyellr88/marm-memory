"""SQLite database with semantic search capabilities"""
import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


def validate_session_name(session_name: str) -> bool:
    """
    Validate session name format

    Rules:
    - Alphanumeric, underscore, hyphen only
    - 1-50 characters
    - Cannot start with hyphen
    """
    if not session_name or len(session_name) > 50:
        return False

    # Allow alphanumeric, underscore, hyphen (but not starting with hyphen)
    pattern = r'^[a-zA-Z0-9_][a-zA-Z0-9_-]*$'
    return bool(re.match(pattern, session_name))


class MARMDatabase:
    """MARM persistent memory storage with SQLite"""

    def __init__(self, db_path: str = ".marm-cli/conversations.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self._initialize_db()

    def _initialize_db(self):
        """Initialize database with MARM schema"""
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrency
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        self._create_tables()
        logger.info(f"Database initialized at {self.db_path}")

    def _create_tables(self):
        """Create MARM database schema"""

        # Conversations table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                user_message TEXT,
                ai_response TEXT,
                embedding BLOB,
                metadata TEXT
            )
        """)

        # Log entries table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS log_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                entry_type TEXT,
                content TEXT NOT NULL,
                auto_detected INTEGER DEFAULT 0,
                embedding BLOB
            )
        """)

        # Notebook entries table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS notebook (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                summary TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                embedding BLOB
            )
        """)

        # Active instructions table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS active_instructions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notebook_key TEXT NOT NULL,
                activated_at TEXT NOT NULL,
                FOREIGN KEY (notebook_key) REFERENCES notebook(key)
            )
        """)

        # Sessions metadata table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                last_activity TEXT NOT NULL,
                message_count INTEGER DEFAULT 0
            )
        """)

        # Create indexes for performance
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_log_entries_session ON log_entries(session_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_id ON sessions(session_id)")

        self.conn.commit()

    def add_conversation(self, session_id: str, user_message: str, ai_response: str,
                        embedding: Optional[bytes] = None, metadata: Optional[Dict] = None):
        """Add conversation to database"""
        if not validate_session_name(session_id):
            error_msg = f"Invalid session name '{session_id}'. Must be alphanumeric with underscores/hyphens, 1-50 chars."
            logger.error(error_msg)
            raise ValueError(error_msg)

        timestamp = datetime.now().isoformat()
        metadata_json = json.dumps(metadata) if metadata else None

        try:
            self.conn.execute("""
                INSERT INTO conversations (session_id, timestamp, user_message, ai_response, embedding, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, timestamp, user_message, ai_response, embedding, metadata_json))

            self.conn.commit()
            logger.debug(f"Added conversation to session '{session_id}'")
            self._update_session_activity(session_id)
        except sqlite3.Error as e:
            logger.error(f"Failed to add conversation to '{session_id}': {e}")
            raise

    def add_log_entry(self, session_id: str, content: str, entry_type: str = "general",
                     auto_detected: bool = False, embedding: Optional[bytes] = None):
        """Add log entry to database"""
        if not validate_session_name(session_id):
            error_msg = f"Invalid session name '{session_id}'. Must be alphanumeric with underscores/hyphens, 1-50 chars."
            logger.error(error_msg)
            raise ValueError(error_msg)

        timestamp = datetime.now().isoformat()

        try:
            self.conn.execute("""
                INSERT INTO log_entries (session_id, timestamp, entry_type, content, auto_detected, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, timestamp, entry_type, content, int(auto_detected), embedding))

            self.conn.commit()
            logger.debug(f"Added log entry to session '{session_id}': {content[:50]}...")
        except sqlite3.Error as e:
            logger.error(f"Failed to add log entry to '{session_id}': {e}")
            raise

    def add_notebook_entry(self, key: str, content: str, summary: Optional[str] = None,
                          embedding: Optional[bytes] = None):
        """Add or update notebook entry"""
        now = datetime.now().isoformat()

        try:
            self.conn.execute("""
                INSERT INTO notebook (key, content, summary, created_at, updated_at, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    content = excluded.content,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at,
                    embedding = excluded.embedding
            """, (key, content, summary, now, now, embedding))

            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error adding notebook entry: {e}")
            return False

    def get_notebook_entries(self) -> List[Dict]:
        """Get all notebook entries"""
        cursor = self.conn.execute("""
            SELECT key, content, summary, created_at, updated_at
            FROM notebook
            ORDER BY updated_at DESC
        """)

        return [dict(row) for row in cursor.fetchall()]

    def activate_instruction(self, notebook_key: str) -> bool:
        """Activate a notebook entry as an instruction"""
        timestamp = datetime.now().isoformat()

        try:
            self.conn.execute("""
                INSERT INTO active_instructions (notebook_key, activated_at)
                VALUES (?, ?)
            """, (notebook_key, timestamp))

            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error activating instruction: {e}")
            return False

    def get_active_instructions(self) -> List[str]:
        """Get list of active instruction keys"""
        cursor = self.conn.execute("""
            SELECT DISTINCT notebook_key
            FROM active_instructions
            ORDER BY activated_at DESC
        """)

        return [row[0] for row in cursor.fetchall()]

    def clear_active_instructions(self):
        """Clear all active instructions"""
        self.conn.execute("DELETE FROM active_instructions")
        self.conn.commit()

    def search_conversations(self, session_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Search conversations by session"""
        query = "SELECT * FROM conversations"
        params = []

        if session_id:
            query += " WHERE session_id = ?"
            params.append(session_id)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def _update_session_activity(self, session_id: str):
        """Update session last activity timestamp"""
        if not validate_session_name(session_id):
            error_msg = f"Invalid session name '{session_id}'. Must be alphanumeric with underscores/hyphens, 1-50 chars."
            logger.error(error_msg)
            raise ValueError(error_msg)

        now = datetime.now().isoformat()

        try:
            self.conn.execute("""
                INSERT INTO sessions (session_id, created_at, last_activity, message_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_activity = excluded.last_activity,
                    message_count = message_count + 1
            """, (session_id, now, now))

            self.conn.commit()
            logger.debug(f"Updated session activity for '{session_id}'")
        except sqlite3.Error as e:
            logger.error(f"Failed to update session activity for '{session_id}': {e}")
            raise

    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """Get session metadata"""
        cursor = self.conn.execute("""
            SELECT * FROM sessions WHERE session_id = ?
        """, (session_id,))

        row = cursor.fetchone()
        return dict(row) if row else None

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
