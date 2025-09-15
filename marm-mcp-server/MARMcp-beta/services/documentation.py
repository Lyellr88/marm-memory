"""Documentation loading service for MARM MCP Server."""

from pathlib import Path
from datetime import datetime, timezone
import sqlite3
from typing import Dict, List

# Import core components
from core.memory import memory

async def load_marm_documentation():
    """Pre-populate the MCP server with core MARM documentation"""
    
    # Define the documentation files to load
    docs_to_load = [
        {
            "file_path": "marm-docs/PROTOCOL.md",
            "notebook_name": "marm_protocol",
            "context_type": "protocol",
            "description": "Complete MARM protocol specification and commands"
        },
        {
            "file_path": "marm-docs/HANDBOOK.md", 
            "notebook_name": "marm_handbook",
            "context_type": "handbook",
            "description": "MARM user handbook and implementation guide"
        },
        {
            "file_path": "marm-docs/README.md",
            "notebook_name": "marm_readme", 
            "context_type": "general",
            "description": "MARM project overview and getting started"
        },
        {
            "file_path": "marm-docs/FAQ.md",
            "notebook_name": "marm_faq",
            "context_type": "support", 
            "description": "Frequently asked questions about MARM"
        },
        {
            "file_path": "marm-docs/DESCRIPTION.md",
            "notebook_name": "marm_description",
            "context_type": "general",
            "description": "MARM project description and core concepts"
        }
    ]
    
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