"""Documentation loading service for MARM MCP Server."""

from pathlib import Path
from datetime import datetime, timezone
import sqlite3
from typing import Dict, List

# Import core components
from core.memory import memory

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
    """Auto-discover essential .md files only to avoid token overload"""
    # Try local development path first
    docs_dir = Path(__file__).parent.parent / "marm-docs"

    # If not found, try Docker path
    if not docs_dir.exists():
        docs_dir = Path("/app/marm-docs")

    # Essential files only - keep startup lean
    essential_files = {
        "PROTOCOL.md",    # Core commands - always needed
        "README.md"      # Tool usage and getting started info
    }

    docs_to_load = []
    seen_notebook_names = set()

    if docs_dir.exists():
        for md_file in sorted(docs_dir.glob("*.md")):
            # Skip non-essential files to reduce token dump
            if md_file.name not in essential_files:
                continue

            filename = md_file.stem.lower()  # "PROTOCOL.md" → "protocol"
            notebook_name = f"marm_{filename}"

            # Check for duplicate notebook names (same stem)
            if notebook_name in seen_notebook_names:
                print(f"WARNING: Duplicate notebook name detected: {notebook_name} (from {md_file.name})")
                # Add timestamp to make unique
                import time
                timestamp = str(int(time.time()))[-4:]  # last 4 digits
                notebook_name = f"marm_{filename}_{timestamp}"
                print(f"         Renamed to: {notebook_name}")

            seen_notebook_names.add(notebook_name)
            context_type = guess_context_type(filename)

            # Auto-generate config based on filename
            docs_to_load.append({
                "file_path": f"marm-docs/{md_file.name}",
                "notebook_name": notebook_name,
                "context_type": context_type,
                "description": f"Essential: {md_file.name}"
            })

        # Print visual QA table of loaded docs
        if docs_to_load:
            print(f"\n[DOCS] Loading essential documentation ({len(docs_to_load)} files):")
            print("+---------------------------------+--------------+-------------------------+")
            print("| File                            | Type         | Notebook Name           |")
            print("+---------------------------------+--------------+-------------------------+")
            for doc in docs_to_load:
                filename = doc["file_path"].split("/")[-1]
                print(f"| {filename:<31} | {doc['context_type']:<12} | {doc['notebook_name']:<23} |")
            print("+---------------------------------+--------------+-------------------------+")

            # Show what's available but not loaded
            all_files = set(f.name for f in docs_dir.glob("*.md"))
            skipped_files = all_files - essential_files
            if skipped_files:
                print(f"Available via marm_smart_recall: {', '.join(sorted(skipped_files))}")
        else:
            print("No essential documentation files found")
    else:
        print(f"WARNING: Documentation directory not found: {docs_dir}")

    return docs_to_load

async def load_marm_documentation():
    """Pre-populate the MCP server with core MARM documentation"""

    # Auto-discover all documentation files
    docs_to_load = get_docs_to_load()
    
    print("Loading MARM documentation into memory system...")
    
    for doc in docs_to_load:
        try:
            # Try to read the documentation file - works in both local and Docker
            # First try relative to current file location (local development)
            doc_path = Path(__file__).parent.parent / doc["file_path"]
            
            # If not found, try Docker app directory
            if not doc_path.exists():
                doc_path = Path("/app") / doc["file_path"]
            if doc_path.exists():
                with open(doc_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Store in memory system for semantic search
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
                
                # Also store in notebook for easy reference
                embedding_bytes = None
                if memory.encoder:
                    try:
                        embedding = memory.encoder.encode(content)
                        embedding_bytes = embedding.tobytes()
                    except Exception as e:
                        print(f"Failed to generate embedding for {doc['notebook_name']}: {e}")
                
                with sqlite3.connect(memory.db_path) as conn:
                    conn.execute('''
                        INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at)
                        VALUES (?, ?, ?, ?)
                    ''', (doc["notebook_name"], content, embedding_bytes, datetime.now(timezone.utc).isoformat()))
                    conn.commit()
                
                print(f"OK: Loaded {doc['notebook_name']} ({len(content)} chars)")
                
            else:
                print(f"WARNING: Documentation file not found: {doc_path}")
                
        except Exception as e:
            # Safe error printing - avoid unicode issues
            try:
                print(f"ERROR: Failed to load {doc['notebook_name']}: {str(e)}")
            except UnicodeEncodeError:
                print(f"ERROR: Failed to load {doc['notebook_name']}: {type(e).__name__}")
    
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
    
    print("MARM documentation database ready!")