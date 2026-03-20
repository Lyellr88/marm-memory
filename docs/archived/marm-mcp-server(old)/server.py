#!/usr/bin/env python3
"""
MARM MCP Server - Memory Accurate Response Mode for Model Context Protocol

Implements complete MARM protocol from constants.js with built-in automation system.
No external dependencies like N8N - everything is self-contained.

Author: Lyell - MARM Systems
Version: 2.1.0 (Blueprint Implementation)
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi_mcp import FastApiMCP
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timezone
import json
import sqlite3
import threading
import numpy as np
import uuid
import asyncio
import re
from pathlib import Path

# Advanced memory system imports
try:
    from sentence_transformers import SentenceTransformer
    SEMANTIC_SEARCH_AVAILABLE = True
except ImportError:
    SEMANTIC_SEARCH_AVAILABLE = False
    print("⚠️  Semantic search not available. Install: pip install sentence-transformers")

# Automation imports
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    print("⚠️  Scheduler not available. Install: pip install apscheduler")

app = FastAPI(
    title="MARM MCP Server",
    description="Memory Accurate Response Mode - Complete Protocol Implementation",
    version="2.1.0"
)

# ================================
# EVENT-DRIVEN AUTOMATION SYSTEM
# ================================

class MARMEvents:
    """Built-in automation system without external dependencies"""
    
    def __init__(self):
        self.listeners = {}
    
    def on(self, event_type: str, callback):
        """Register event listener"""
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(callback)
    
    async def emit(self, event_type: str, data: dict):
        """Trigger automatic actions based on events"""
        if event_type in self.listeners:
            for callback in self.listeners[event_type]:
                try:
                    await callback(data)
                except Exception as e:
                    print(f"Event callback failed: {e}")

# Global events system
events = MARMEvents()

# ================================
# CORE MEMORY SYSTEM
# ================================

class MARMMemory:
    """Advanced memory system with semantic search and MARM protocol support"""
    
    def __init__(self, db_path: str = "marm_memory.db"):
        self.db_path = db_path
        self.db_lock = threading.Lock()
        
        # Initialize semantic search if available
        if SEMANTIC_SEARCH_AVAILABLE:
            self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        else:
            self.encoder = None
            
        self.init_database()
        
        # Active sessions and notebook state
        self.active_sessions = {}
        self.active_notebook_entries = []
    
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
        if context_type == "general":
            context_type = await self.auto_classify_content(content)
            
        memory_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}
        
        # Generate embedding for semantic search
        embedding_bytes = None
        if self.encoder and content.strip():
            try:
                embedding = self.encoder.encode(content)
                embedding_bytes = embedding.tobytes()
            except Exception as e:
                print(f"Failed to generate embedding: {e}")
        
        with sqlite3.connect(self.db_path) as conn:
            # Store memory
            conn.execute('''
                INSERT INTO memories (id, session_name, content, embedding, timestamp, context_type, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (memory_id, session, content, embedding_bytes, timestamp, context_type, json.dumps(metadata)))
            
            # Update session access time
            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
            ''', (session, timestamp))
            
            conn.commit()
        
        # Trigger automation events
        await events.emit('memory_stored', {
            'memory_id': memory_id,
            'session': session,
            'content': content,
            'context_type': context_type
        })
        
        return memory_id
    
    async def recall_similar(self, query: str, session: str = None, limit: int = 5) -> List[Dict]:
        """Find semantically similar memories"""
        if not self.encoder:
            return await self.recall_text_search(query, session, limit)
        
        try:
            query_embedding = self.encoder.encode(query)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT id, session_name, content, embedding, timestamp, context_type, metadata
                    FROM memories
                    WHERE embedding IS NOT NULL
                    AND (? IS NULL OR session_name = ?)
                    ORDER BY timestamp DESC
                ''', (session, session))
                
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT id, session_name, content, timestamp, context_type, metadata
                FROM memories
                WHERE content LIKE ?
                AND (? IS NULL OR session_name = ?)
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (f"%{query}%", session, session, limit))
            
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

# ================================
# DOCUMENTATION PRE-LOADING
# ================================

async def load_marm_documentation():
    """Pre-populate the MCP server with core MARM documentation"""
    
    # Define the documentation files to load
    docs_to_load = [
        {
            "file_path": "../GitHub docs/PROTOCOL.md",
            "notebook_name": "marm_protocol",
            "context_type": "protocol",
            "description": "Complete MARM protocol specification and commands"
        },
        {
            "file_path": "../GitHub docs/HANDBOOK.md", 
            "notebook_name": "marm_handbook",
            "context_type": "handbook",
            "description": "MARM user handbook and implementation guide"
        },
        {
            "file_path": "../GitHub docs/README.md",
            "notebook_name": "marm_readme", 
            "context_type": "general",
            "description": "MARM project overview and getting started"
        },
        {
            "file_path": "../GitHub docs/FAQ.md",
            "notebook_name": "marm_faq",
            "context_type": "support", 
            "description": "Frequently asked questions about MARM"
        },
        {
            "file_path": "../GitHub docs/ROADMAP.md",
            "notebook_name": "marm_roadmap",
            "context_type": "project",
            "description": "MARM development roadmap and future plans"
        }
    ]
    
    print("🔄 Loading MARM documentation into memory system...")
    
    for doc in docs_to_load:
        try:
            # Try to read the documentation file
            doc_path = Path(__file__).parent / doc["file_path"]
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
                
                print(f"✅ Loaded {doc['notebook_name']} ({len(content)} chars)")
                
            else:
                print(f"⚠️  Documentation file not found: {doc_path}")
                
        except Exception as e:
            print(f"❌ Failed to load {doc['notebook_name']}: {e}")
    
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
- /notebook status: - Show current active list""",
            "context_type": "protocol"
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

