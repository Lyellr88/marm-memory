"""Documentation loading service for MARM MCP Server."""

import os
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import hashlib
import threading
from typing import Dict

from ..core.memory import memory
from ..utils.helpers import docs_dir as helpers_docs_dir


def guess_context_type(filename):
    filename_lower = filename.lower()
    if "protocol" in filename_lower:
        return "protocol"
    elif "handbook" in filename_lower:
        return "handbook"
    elif "faq" in filename_lower:
        return "support"
    elif "readme" in filename_lower:
        return "general"
    elif "description" in filename_lower:
        return "general"
    elif "tool" in filename_lower or "reference" in filename_lower:
        return "reference"
    elif "workflow" in filename_lower or "pattern" in filename_lower:
        return "workflow"
    elif "troubleshoot" in filename_lower or "debug" in filename_lower:
        return "support"
    elif "integration" in filename_lower or "setup" in filename_lower:
        return "integration"
    elif "api" in filename_lower:
        return "api"
    elif "security" in filename_lower or "auth" in filename_lower:
        return "security"
    elif "config" in filename_lower or "setting" in filename_lower:
        return "config"
    elif "install" in filename_lower or "deploy" in filename_lower:
        return "installation"
    else:
        return "general"


def _docs_dir() -> Path | None:
    """Resolve the packaged marm-docs directory, or None if it is missing.

    Delegates to utils.helpers so the protocol readers and the doc indexer can
    never disagree about where docs live. Earlier versions searched several
    candidate paths to cover a second copy at the repo root; that copy was never
    included in the wheel, so pip installs matched nothing and silently indexed
    no docs. There is now exactly one location, inside the package.
    """
    return helpers_docs_dir()


def get_docs_to_load():
    """Return all docs from marm-docs/ for memory indexing."""
    docs_dir = _docs_dir()

    docs = []
    if docs_dir is not None:
        for md_file in sorted(docs_dir.glob("*.md")):
            filename = md_file.stem.lower()
            docs.append(
                {
                    "file_path": f"marm-docs/{md_file.name}",
                    "context_type": guess_context_type(filename),
                    "description": md_file.name,
                }
            )
        if docs:
            names = ", ".join(d["file_path"].split("/")[-1] for d in docs)
            print(f"[DOCS] Indexing for marm_smart_recall: {names}")
    else:
        print(
            "WARNING: packaged marm-docs not found -- reinstall with "
            "`python -m pip install -U --force-reinstall marm-mcp-server`"
        )

    return docs


