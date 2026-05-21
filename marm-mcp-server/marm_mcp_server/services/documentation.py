"""Documentation loading service for MARM MCP Server."""

from pathlib import Path
from datetime import datetime, timezone
import sqlite3
from typing import Dict, List

# Import core components
from ..core.memory import memory

def guess_context_type(filename):
    """Smart context classification based on filename"""
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
    """Return two lists: essential docs (memories + notebook) and search-only docs (memories only)."""
    docs_dir = Path(__file__).parent.parent.parent / "marm-docs"
    if not docs_dir.exists():
        docs_dir = Path("/app/marm-docs")

    # Loaded at startup into memories + notebook (active context)
    essential_files = {
        "PROTOCOL.md"
    }

    essential_docs = []
    search_only_docs = []
    seen_notebook_names = set()

    if docs_dir.exists():
        for md_file in sorted(docs_dir.glob("*.md")):
            filename = md_file.stem.lower()
            context_type = guess_context_type(filename)
            entry = {
                "file_path": f"marm-docs/{md_file.name}",
                "context_type": context_type,
            }

            if md_file.name in essential_files:
                notebook_name = f"marm_{filename}"
                if notebook_name in seen_notebook_names:
                    import time
                    notebook_name = f"marm_{filename}_{str(int(time.time()))[-4:]}"
                seen_notebook_names.add(notebook_name)
                entry["notebook_name"] = notebook_name
                entry["description"] = f"Essential: {md_file.name}"
                essential_docs.append(entry)
            else:
                entry["notebook_name"] = None
                entry["description"] = f"Search: {md_file.name}"
                search_only_docs.append(entry)

        if essential_docs:
            print(f"\n[DOCS] Startup docs ({len(essential_docs)} files — memories + notebook):")
            print("+---------------------------------+--------------+-------------------------+")
            print("| File                            | Type         | Notebook Name           |")
            print("+---------------------------------+--------------+-------------------------+")
            for doc in essential_docs:
                fname = doc["file_path"].split("/")[-1]
                print(f"| {fname:<31} | {doc['context_type']:<12} | {doc['notebook_name']:<23} |")
            print("+---------------------------------+--------------+-------------------------+")

        if search_only_docs:
            names = ", ".join(d["file_path"].split("/")[-1] for d in search_only_docs)
            print(f"[DOCS] Indexed for marm_smart_recall only: {names}")
    else:
        print(f"WARNING: Documentation directory not found: {docs_dir}")

    return essential_docs, search_only_docs

async def _index_doc(doc: Dict, include_notebook: bool) -> bool:
    """Read one doc file and store it in memories (and optionally notebook).

    Returns True on success, False if the file is missing or indexing fails.
    """
    doc_path = Path(__file__).parent.parent.parent / doc["file_path"]
    if not doc_path.exists():
        doc_path = Path("/app") / doc["file_path"]
    if not doc_path.exists():
        print(f"WARNING: Documentation file not found: {doc_path}")
        return False

    try:
        with open(doc_path, 'r', encoding='utf-8') as f:
            content = f.read()

        await memory.store_memory(
            content=content,
            session="marm_system",
            context_type=doc["context_type"],
            metadata={
                "doc_type": "documentation",
                "source_file": doc["file_path"],
                "description": doc["description"]
            }
        )

        if include_notebook:
            embedding_bytes = None
            if memory.encoder:
                try:
                    embedding = memory.encoder.encode(content)
                    embedding_bytes = embedding.tobytes()
                except Exception as e:
                    print(f"Failed to generate embedding for {doc['notebook_name']}: {e}")

            with sqlite3.connect(memory.db_path) as conn:
                conn.execute(
                    'INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at) VALUES (?, ?, ?, ?)',
                    (doc["notebook_name"], content, embedding_bytes, datetime.now(timezone.utc).isoformat())
                )
                conn.commit()
            print(f"OK: Loaded {doc['notebook_name']} ({len(content)} chars)")
        else:
            print(f"OK: Indexed for search: {doc['file_path'].split('/')[-1]} ({len(content)} chars)")

        return True

    except Exception as e:
        try:
            print(f"ERROR: Failed to load {doc['file_path']}: {str(e)}")
        except UnicodeEncodeError:
            print(f"ERROR: Failed to load {doc['file_path']}: {type(e).__name__}")
        return False


