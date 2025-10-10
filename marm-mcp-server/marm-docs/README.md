# MARM: The AI That Remembers Your Conversations

Memory Accurate Response Mode v2.2.6 - The intelligent memory system for AI agents with WebSocket support. Stop losing context. Stop hallucinations. Start controlling your LLM conversations.  

---

## 🎯 Why MARM?

MARM (Memory Accurate Response Mode) is a comprehensive AI memory ecosystem I designed to solve the problem of context loss in large language models. What started as a simple protocol has evolved into a suite of tools that provide a persistent, intelligent, and cross-platform memory for any AI agent.

The MARM ecosystem consists of three main components:

- **The MARM Protocol:** A set of rules and commands for structured, reliable AI interaction.
- **The MARM Universal MCP Server:** A production-ready memory intelligence platform that provides a powerful, stateful backend for any MCP-compatible AI client.
- **The MARM Chatbot:** A web-based interface for interacting with the MARM protocol directly.

Whether you're a developer looking to build the next generation of AI agents, a researcher studying AI behavior, or simply a power user who wants to have more productive conversations with your AI, the MARM ecosystem provides the tools you need to unlock the full potential of large language models.

>Appears in Google AI Overview for AI memory protocol queries (as of Aug 2025)

The newest addition tho the ecosystem is MARM MCP it represents an emerging category of MCP server that integrates a complete protocol layer with intelligent memory systems. Built on FastAPI and SQLite, it combines the MARM protocol with semantic search, session management, and smart retrieval to bridge tool access with structured reasoning. This creates a more consistent, user-controlled LLM experience that goes beyond simple tool exposure.

| **Category** | **Feature** | **Description** |
|--------------|-------------|-----------------|
| **🧠 Memory** | **Semantic Search** | Find memories by meaning using AI embeddings, not keyword matching |
| | **Auto-Classification** | Content intelligently categorized (code, project, book, general) |
| | **Cross-Session Memory** | Memories survive across different AI agent conversations |
| | **Smart Recall** | Vector similarity search with context-aware intelligent fallbacks |
| **🤝 Multi-AI** | **Unified Memory Layer** | Accessible by any connected LLM (Claude, Qwen, Gemini, etc.) |
| | **Cross-Platform Intelligence** | Different AI agents learn from each other's interactions |
| | **User-Controlled Memory** | Granular control over memory sharing and "Bring Your Own History" |
| **🏗️ Architecture** | **18 Complete MCP Tools** | Full Model Context Protocol implementation |
| | **Database Optimization** | SQLite with WAL mode and connection pooling |
| | **Rate Limiting** | IP-based protection for sustainable free service |
| | **MCP Compliance** | Response size management for optimal performance |
| | **Docker Ready** | Containerized deployment with health monitoring |
| **⚡ Advanced** | **Usage Analytics** | Privacy-conscious insights for platform optimization |
| | **Event-Driven System** | Self-managing architecture with comprehensive error isolation |
| | **Structured Logging** | Development and debugging support with `structlog` |
| | **Health Monitoring** | Real-time system status and performance tracking |

---

## Why I Built MARM  

MARM started with my own frustrations: AI losing context, repeating itself, and drifting off track. But I didn’t stop there. I asked a simple question in a few AI subreddits:  
*“What’s the one thing you wish your LLM could do better?”*  

The replies echoed the same pain points:  

- Keep memory accurate  
- Give users more control  
- Be transparent, not a black box  

That feedback confirmed the gap I already saw. I took those shared frustrations, found the middle ground, and built MARM. Early contributors validated the idea and shaped features, but the core system grew out of both personal trial and community insight.  

MARM is the result of combining individual persistence with collective needs, a protocol designed to solve what we all kept running into.  

---

## Before MARM vs After MARM

**Without MARM:**

- "Wait, what were we discussing about the database schema?"
- AI repeats previous suggestions you already rejected
- Loses track of project requirements mid-conversation
- Starts from scratch every time you return

**With MARM:**

- AI references your logged project notes and decisions
- Maintains context across multiple sessions  
- Builds on previous discussions instead of starting over
- Remembers what works and what doesn't for your project

---

## Why Use MARM?

Modern LLMs often lose context or fabricate information. MARM introduces a session memory kernel, structured logs, and a user-controlled knowledge library. Anchoring the AI to *your* logic and data. It’s more than a chatbot wrapper. It’s a methodology for accountable AI.

### Command Overview

| **Category** | **Command** | **Function** |
|--------------|-------------|--------------|
| **Session** | `/start marm` | Activate protocol |
| | `/refresh marm` | Reaffirm/reset context |
| **Core** | `/log` | Start structured session logging |
| | `/notebook` | Store key data |
| | `/summary:` | Summarize and reseed sessions |
| **Advanced** | `/deep dive` | Request context-aware response |
| | `/show reasoning` | Reveal logic trail of last answer |  

Need a walkthrough or troubleshooting help? The [`MARM-HANDBOOK.md`](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MARM-HANDBOOK.md) covers all aspects of using MARM.