async def _index_doc(doc: Dict) -> bool:
    """Read one doc file and store it in memories for search.

    Skips indexing if the file content hash matches doc_index AND the memory row still exists.
    Re-indexes if content changed or the memory was deleted externally.
    Returns True on success, False if the file is missing or indexing fails.
    """
    docs_dir = _docs_dir()
    doc_path = docs_dir / Path(doc["file_path"]).name if docs_dir else None
    if doc_path is None or not doc_path.exists():
        print(f"WARNING: Documentation file not found: {doc['file_path']}")
        return False

    try:
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        source_file = doc["file_path"]
        fname = source_file.split("/")[-1]

        with memory.get_connection() as conn:
            row = conn.execute(
                "SELECT content_hash, memory_id FROM doc_index WHERE source_file = ?",
                (source_file,),
            ).fetchone()

        if row and row[0] == content_hash:
            memory_id = row[1]
            if memory_id:
                with memory.get_connection() as conn:
                    exists = conn.execute(
                        "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
                    ).fetchone()
                if exists:
                    print(f"SKIP: {fname} unchanged")
                    return True
                print(f"[DOCS] {fname} memory row missing, re-indexing")

        # Audited under the SQLite write-atomicity hardening effort
        # (docs/current/sqlite-write-atomicity-hardening.md): no BEGIN
        # IMMEDIATE needed here. Exactly one of the two branches below
        # runs per call, and each is a single statement -- a lone
        # statement is already atomic under SQLite regardless of
        # isolation_level, so there's no multi-statement sequence to
        # protect. store_memory_queued below intentionally stays outside
        # any transaction (it awaits and does its own internal locking).
        with memory.get_connection() as conn:
            if row and row[1]:
                conn.execute("DELETE FROM memories WHERE id = ?", (row[1],))
            else:
                conn.execute(
                    "DELETE FROM memories WHERE session_name = 'marm_system'"
                    " AND json_extract(metadata, '$.source_file') = ?",
                    (source_file,),
                )
            conn.commit()

        new_memory_id = await memory.store_memory_queued(
            content=content,
            session="marm_system",
            context_type=doc["context_type"],
            metadata={
                "doc_type": "documentation",
                "source_file": source_file,
                "description": doc["description"],
            },
        )

        with memory.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO doc_index (source_file, content_hash, memory_id, indexed_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    source_file,
                    content_hash,
                    new_memory_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

        action = "Updated" if (row and row[0] != content_hash) else "Indexed"
        print(f"OK: {action} {fname} ({len(content)} chars)")
        return True

    except Exception as e:
        try:
            print(f"ERROR: Failed to load {doc['file_path']}: {e!s}")
        except UnicodeEncodeError:
            print(f"ERROR: Failed to load {doc['file_path']}: {type(e).__name__}")
        return False


_docs_loaded: bool = False
_docs_load_in_progress: bool = False
_tool_call_count: int = 0
_refresh_in_progress: bool = False
_refresh_state_lock = threading.Lock()
_docs_load_state_lock = threading.Lock()
REFRESH_EVERY: int = 50


def docs_are_loaded() -> bool:
    return _docs_loaded


async def ensure_docs_loaded() -> None:
    """Load docs once, even when multiple tool calls arrive together."""
    if os.environ.get("MARM_SKIP_DOC_LOAD") == "1":
        return

    global _docs_load_in_progress

    if docs_are_loaded():
        return

    should_load = False
    with _docs_load_state_lock:
        if not docs_are_loaded() and not _docs_load_in_progress:
            _docs_load_in_progress = True
            should_load = True

    if should_load:
        try:
            await load_marm_documentation()
        finally:
            with _docs_load_state_lock:
                _docs_load_in_progress = False
        return

    while True:
        with _docs_load_state_lock:
            if not _docs_load_in_progress:
                return
        await asyncio.sleep(0)


async def maybe_auto_refresh() -> None:
    global _tool_call_count, _refresh_in_progress
    should_refresh = False

    with _refresh_state_lock:
        _tool_call_count += 1
        if _tool_call_count >= REFRESH_EVERY and not _refresh_in_progress:
            _tool_call_count = 0
            _refresh_in_progress = True
            should_refresh = True

    if not should_refresh:
        return

    try:
        await reload_marm_documentation()
    finally:
        with _refresh_state_lock:
            _refresh_in_progress = False


async def ensure_marm_started(session_name: str = "default") -> None:
    """Load docs if not loaded, then upsert session recency without log routing."""
    await ensure_docs_loaded()
    try:
        with memory.get_connection() as conn:
            conn.execute(
                "INSERT INTO sessions (session_name, last_accessed)"
                " VALUES (?, ?)"
                " ON CONFLICT(session_name) DO UPDATE SET"
                " last_accessed = excluded.last_accessed",
                (session_name, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
    except Exception:
        pass


async def reload_marm_documentation():
    """Force a fresh doc load regardless of prior state."""
    global _docs_loaded
    _docs_loaded = False
    await load_marm_documentation()


_LEGACY_SYSTEM_NOTEBOOK_NAMES = {
    "marm_protocol",
    "marm_commands_summary",
    "mcp_integration_guide",
    "marm_readme",
    "marm_mcp-handbook",
}


async def load_marm_documentation():
    """Index all marm-docs/ files into memories for semantic search."""
    global _docs_loaded

    with memory.get_connection() as conn:
        already_cleaned = conn.execute(
            "SELECT value FROM user_settings WHERE key = 'system_notebook_cleanup_v1'"
        ).fetchone()
        if not already_cleaned:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for name in _LEGACY_SYSTEM_NOTEBOOK_NAMES:
                    conn.execute("DELETE FROM notebook_entries WHERE name = ?", (name,))
                conn.execute(
                    "INSERT OR REPLACE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
                    (
                        "system_notebook_cleanup_v1",
                        "done",
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            print("[DOCS] Cleaned up legacy system notebook entries")

    docs = get_docs_to_load()
    print("Loading MARM documentation into memory system...")

    if not docs:
        print("WARNING: No documentation files found — will retry on next tool call")
        return

    failures = 0
    for doc in docs:
        if not await _index_doc(doc):
            failures += 1

    if failures == 0:
        print("MARM documentation database ready!")
        _docs_loaded = True
    else:
        print(
            f"WARNING: {failures} doc(s) failed to index — will retry on next tool call"
        )
