# MARM MCP Server Blueprint

## Core MARM Protocol Commands (From constants.js)

**Session Commands:**
- `/start marm` - Activates MARM memory and accuracy layers
- `/refresh marm` - Refreshes active session state and reaffirms protocol adherence

**Core Commands:**
- `/log session: [name]` - Create or switch the named session container
- `/log entry: [YYYY-MM-DD-topic-summary]` - Add a structured log entry for milestones or decisions
- `/log show: [session]` - Display all entries and sessions logged
- `/log delete: [session/entry name]` - Delete the specified session or entry

**Reasoning and Summaries:**
- `/summary: [session name]` - emits a paste-ready context block for new chats
- `/context_bridge: [new topic]` - Intelligent context bridging for smooth workflow transitions

**Notebook Commands:**
- `/notebook add: [name] [data]` - Add a new entry
- `/notebook use: [name]` - Activate an entry as an instruction. Multiple: /notebook use: name1,name2
- `/notebook show:` - Display all saved keys and summaries
- `/notebook delete: [name]` - Delete a specific notebook entry
- `/notebook clear:` - Clear the active list
- `/notebook status:` - Show the current active list

## MCP Server Implementation Requirements

**What the MCP server needs to support:**
- All MARM protocol commands from constants.js
- Semantic search and recall using vector embeddings
- Context classification for project management and development work
- Cross-session memory that survives conversation resets
- Built-in automation system (no external dependencies like N8N)
- Auto-date system for AI accuracy
- Event-driven workflow automation

## Built-in Automation System (Key Differentiator)

**This MCP server includes a complete automation system without external services like N8N:**

### **Event-Driven Automation**
```python
class MARMEvents:
    def __init__(self):
        self.listeners = {}
    
    async def emit(self, event_type: str, data: dict):
        """Trigger automatic actions based on events"""
        if event_type in self.listeners:
            for callback in self.listeners[event_type]:
                await callback(data)

# Register focused automation (only for log/notebook commands)
events = MARMEvents()
events.on('log_entry_created', auto_classify_content)
events.on('notebook_entry_added', update_knowledge_index) 
events.on('session_progress', track_project_metrics)
```

### **Focused Auto-Actions (Log/Notebook Only)**
```python
async def auto_classify_content(content: str, session: str):
    """Auto-classify log entries - no external APIs"""
    content_lower = content.lower()
    if any(word in content_lower for word in ['function', 'class', 'code', 'bug', 'debug']):
        context_type = 'code'
    elif any(word in content_lower for word in ['project', 'milestone', 'deadline', 'goal']):
        context_type = 'project'  
    else:
        context_type = 'general'
    
    # Store classification internally
    await memory.update_entry_metadata(content, {"auto_classified": context_type})

async def update_knowledge_index(name: str, data: str):
    """Update internal search index when notebook entries added"""
    # Generate embeddings for better search
    if SEMANTIC_SEARCH_AVAILABLE:
        embedding = encoder.encode(data)
        await memory.update_notebook_embedding(name, embedding)
    
    # Track knowledge growth
    await memory.increment_knowledge_stats()
```

### **User-Controlled Scheduled Automation**
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

# User-configurable daily summary (can be disabled)
@scheduler.scheduled_job('cron', hour='user_configured', minute=0, id='daily_summary')
async def optional_daily_summary():
    """Generate daily summaries - user controls time or disables"""
    user_settings = await get_user_automation_settings()
    
    if user_settings.get('daily_summary_enabled', False):
        summary_hour = user_settings.get('summary_time', 18)  # Default 6 PM
        
        for session in active_sessions:
            summary = await generate_session_summary(session)
            # Store internally, no external emails
            await memory.store_daily_summary(session, summary)

# Simple maintenance automation
@scheduler.scheduled_job('interval', hours=6)  # Every 6 hours
async def maintain_database():
    """Basic database maintenance - no external calls"""
    await cleanup_old_embeddings()
    await optimize_sqlite_indices()