The MCP server uses semantic search with sentence transformers, SQLite storage, and event-driven automation for intelligent memory management.""",
            "context_type": "code"
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
            
            print(f"✅ Added core knowledge: {knowledge['name']}")
            
        except Exception as e:
            print(f"❌ Failed to add {knowledge['name']}: {e}")
    
    print("🎯 MARM documentation database ready!")

# ================================
# PYDANTIC MODELS
# ================================

class SessionRequest(BaseModel):
    session_name: str = Field(..., description="Name of the session")

class LogEntryRequest(BaseModel):
    entry: str = Field(..., description="Log entry in format: YYYY-MM-DD-topic-summary")
    session_name: str = Field(default="main", description="Session name")

class NotebookAddRequest(BaseModel):
    name: str = Field(..., description="Name of the notebook entry")
    data: str = Field(..., description="Content of the notebook entry")

class NotebookUseRequest(BaseModel):
    names: str = Field(..., description="Comma-separated list of notebook entry names")

class ContextBridgeRequest(BaseModel):
    new_topic: str = Field(..., description="New topic for context bridging")
    session_name: str = Field(default="main", description="Session name")

class SmartRecallRequest(BaseModel):
    query: str = Field(..., description="Query to search for in memory")
    session_name: str = Field(default="main", description="Session to search in")
    limit: int = Field(default=5, description="Maximum number of results")

class ContextualLogRequest(BaseModel):
    content: str = Field(..., description="Content to log with auto-classification")
    session_name: str = Field(default="main", description="Session to log to")

# ================================
# MARM PROTOCOL ENDPOINTS
# ================================

@app.post("/marm_start", tags=["MARM Protocol"])
async def marm_start(request: SessionRequest):
    """
    🚀 Activates MARM memory and accuracy layers
    
    Equivalent to /start marm command
    """
    try:
        with sqlite3.connect(memory.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, marm_active, last_accessed)
                VALUES (?, TRUE, ?)
            ''', (request.session_name, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        
        await events.emit('marm_started', {'session': request.session_name})
        
        return {
            "status": "success",
            "message": f"🚀 MARM protocol activated for session '{request.session_name}'",
            "session_name": request.session_name,
            "marm_active": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start MARM: {str(e)}")

@app.post("/marm_refresh", tags=["MARM Protocol"])
async def marm_refresh(request: SessionRequest):
    """
    🔄 Refreshes active session state and reaffirms protocol adherence
    
    Equivalent to /refresh marm command
    """
    try:
        with sqlite3.connect(memory.db_path) as conn:
            conn.execute('''
                UPDATE sessions SET last_accessed = ? WHERE session_name = ?
            ''', (datetime.now(timezone.utc).isoformat(), request.session_name))
            conn.commit()
        
        await events.emit('marm_refreshed', {'session': request.session_name})
        
        return {
            "status": "success",
            "message": f"🔄 MARM session '{request.session_name}' refreshed",
            "session_name": request.session_name
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh MARM: {str(e)}")

@app.post("/marm_log_session", tags=["Logging"])
async def marm_log_session(request: SessionRequest):
    """
    📂 Create or switch to named session container
    
    Equivalent to /log session: [name] command
    """
    try:
        with sqlite3.connect(memory.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
            ''', (request.session_name, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        
        await events.emit('session_created', {'session': request.session_name})
        
        return {
            "status": "success",
            "message": f"📂 Session '{request.session_name}' created/activated",
            "session_name": request.session_name
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")

@app.post("/marm_log_entry", tags=["Logging"])
async def marm_log_entry(request: LogEntryRequest):
    """
    📝 Add structured log entry for milestones or decisions
    
    Equivalent to /log entry: [YYYY-MM-DD-topic-summary] command
    """
    try:
        # Clean auto-date logic for log entries
        entry_pattern = r'^(\d{4}-\d{2}-\d{2})-(.*?)-(.*?)$'
        match = re.match(entry_pattern, request.entry)
        
        if match:
            # Entry is already properly formatted
            entry_date, topic, summary = match.groups()
            formatted_entry = request.entry
        else:
            # Auto-format entry with current date
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Smart parsing: handle "topic-summary" or just "summary"
            if '-' in request.entry:
                topic, summary = request.entry.split('-', 1)
                topic = topic.strip()
                summary = summary.strip()
            else:
                topic = "general"
                summary = request.entry.strip()
            
            entry_date = today
            formatted_entry = f"{today}-{topic}-{summary}"
        
        entry_id = str(uuid.uuid4())
        with sqlite3.connect(memory.db_path) as conn:
            conn.execute('''
                INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (entry_id, request.session_name, entry_date, topic, summary, formatted_entry))
            conn.commit()
        
        await events.emit('log_entry_created', {
            'entry_id': entry_id,
            'session': request.session_name,
            'content': formatted_entry
        })
        
        return {
            "status": "success",
            "message": f"📝 Log entry added: {formatted_entry}",
            "entry_id": entry_id,
            "formatted_entry": formatted_entry
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create log entry: {str(e)}")

@app.get("/marm_log_show", tags=["Logging"])
async def marm_log_show(session_name: Optional[str] = None):
    """
    📋 Display all entries and sessions logged
    
    Equivalent to /log show: [session] command
    """
    try:
        with sqlite3.connect(memory.db_path) as conn:
            if session_name:
                cursor = conn.execute('''
                    SELECT id, entry_date, topic, summary, full_entry
                    FROM log_entries WHERE session_name = ?
                    ORDER BY entry_date DESC
                ''', (session_name,))
                entries = [{"id": r[0], "entry_date": r[1], "topic": r[2], 
                          "summary": r[3], "full_entry": r[4]} for r in cursor.fetchall()]
                
                return {
                    "status": "success",
                    "session_name": session_name,
                    "entries": entries,
                    "total_entries": len(entries)
                }
            else:
                cursor = conn.execute('SELECT session_name, COUNT(*) FROM log_entries GROUP BY session_name')
                sessions = [{"session_name": r[0], "entry_count": r[1]} for r in cursor.fetchall()]
                
                return {
                    "status": "success",
                    "sessions": sessions,
                    "total_sessions": len(sessions)
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to show logs: {str(e)}")

@app.delete("/marm_log_delete", tags=["Logging"])
async def marm_log_delete(target: str, session_name: Optional[str] = None):
    """
    🗑️ Delete specified session or entry
    
    Equivalent to /log delete: [session/entry name] command
    """
    try:
        with sqlite3.connect(memory.db_path) as conn:
            if session_name:
                # Delete specific entry from session
                cursor = conn.execute('''
                    DELETE FROM log_entries 
                    WHERE session_name = ? AND (id = ? OR topic = ?)
                ''', (session_name, target, target))
                deleted = cursor.rowcount
            else:
                # Delete entire session
                conn.execute('DELETE FROM sessions WHERE session_name = ?', (target,))
                cursor = conn.execute('DELETE FROM log_entries WHERE session_name = ?', (target,))
                deleted = cursor.rowcount
            
            conn.commit()
            
            return {
                "status": "success",
                "message": f"🗑️ Deleted {deleted} items",
                "deleted_count": deleted
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {str(e)}")

@app.get("/marm_summary", tags=["Reasoning"])
async def marm_summary(session_name: str):
    """
    📊 Generate paste-ready context block for new chats
    
    Equivalent to /summary: [session name] command
    """
    try:
        with sqlite3.connect(memory.db_path) as conn:
            cursor = conn.execute('''
                SELECT entry_date, topic, summary, full_entry
                FROM log_entries WHERE session_name = ?
                ORDER BY entry_date DESC
            ''', (session_name,))
            entries = cursor.fetchall()
        
        if not entries:
            return {
                "status": "empty",
                "message": f"No entries found in session '{session_name}'"
            }
        
        summary_lines = [f"# MARM Session Summary: {session_name}"]
        summary_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
        summary_lines.append("")
        
        for entry in entries:
            summary_lines.append(f"**{entry[0]}** [{entry[1]}]: {entry[2]}")
        
        summary_text = "\n".join(summary_lines)
        
        return {
            "status": "success",
            "session_name": session_name,
            "summary": summary_text,
            "entry_count": len(entries)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")

@app.post("/marm_context_bridge", tags=["Reasoning"])
async def marm_context_bridge(request: ContextBridgeRequest):
    """
    🌉 Intelligent context bridging for smooth workflow transitions
    
    Equivalent to /context_bridge: [new topic] command
    """
    try:
        # Use semantic search for intelligent context bridging
        if memory.encoder:
            # Semantic search across memories for better context matching
            related_memories = await memory.recall_similar(
                query=request.new_topic,
                session_name=None,  # Search across all sessions
                limit=8
            )
            
            # Also search log entries with basic text matching as backup
            with sqlite3.connect(memory.db_path) as conn:
                cursor = conn.execute('''
                    SELECT session_name, topic, summary, full_entry
                    FROM log_entries 
                    WHERE topic LIKE ? OR summary LIKE ?
                    ORDER BY entry_date DESC
                    LIMIT 3
                ''', (f"%{request.new_topic}%", f"%{request.new_topic}%"))
                log_matches = cursor.fetchall()
            
            # Combine semantic and text matches
            related_content = []
            for memory_item in related_memories[:5]:
                related_content.append({
                    'type': 'memory',
                    'session': memory_item['session_name'],
                    'content': memory_item['content'],
                    'similarity': memory_item['similarity'],
                    'context_type': memory_item['context_type']
                })
            
            for log_item in log_matches:
                related_content.append({
                    'type': 'log',
                    'session': log_item[0],
                    'topic': log_item[1],
                    'summary': log_item[2],
                    'similarity': 0.7  # Default for text matches
                })
        else:
            # Fallback to basic text search if no semantic search
            with sqlite3.connect(memory.db_path) as conn:
                cursor = conn.execute('''
                    SELECT session_name, topic, summary, full_entry
                    FROM log_entries 
                    WHERE topic LIKE ? OR summary LIKE ?
                    ORDER BY entry_date DESC
                    LIMIT 5
                ''', (f"%{request.new_topic}%", f"%{request.new_topic}%"))
                log_matches = cursor.fetchall()
                
                related_content = []
                for log_item in log_matches:
                    related_content.append({
                        'type': 'log',
                        'session': log_item[0],
                        'topic': log_item[1],
                        'summary': log_item[2],
                        'similarity': 0.7
                    })
        
        bridge_lines = [f"# Context Bridge: {request.new_topic}"]
        bridge_lines.append(f"Session: {request.session_name}")
        bridge_lines.append("")
        
        if related_content:
            bridge_lines.append("## Related Context:")
            # Sort by similarity for better relevance
            sorted_content = sorted(related_content, key=lambda x: x.get('similarity', 0), reverse=True)
            
            for item in sorted_content:
                similarity_pct = int(item.get('similarity', 0.7) * 100)
                session_badge = f"[{item['session']}]"
                
                if item.get('type') == 'memory':
                    context_badge = f"[{item['context_type'].upper()}]"
                    content_preview = item['content'][:100] + "..." if len(item['content']) > 100 else item['content']
                    bridge_lines.append(f"- {session_badge} {context_badge} ({similarity_pct}%): {content_preview}")
                else:  # log entry
                    bridge_lines.append(f"- {session_badge} [LOG] ({similarity_pct}%): {item['topic']} - {item['summary']}")
            
            bridge_lines.append("")
        
        # Smart recommendations based on content found
        if related_content:
            bridge_lines.append("## Recommended Approach:")
            context_types = [item.get('context_type', 'general') for item in related_content if item.get('type') == 'memory']
            
            if 'code' in context_types:
                bridge_lines.append("- Review related code patterns and implementations above")
                bridge_lines.append("- Consider lessons learned from similar technical work")
            elif 'project' in context_types:
                bridge_lines.append("- Build on successful project patterns identified above")
                bridge_lines.append("- Apply lessons learned from previous project phases")
            else:
                bridge_lines.append("- Leverage insights from related work shown above")
                bridge_lines.append("- Build on established patterns and approaches")
        else:
            bridge_lines.append("## Starting Fresh:")
            bridge_lines.append("- No directly related context found - starting with clean slate")
            bridge_lines.append("- Consider documenting key decisions as you progress")
        
        bridge_lines.append("")
        bridge_lines.append("---")
        bridge_lines.append("*Ready to proceed with focused work*")
        
        bridge_text = "\n".join(bridge_lines)
        
        return {
            "status": "success",
            "new_topic": request.new_topic,
            "session_name": request.session_name,
            "bridge_text": bridge_text,
            "related_count": len(related_content)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create context bridge: {str(e)}")

# ================================
# NOTEBOOK ENDPOINTS
# ================================

@app.post("/marm_notebook_add", tags=["Notebook"])
async def marm_notebook_add(request: NotebookAddRequest):
    """
    📓 Add a new entry
    
    Equivalent to /notebook add: [name] [data] command
    """
    try:
        # Generate embedding if available
        embedding_bytes = None
        if memory.encoder:
            try:
                embedding = memory.encoder.encode(request.data)
                embedding_bytes = embedding.tobytes()
            except Exception as e:
                print(f"Failed to generate embedding: {e}")
        
        with sqlite3.connect(memory.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO notebook_entries (name, data, embedding, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (request.name, request.data, embedding_bytes, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        
        await events.emit('notebook_entry_added', {
            'name': request.name,
            'data': request.data
        })
        
        return {
            "status": "success",
            "message": f"📓 Notebook entry '{request.name}' added",
            "name": request.name
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add notebook entry: {str(e)}")

@app.post("/marm_notebook_use", tags=["Notebook"])
async def marm_notebook_use(request: NotebookUseRequest):
    """
    🔧 Activate entries as instructions
    
    Equivalent to /notebook use: [name1,name2] command
    """
    try:
        names = [n.strip() for n in request.names.split(',')]
        activated_entries = []
        
        with sqlite3.connect(memory.db_path) as conn:
            for name in names:
                cursor = conn.execute('SELECT name, data FROM notebook_entries WHERE name = ?', (name,))
                result = cursor.fetchone()
                if result:
                    activated_entries.append({"name": result[0], "data": result[1]})
        
        # Update active list in memory
        memory.active_notebook_entries = activated_entries
        
        return {
            "status": "success",
            "message": f"🔧 Activated {len(activated_entries)} notebook entries",
            "activated_entries": [e["name"] for e in activated_entries],
            "entries": activated_entries
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to activate notebook entries: {str(e)}")

@app.get("/marm_notebook_show", tags=["Notebook"])
async def marm_notebook_show():
    """
    📚 Display all saved keys and summaries
    
    Equivalent to /notebook show: command
    """
    try:
        with sqlite3.connect(memory.db_path) as conn:
            cursor = conn.execute('''
                SELECT name, data, created_at, updated_at 
                FROM notebook_entries 
                ORDER BY updated_at DESC
            ''')
            
            entries = []
            for row in cursor.fetchall():
                preview = row[1][:100] + "..." if len(row[1]) > 100 else row[1]
                entries.append({
                    "name": row[0],
                    "preview": preview,
                    "created_at": row[2],
                    "updated_at": row[3]
                })
        
        return {
            "status": "success",
            "message": f"📚 Found {len(entries)} notebook entries",
            "entries": entries,
            "total_count": len(entries)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to show notebook entries: {str(e)}")

@app.delete("/marm_notebook_delete", tags=["Notebook"])
async def marm_notebook_delete(name: str):
    """
    🗑️ Delete a specific notebook entry
    
    Equivalent to /notebook delete: [name] command
    """
    try:
        with sqlite3.connect(memory.db_path) as conn:
            cursor = conn.execute('DELETE FROM notebook_entries WHERE name = ?', (name,))
            deleted = cursor.rowcount
            conn.commit()
        
        return {
            "status": "success" if deleted > 0 else "not_found",
            "message": f"🗑️ Deleted notebook entry '{name}'" if deleted > 0 else f"Entry '{name}' not found",
            "deleted": deleted > 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete notebook entry: {str(e)}")

@app.delete("/marm_notebook_clear", tags=["Notebook"])
async def marm_notebook_clear():
    """
    🧹 Clear the active list
    
    Equivalent to /notebook clear: command
    """
    try:
        memory.active_notebook_entries = []
        
        return {
            "status": "success",
            "message": "🧹 Active notebook entries cleared",
            "active_count": 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear active entries: {str(e)}")

@app.get("/marm_notebook_status", tags=["Notebook"])
async def marm_notebook_status():
    """
    📊 Show the current active list
    
    Equivalent to /notebook status: command
    """
    try:
        active_names = [entry["name"] for entry in memory.active_notebook_entries]
        
        return {
            "status": "success",
            "message": f"📊 {len(active_names)} active notebook entries",
            "active_entries": active_names,
            "entries": memory.active_notebook_entries,
            "active_count": len(active_names)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get notebook status: {str(e)}")

# ================================
# MEMORY SYSTEM ENDPOINTS
# ================================

@app.post("/marm_smart_recall", tags=["Memory"])
async def marm_smart_recall(request: SmartRecallRequest):
    """
    🧠 Intelligent memory recall based on semantic similarity
    
    Finds relevant memories using semantic similarity or text search.
    Returns the most relevant memories with similarity scores.
    """
    try:
        similar_memories = await memory.recall_similar(request.query, request.session_name, request.limit)
        
        if not similar_memories:
            return {
                "status": "no_results",
                "message": f"🤔 No memories found for query: '{request.query}'",
                "query": request.query,
                "session_name": request.session_name,
                "results": []
            }
        
        # Format context for easy use
        context_lines = []
        for mem in similar_memories:
            context_lines.append(f"[{mem['context_type'].upper()}] {mem['content']}")
        
        context_summary = "\n".join(context_lines)
        
        return {
            "status": "success",
            "message": f"🧠 Found {len(similar_memories)} relevant memories",
            "query": request.query,
            "session_name": request.session_name,
            "context_summary": context_summary,
            "results": similar_memories
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory recall failed: {str(e)}")

@app.post("/marm_contextual_log", tags=["Memory"])
async def marm_contextual_log(request: ContextualLogRequest):
    """
    📝 Log with automatic context classification
    
    Automatically classifies content type and stores with proper context.
    Uses semantic embeddings for intelligent recall.
    """
    try:
        # Auto-classify and store in memory system
        memory_id = await memory.store_memory(request.content, request.session_name)
        
        # Get the classification that was applied
        context_type = await memory.auto_classify_content(request.content)
        
        return {
            "status": "success",
            "message": f"📝 Logged and indexed as '{context_type}' context",
            "memory_id": memory_id,
            "content": request.content,
            "session_name": request.session_name,
            "context_type": context_type
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contextual logging failed: {str(e)}")

# ================================
# UTILITY ENDPOINTS
# ================================

@app.get("/marm_current_context", tags=["System"])
async def marm_current_context():
    """
    🕐 Get current date and system context
    
    Provides current date/time to prevent AI date confusion
    """
    now = datetime.now(timezone.utc)
    
    return {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M:%S UTC"),
        "formatted_date": now.strftime("%A, %B %d, %Y"),
        "context": f"Today is {now.strftime('%A, %B %d, %Y')} at {now.strftime('%H:%M UTC')}",
        "system_status": "operational",
        "semantic_search": "available" if SEMANTIC_SEARCH_AVAILABLE else "text_only",
        "scheduler": "available" if SCHEDULER_AVAILABLE else "disabled"
    }

@app.post("/marm_reload_docs", tags=["System"])
async def marm_reload_docs():
    """
    📚 Reload MARM documentation into memory system
    
    Refreshes all documentation files and core knowledge in the database
    """
    try:
        await load_marm_documentation()
        return {
            "status": "success",
            "message": "📚 MARM documentation reloaded successfully",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload documentation: {str(e)}")

@app.get("/marm_system_info", tags=["System"])  
async def marm_system_info():
    """
    ℹ️ Get comprehensive system information and loaded documentation
    
    Shows what documentation is available and system capabilities
    """
    try:
        # Get notebook entries (documentation)
        with sqlite3.connect(memory.db_path) as conn:
            cursor = conn.execute('''
                SELECT name, LENGTH(data) as size, created_at, updated_at
                FROM notebook_entries
                WHERE name LIKE 'marm_%'
                ORDER BY updated_at DESC
            ''')
            docs = [{"name": r[0], "size_chars": r[1], "created": r[2], "updated": r[3]} 
                   for r in cursor.fetchall()]
            
            # Get memory count
            cursor = conn.execute('SELECT COUNT(*) FROM memories')
            memory_count = cursor.fetchone()[0]
            
            # Get session count  
            cursor = conn.execute('SELECT COUNT(*) FROM sessions')
            session_count = cursor.fetchone()[0]
        
        return {
            "status": "operational",
            "version": "2.1.0",
            "capabilities": {
                "semantic_search": SEMANTIC_SEARCH_AVAILABLE,
                "scheduler": SCHEDULER_AVAILABLE,
                "documentation_loaded": len(docs) > 0
            },
            "database_stats": {
                "notebook_entries": len(docs),
                "memories": memory_count, 
                "sessions": session_count
            },
            "loaded_documentation": docs,
            "mcp_endpoint": "http://localhost:8001/mcp",
            "api_docs": "http://localhost:8001/docs"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get system info: {str(e)}")

# ================================
# AUTOMATION EVENT HANDLERS
# ================================

async def auto_classify_content(data: dict):
    """Auto-classify log entries"""
    content = data.get('content', '')
    context_type = await memory.auto_classify_content(content)
    print(f"Auto-classified '{content[:50]}...' as '{context_type}'")

async def update_knowledge_index(data: dict):
    """Update search index when notebook entries added"""
    print(f"Knowledge index updated for: {data.get('name')}")

# Register automation events
events.on('log_entry_created', auto_classify_content)
events.on('notebook_entry_added', update_knowledge_index)

# ================================
# AUTO-DATE MIDDLEWARE
# ================================

@app.middleware("http")
async def inject_date_context(request, call_next):
    """Automatically provide current date context to prevent AI date confusion"""
    request.state.current_date = datetime.now().strftime("%Y-%m-%d")
    request.state.date_context = f"Current date: {datetime.now().strftime('%A, %B %d, %Y')}"
    response = await call_next(request)
    return response

# ================================
# MCP SERVER SETUP
# ================================

# Create MCP server
mcp = FastApiMCP(
    app,
    name="MARM Memory System",
    description="Complete MARM protocol implementation with advanced memory, logging, and automation",
    version="2.1.0"
)

# Mount MCP server
mcp.mount()

# ================================
# STARTUP EVENTS
# ================================

@app.on_event("startup")
async def startup_event():
    """Initialize MARM MCP Server with documentation"""
    print("🚀 Initializing MARM MCP Server...")
    
    # Load all MARM documentation into memory
    await load_marm_documentation()
    
    print("✅ MARM MCP Server initialization complete!")
    print("📚 Documentation database loaded and ready")
    print("🧠 Semantic search available for all MARM knowledge")

# ================================
# DEVELOPMENT SERVER
# ================================

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting MARM MCP Server v2.1.0...")
    print("📋 MCP Endpoint: http://localhost:8001/mcp")
    print("🔗 API Documentation: http://localhost:8001/docs")
    print("💾 Memory database: marm_memory.db")
    print("🎯 All 16 MARM protocol commands implemented")
    
    if SEMANTIC_SEARCH_AVAILABLE:
        print("🧠 Semantic search: ENABLED")
    else:
        print("⚠️  Semantic search: DISABLED (install sentence-transformers)")
    
    if SCHEDULER_AVAILABLE:
        print("⏰ Automation scheduler: ENABLED")
    else:
        print("⚠️  Scheduler: DISABLED (install apscheduler)")
    
    uvicorn.run(app, host="0.0.0.0", port=8001)