_docs_loaded: bool = False


def docs_are_loaded() -> bool:
    return _docs_loaded


async def reload_marm_documentation():
    """Force a fresh doc load regardless of prior state."""
    global _docs_loaded
    _docs_loaded = False
    await load_marm_documentation()


async def load_marm_documentation():
    """Pre-populate the MCP server with core MARM documentation"""
    global _docs_loaded

    essential_docs, search_only_docs = get_docs_to_load()

    print("Loading MARM documentation into memory system...")

    missing_essential_docs = len(essential_docs) == 0
    essential_failures = 0
    for doc in essential_docs:
        if not await _index_doc(doc, include_notebook=True):
            essential_failures += 1

    for doc in search_only_docs:
        await _index_doc(doc, include_notebook=False)
    
    # Add some core knowledge entries
    core_knowledge = [
        {
            "name": "marm_commands_summary",
            "content": """MARM Core Commands Quick Reference:

SESSION COMMANDS:
- /start marm - Activates MARM memory and accuracy layers
- /refresh marm - Refreshes active session state

LOGGING COMMANDS:
- /log session: [name] - Create or switch to named session
- /log entry: [YYYY-MM-DD-topic-summary] - Add structured log entry
- /log show: [session] - Display all entries and sessions
- /log delete: [session/entry] - Delete specified session or entry

REASONING COMMANDS:
- /summary: [session] - Generate paste-ready context block
- /context_bridge: [new topic] - Intelligent workflow transitions

NOTEBOOK COMMANDS:
- /notebook add: [name] [data] - Add new entry
- /notebook use: [name1,name2] - Activate entries as instructions  
- /notebook show: - Display all saved entries
- /notebook delete: [name] - Delete specific entry
- /notebook clear: - Clear active list
- /notebook status: - Show current active list"""
        },
        {
            "name": "mcp_integration_guide", 
            "content": """MARM MCP Server Integration Guide:

This MCP server provides all MARM protocol functionality to Claude Desktop through these endpoints:

MEMORY SYSTEM:
- marm_smart_recall - Semantic search across all memories
- marm_contextual_log - Auto-classifying memory storage

PROTOCOL COMMANDS:  
- marm_start / marm_refresh - Session management
- marm_log_session / marm_log_entry / marm_log_show / marm_log_delete - Logging
- marm_summary / marm_context_bridge - Reasoning and workflow transitions
- marm_notebook_* - All 6 notebook management functions

SYSTEM:
- marm_current_context - Current date/time and system status

The MCP server uses semantic search with sentence transformers, SQLite storage, and event-driven automation for intelligent memory management."""
        }
    ]
    
    for knowledge in core_knowledge:
        try:
            embedding_bytes = None
            if memory.encoder:
                try:
                    embedding = memory.encoder.encode(knowledge["content"])
                    embedding_bytes = embedding.tobytes()
                except Exception as e:
                    print(f"Failed to generate embedding for {knowledge['name']}: {e}")
            
            with sqlite3.connect(memory.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at)
                    VALUES (?, ?, ?, ?)
                ''', (knowledge["name"], knowledge["content"], embedding_bytes, datetime.now(timezone.utc).isoformat()))
                conn.commit()
            
            print(f"OK: Added core knowledge: {knowledge['name']}")
            
        except Exception as e:
            # Safe error printing - avoid unicode issues
            try:
                print(f"ERROR: Failed to add {knowledge['name']}: {str(e)}")
            except UnicodeEncodeError:
                print(f"ERROR: Failed to add {knowledge['name']}: {type(e).__name__}")
    
    if not missing_essential_docs and essential_failures == 0:
        print("MARM documentation database ready!")
        _docs_loaded = True
    elif missing_essential_docs:
        print("WARNING: No essential documentation files found — will retry on next marm_start")
    else:
        print(f"WARNING: {essential_failures} essential doc(s) failed to index — will retry on next marm_start")