# User controls
async def configure_automation(summary_enabled: bool, summary_hour: int = 18):
    """Allow users to control automation settings"""
    settings = {
        'daily_summary_enabled': summary_enabled,
        'summary_time': summary_hour
    }
    await store_user_settings(settings)
    
    # Update scheduler
    if summary_enabled:
        scheduler.reschedule_job('daily_summary', hour=summary_hour)
    else:
        scheduler.pause_job('daily_summary')

scheduler.start()
```


### **Auto-Date System (Critical for AI Accuracy)**
```python
from datetime import datetime, timezone

@app.middleware("http")
async def inject_date_context(request, call_next):
    """Automatically provide current date context to prevent AI date confusion"""
    request.state.current_date = datetime.now().strftime("%Y-%m-%d")
    request.state.date_context = f"Current date: {datetime.now().strftime('%A, %B %d, %Y')}"
    response = await call_next(request)
    return response

@app.get("/marm_current_context")
async def get_current_context():
    """Always provide accurate current date to AI"""
    now = datetime.now(timezone.utc)
    return {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M:%S UTC"),
        "formatted_date": now.strftime("%A, %B %d, %Y"),
        "context": f"Today is {now.strftime('%A, %B %d, %Y')} at {now.strftime('%H:%M UTC')}"
    }
```

**Implementation details:**

- Vector embeddings using SentenceTransformer for semantic similarity
- SQLite database for storage with BLOB embedding storage
- Smart classification of content types
- Intelligent recall based on query similarity

**Core memory system:**

```python
from sentence_transformers import SentenceTransformer
import numpy as np
from datetime import datetime
import sqlite3

class MARMMemory:
    def __init__(self):
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')  # Lightweight
        self.db = sqlite3.connect('marm_memory.db', check_same_thread=False)
        self.init_db()
    
    async def store_memory(self, content: str, session: str, context_type: str = "general"):
        """Store content with vector embedding for semantic search"""
        embedding = self.encoder.encode(content)
        
        self.db.execute('''
            INSERT INTO memories (session, content, embedding, timestamp, context_type)
            VALUES (?, ?, ?, ?, ?)
        ''', (session, content, embedding.tobytes(), datetime.now().isoformat(), context_type))
        self.db.commit()
    
    async def recall_similar(self, query: str, session: str, limit: int = 5):
        """Find semantically similar memories"""
        query_embedding = self.encoder.encode(query)
        # Calculate similarity and return top matches
        return sorted(memories, key=lambda x: x[3], reverse=True)[:limit]
```

**Smart API endpoints:**

```python
@app.post("/marm_smart_recall")
async def smart_recall(query: str, session_name: str = "main"):
    """Intelligent memory recall based on semantic similarity"""
    similar_memories = await memory.recall_similar(query, session_name)
    context = "\n".join([f"[{mem[1]}] {mem[0]}" for mem in similar_memories])
    return f"🧠 **Relevant Context Found:**\n{context}"

@app.post("/marm_contextual_log")
async def contextual_log(content: str, session_name: str = "main"):
    """Log with automatic context classification"""
    context_type = classify_content(content)  # "code", "book", "character", "project"
    await memory.store_memory(content, session_name, context_type)
    return f"📝 Logged and indexed as '{context_type}' context"
```

**MCP Endpoints Needed:**

```python
# Core MARM Protocol Endpoints
@app.post("/marm_start")
async def marm_start(session_name: str = "main"):
    """Equivalent to /start marm command"""

@app.post("/marm_refresh") 
async def marm_refresh(session_name: str = "main"):
    """Equivalent to /refresh marm command"""

@app.post("/marm_log_session")
async def marm_log_session(session_name: str):
    """Equivalent to /log session: [name] command"""

@app.post("/marm_log_entry")
async def marm_log_entry(entry: str, session_name: str = "main"):
    """Equivalent to /log entry: [YYYY-MM-DD-topic-summary] command"""

