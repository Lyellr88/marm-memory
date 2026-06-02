"""Documentation loading service for MARM MCP Server."""

from pathlib import Path
from datetime import datetime, timezone
import asyncio
import hashlib
import threading
from typing import Dict

from ..core.memory import memory


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


def get_docs_to_load():
    """Return all docs from marm-docs/ for memory indexing."""
    docs_dir = Path(__file__).parent.parent.parent / "marm-docs"
    if not docs_dir.exists():
        docs_dir = Path("/app/marm-docs")

    docs = []
    if docs_dir.exists():
        for md_file in sorted(docs_dir.glob("*.md")):
            filename = md_file.stem.lower()
            docs.append({
                "file_path": f"marm-docs/{md_file.name}",
                "context_type": guess_context_type(filename),
                "description": md_file.name,
            })
        if docs:
            names = ", ".join(d["file_path"].split("/")[-1] for d in docs)
            print(f"[DOCS] Indexing for marm_smart_recall: {names}")
    else:
        print(f"WARNING: Documentation directory not found: {docs_dir}")

    return docs


async def _index_doc(doc: Dict) -> bool:
    """Read one doc file and store it in memories for search.

    Skips indexing if the file content hash matches doc_index AND the memory row still exists.
    Re-indexes if content changed or the memory was deleted externally.
    Returns True on success, False if the file is missing or indexing fails.
    """
    doc_path = Path(__file__).parent.parent.parent / doc["file_path"]
    if not doc_path.exists():
        doc_path = Path("/app") / doc["file_path"]
    if not doc_path.exists():
        print(f"WARNING: Documentation file not found: {doc_path}")
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
            # Hash matches — verify the memory row still exists before skipping.
            # If memory_id is NULL (migrated from older doc_index), fall through to
            # re-index once so the row gets a valid memory_id backfilled.
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

        # Remove the existing memory before re-indexing.
        # Use memory_id for an exact delete when available; fall back to json_extract.
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
                (source_file, content_hash, new_memory_id, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

        action = "Updated" if (row and row[0] != content_hash) else "Indexed"
        print(f"OK: {action} {fname} ({len(content)} chars)")
        return True

    except Exception as e:
        try:
            print(f"ERROR: Failed to load {doc['file_path']}: {str(e)}")
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
    """Load docs if not loaded, then upsert the session row with marm_active."""
    await ensure_docs_loaded()
    try:
        with memory.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_name, marm_active, last_accessed)"
                " VALUES (?, TRUE, ?)",
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

    # One-time cleanup of system-created notebook entries from older MARM versions.
    # These were never user data — the notebook is now user territory only.
    with memory.get_connection() as conn:
        already_cleaned = conn.execute(
            "SELECT value FROM user_settings WHERE key = 'system_notebook_cleanup_v1'"
        ).fetchone()
        if not already_cleaned:
            for name in _LEGACY_SYSTEM_NOTEBOOK_NAMES:
                conn.execute("DELETE FROM notebook_entries WHERE name = ?", (name,))
            conn.execute(
                "INSERT OR REPLACE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("system_notebook_cleanup_v1", "done", datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
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
        print(f"WARNING: {failures} doc(s) failed to index — will retry on next tool call")