---

# 🛠️ MARM MCP Server Guide

Now that you understand the ecosystem, here's info and how to actually use the MCP server with your AI agents

---

## 🛠️ Complete MCP Tool Suite (18 Tools)

**💡 Pro Tip:** You don't need to manually call these tools! Just tell your AI agent what you want in natural language:

- *"Claude, log this session as 'Project Alpha' and add this conversation as 'database design discussion'"*
- *"Remember this code snippet in your notebook for later"*
- *"Search for what we discussed about authentication yesterday"*

The AI agent will automatically use the appropriate tools. Manual tool access is available for power users who want direct control.

| **Category** | **Tool** | **Description** |
|--------------|----------|-----------------|
| **🧠 Memory Intelligence** | `marm_smart_recall` | AI-powered semantic similarity search across all memories. Supports global search with `search_all=True` flag |
| | `marm_contextual_log` | Intelligent auto-classifying memory storage using vector embeddings |
| **🚀 Session Management** | `marm_start` | Activate MARM intelligent memory and response accuracy layers |
| | `marm_refresh` | Refresh AI agent session state and reaffirm protocol adherence |
| **📚 Logging System** | `marm_log_session` | Create or switch to named session container |
| | `marm_log_entry` | Add structured log entry with auto-date formatting |
| | `marm_log_show` | Display all entries and sessions (filterable) |
| | `marm_log_delete` | Delete specified session or individual entries |
| **🔄 Reasoning & Workflow** | `marm_summary` | Generate context-aware summaries with intelligent truncation for LLM conversations |
| | `marm_context_bridge` | Smart context bridging for seamless AI agent workflow transitions |
| **📔 Notebook Management** | `marm_notebook_add` | Add new notebook entry with semantic embeddings |
| | `marm_notebook_use` | Activate entries as instructions (comma-separated) |
| | `marm_notebook_show` | Display all saved keys and summaries |
| | `marm_notebook_delete` | Delete specific notebook entry |
| | `marm_notebook_clear` | Clear the active instruction list |
| | `marm_notebook_status` | Show current active instruction list |
| **⚙️ System Utilities** | `marm_current_context` | **Background Tool** - Automatically provides current date/time for log entries (AI agents use automatically) |
| | `marm_system_info` | Comprehensive system information, health status, and loaded docs |
| | `marm_reload_docs` | Reload documentation into memory system |

---

## 🏗️ Architecture Overview

### **Core Technology Stack**

```txt
FastAPI (0.115.4) + FastAPI-MCP (0.4.0)
├── SQLite with WAL Mode + Custom Connection Pooling  
├── Sentence Transformers (all-MiniLM-L6-v2) + Semantic Search
├── Structured Logging (structlog) + Memory Monitoring (psutil)
├── IP-Based Rate Limiting + Usage Analytics
├── MCP Response Size Compliance (1MB limit)
├── Event-Driven Automation System
├── Docker Containerized Deployment + Health Monitoring
└── Advanced Memory Intelligence + Auto-Classification
```

### **Database Schema (5 Tables)**

#### `memories` - Core Memory Storage

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    session_name TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,              -- AI vector embeddings for semantic search
    timestamp TEXT NOT NULL,
    context_type TEXT DEFAULT 'general',  -- Auto-classified content type
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### `sessions` - Session Management

```sql
CREATE TABLE sessions (
    session_name TEXT PRIMARY KEY,
    marm_active BOOLEAN DEFAULT FALSE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_accessed TEXT DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT DEFAULT '{}'
);
```

#### Plus: `log_entries`, `notebook_entries`, `user_settings`

---

## 📈 Performance & Scalability

### **Production Optimizations**

- **Custom SQLite Connection Pool**: Thread-safe with configurable limits (default: 5)
- **WAL Mode**: Write-Ahead Logging for concurrent access performance
- **Lazy Loading**: Semantic models loaded only when needed (resource efficient)
- **Intelligent Caching**: Memory usage optimization with cleanup cycles
- **Response Size Management**: MCP 1MB compliance with smart truncation

### **Rate Limiting Tiers**

- **Default**: 60 requests/minute, 5min cooldown
- **Memory Heavy**: 20 requests/minute, 10min cooldown (semantic search)
- **Search Operations**: 30 requests/minute, 5min cooldown

---

## 🆚 Competitive Advantage

### **vs. Basic MCP Implementations**

| Feature | MARM v2.2.6 | Basic MCP Servers |
|---------|-------------|-------------------|
| **Memory Intelligence** | AI-powered semantic search with auto-classification | Basic key-value storage |
| **Tool Coverage** | 18 complete MCP protocol tools | 3-5 basic wrappers |  
| **Scalability** | Database optimization + connection pooling | Single connection |
| **MCP Compliance** | 1MB response size management | No size controls |
| **Deployment** | Docker containerization + health monitoring | Local development only |
| **Analytics** | Usage tracking + business intelligence | No tracking |
| **Codebase Maturity** | 2,500+ lines professional code | 200-800 lines |