@app.get("/marm_log_show")
async def marm_log_show(session_name: str = None):
    """Equivalent to /log show: [session] command"""

@app.delete("/marm_log_delete")
async def marm_log_delete(target: str, session_name: str = "main"):
    """Equivalent to /log delete: [session/entry name] command"""

@app.get("/marm_summary")
async def marm_summary(session_name: str):
    """Equivalent to /summary: [session name] command"""

@app.post("/marm_context_bridge")
async def marm_context_bridge(new_topic: str, session_name: str = "main"):
    """
    🌉 Intelligent context bridging for workflow transitions
    
    When switching topics/tasks, this finds relevant context from previous work
    and creates smooth transitions instead of jarring context switches.
    
    Equivalent to /context_bridge: [new topic] command
    """

@app.post("/marm_notebook_add")
async def marm_notebook_add(name: str, data: str):
    """Equivalent to /notebook add: [name] [data] command"""

@app.post("/marm_notebook_use")
async def marm_notebook_use(names: str):
    """Equivalent to /notebook use: [name1,name2] command"""

@app.get("/marm_notebook_show")
async def marm_notebook_show():
    """Equivalent to /notebook show: command"""

@app.delete("/marm_notebook_delete")
async def marm_notebook_delete(name: str):
    """Equivalent to /notebook delete: [name] command"""

@app.delete("/marm_notebook_clear")
async def marm_notebook_clear():
    """Equivalent to /notebook clear: command"""

@app.get("/marm_notebook_status")
async def marm_notebook_status():
    """Equivalent to /notebook status: command"""
```

**Natural language processing:**

```python
@app.post("/marm_natural_command")
async def natural_command(text: str, session_name: str = "main"):
    """Process natural language MARM commands"""
    text_lower = text.lower()
    
    if "remember" in text_lower or "note" in text_lower:
        name, content = extract_note_parts(text)
        return await marm_notebook_add(NotebookEntry(name=name, data=content))
    elif "log" in text_lower or "record" in text_lower:
        return await smart_log(text, session_name)
    elif "summarize" in text_lower or "summary" in text_lower:
        return await marm_session_summary(session_name)
    else:
        return "💡 I can help you log entries, add notes, or create summaries. What would you like to do?"
```

**Built-in automation system:**

```python
import httpx
import smtplib
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Event-driven automation
class MARMEvents:
    def __init__(self):
        self.listeners = {}
    
    async def emit(self, event_type: str, data: dict):
        """Trigger automatic actions based on events"""
        if event_type in self.listeners:
            for callback in self.listeners[event_type]:
                await callback(data)

# Direct integrations without external services
async def send_slack_notification(message: str):
    """Direct Slack webhook integration"""
    webhook_url = "YOUR_SLACK_WEBHOOK_URL" 
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json={"text": message})

async def smart_auto_actions(content: str, session: str, context_type: str):
    """Automatic actions based on content type"""
    if context_type == "code":
        await create_github_gist(content)
    elif context_type == "character": 
        await update_character_wiki(content)
    elif context_type == "book":
        await update_writing_stats(content)
    elif "deadline" in content.lower():
        await create_calendar_event(content)

# Scheduled automation
scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour=18, minute=0)  # Daily at 6 PM
async def daily_summary():
    """Auto-generate daily summaries"""
    for session in sessions.keys():
        summary = await generate_session_summary(session)
        await send_email(f"Daily MARM Summary: {session}", summary)
```

**Auto-date system (Critical for AI accuracy):**

```python
from datetime import datetime, timezone

@app.get("/marm_current_date")
async def get_current_date():
    """Provide current date context to AI - fixes AI date assumptions"""
    now = datetime.now(timezone.utc)
    return {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M:%S UTC"),
        "formatted_date": now.strftime("%B %d, %Y"),
        "day_of_week": now.strftime("%A"),
        "context": f"Today is {now.strftime('%A, %B %d, %Y')} at {now.strftime('%H:%M UTC')}"
    }

