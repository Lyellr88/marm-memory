"""Advanced memory system with semantic search and MARM protocol support."""

import importlib.util
import threading
from datetime import datetime, timezone
from typing import List, Dict, Optional

from .memory_utils import (
    _safe_print,
    _chunk_text,  # noqa: F401
    _safe_fts_query,  # noqa: F401
    _temporal_score,  # noqa: F401
    sanitize_content,  # noqa: F401
    CHUNK_TOKEN_LIMIT,  # noqa: F401
    CHUNK_OVERLAP_TOKENS,  # noqa: F401
    CHUNK_THRESHOLD_WORDS,  # noqa: F401
    _is_exact_query,  # noqa: F401
)
from .memory_db import (
    SQLiteConnectionPool,
    ConnectionContext,
    init_database,
    _get_compaction_write_count as _get_compaction_write_count_db,
    _set_compaction_write_count as _set_compaction_write_count_db,
    _increment_compaction_write_count as _increment_compaction_write_count_db,
)
from .memory_scoring import (
    _score_chunk_aware,  # noqa: F401
)

from ..config.settings import (
    SEMANTIC_SEARCH_AVAILABLE,
    DEFAULT_DB_PATH,
    MAX_DB_CONNECTIONS,
    DEFAULT_SEMANTIC_MODEL,
    MAX_QUEUE_SIZE,
    WRITE_QUEUE_ENABLED,
    COMPACTION_ENABLED,
    COMPACTION_TRIGGER_COUNT,
    SIGNUP_PROMPT_ENABLED,
    SIGNUP_PROMPT_THRESHOLD,
)
from .compaction import trigger_compaction
from .write_queue import WriteQueue
from .memory_ops import (
    _store_memory,
    _update_memory,
    _recall_similar,
    _recall_text_search,
)

if SEMANTIC_SEARCH_AVAILABLE:
    if importlib.util.find_spec("sentence_transformers") is None:
        SEMANTIC_SEARCH_AVAILABLE = False


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

        init_database(self.db_path)

        self.active_sessions = {}
        self.active_notebook_entries_by_session: dict[str, list[dict]] = {}
        self.active_log_session: str = "main"
        self._write_queue: WriteQueue | None = None
        self._session_write_counts: dict = {}
        self._pending_compaction_scans: dict = {}

    def restore_active_session(self) -> None:
        """Restore the active log session from DB on server startup."""
        try:
            with self.get_connection() as conn:
                row = conn.execute(
                    "SELECT session_name FROM sessions WHERE marm_active = TRUE ORDER BY last_accessed DESC LIMIT 1"
                ).fetchone()
            if row:
                self.active_log_session = row[0]
        except Exception:
            pass

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
        return _get_compaction_write_count_db(self, session)

    def _set_compaction_write_count(self, session: str, count: int) -> None:
        _set_compaction_write_count_db(self, session, count)

    def _increment_compaction_write_count(self, session: str) -> int:
        return _increment_compaction_write_count_db(self, session)

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
        return ConnectionContext(self.connection_pool)

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
        return await _update_memory(self, memory_id, new_content)

    async def store_memory(
        self,
        content: str,
        session: str,
        context_type: str = "general",
        metadata: Dict = None,
    ) -> str:
        return await _store_memory(self, content, session, context_type, metadata)

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
<<<<<<< HEAD
        exact_mode: str = "auto",
    ):
        return await _recall_similar(
            self, query, session, limit, query_vec, include_scan_metadata, exact_mode
=======
        project: str = None,
        platform: str = None,
    ):
        return await _recall_similar(
            self,
            query,
            session,
            limit,
            query_vec,
            include_scan_metadata,
            project,
            platform,
>>>>>>> upstream/MARM-main
        )

    async def recall_text_search(
        self,
        query: str,
        session: str = None,
        limit: int = 5,
        project: str = None,
        platform: str = None,
    ) -> List[Dict]:
        return await _recall_text_search(
            self, query, session, limit, project=project, platform=platform
        )

    def check_and_mark_signup_prompt(self) -> bool:
        if not SIGNUP_PROMPT_ENABLED:
            return False
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM user_settings WHERE key = 'signup_prompted'"
            ).fetchone()
            if row:
                return False
            count = conn.execute(
                """
                SELECT COUNT(*) FROM memories
                WHERE session_name != 'marm_system'
                  AND (compaction_role IS NULL OR compaction_role != 'source')
                """
            ).fetchone()[0]
            if count < SIGNUP_PROMPT_THRESHOLD:
                return False
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("signup_prompted", "1", now),
            )
        return True


memory = MARMMemory()