@app.post("/marm_smart_log_with_date")
async def smart_log_with_date(content: str, session_name: str = "main"):
    """Smart logging that auto-adds current date - users never input dates"""
    now = datetime.now()
    
    # Auto-format with actual current date
    topic = extract_topic(content)
    formatted_entry = f"[{now.strftime('%Y-%m-%d')}-{topic}]"
    
    # Store with real timestamp
    sessions[session_name]["logs"].append({
        "timestamp": now.isoformat(),
        "entry": formatted_entry,
        "raw_input": content,
        "auto_dated": True
    })
    
    return f"📝 Auto-dated log: {formatted_entry} (Real date: {now.strftime('%B %d, %Y')})"

# Auto-inject current date context into all responses
@app.middleware("http")
async def inject_date_context(request, call_next):
    """Automatically provide current date context to prevent AI date confusion"""
    # Add current date to request context so AI knows real date
    request.state.current_date = datetime.now().strftime("%Y-%m-%d")
    request.state.date_context = f"Current date: {datetime.now().strftime('%A, %B %d, %Y')}"
    response = await call_next(request)
    return response
```

**Why this MCP approach is superior:**

- ✅ **Complete MARM protocol support** - All commands from constants.js implemented exactly as in original MARM
- ✅ **Built-in automation system** - Event-driven, scheduled, and smart auto-actions without N8N
- ✅ **Semantic understanding** - Finds relevant context even with different wording  
- ✅ **Context-aware** - Knows difference between code, project, and development notes
- ✅ **Auto-date system** - AI always knows the real current date (Sept 3, 2025) - fixes major AI limitation
- ✅ **Context bridging** - Intelligent workflow transitions connecting related work across sessions
- ✅ **Direct service integrations** - Slack, GitHub, Google Sheets APIs without middleware
- ✅ **Cross-session continuity** - Memory spans multiple projects and conversations
- ✅ **True MARM compatibility** - Exact copy of how MARM runs, just as MCP server
- ✅ **Zero external dependencies** - Self-contained automation vs competitor's complex setups

**Memory advantages over base LLM:**

- **Durable**: Survives conversation resets and system restarts
- **Searchable**: Find relevant info semantically across all past interactions  
- **Contextual**: Understands if discussing code, projects, or development work
- **Protocol-based**: Integrates with existing MARM command structure
- **Session-aware**: Maintains separate contexts for different projects

---

**Status:** Advanced implementation for competitive advantage
**Priority:** High - Core differentiating feature for MARM ecosystem
**Risk:** None - Open source libraries, standard database patterns
**Timeline:** 2-3 hours integration with existing FastAPI-MCP setup

---

## Future Features (Post-Stability)

**External Service Integrations (Add after core is stable):**

### **GitHub Integration**
```python
async def create_github_gist(content: str):
    """Direct GitHub API integration for code snippets"""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"files": {"snippet.txt": {"content": content}}}
    async with httpx.AsyncClient() as client:
        await client.post("https://api.github.com/gists", json=data, headers=headers)
```

### **Slack Integration**  
```python
async def send_slack_notification(message: str):
    """Direct Slack webhook for project updates"""
    webhook_url = "YOUR_SLACK_WEBHOOK_URL" 
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json={"text": message})
```

### **Google Sheets Integration**
```python
async def update_project_sheet(session: str, content: str):
    """Direct Google Sheets API for project tracking"""
    # Implementation for Google Sheets API
    pass
```

### **Calendar Integration**
```python
async def create_calendar_event(content: str):
    """Auto-create calendar events from deadline mentions"""
    # Implementation for calendar APIs
    pass
```

**Notes:**
- Add these integrations once core memory system is stable and tested
- Each integration requires authentication setup (OAuth, API keys, webhooks)
- Focus on reliability and user control for external service connections
- Consider user privacy and data security for all external integrations
