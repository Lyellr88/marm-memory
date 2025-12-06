<div align="center">
<picture>
<img src="https://raw.githubusercontent.com/Lyellr88/MARM-Systems/MARM-main/media/marm-logo.svg"
     alt="MARM - The AI That Remembers Your Conversations"
     width="700"
     height="350">
</picture>
<h1 align="center">MARM: The AI That Remembers Your Conversations</h1>

Memory Accurate Response Mode v2.2.6 - The intelligent persistent memory system for AI agents, stop fighting your memory and control it. Experience long-term recall, session continuity, and reliable conversation history, so your LLMs never lose track of what matters.

[![GitHub stars](https://img.shields.io/github/stars/Lyellr88/MARM-Systems?style=flat&color=blue)](https://github.com/Lyellr88/MARM-Systems/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Lyellr88/MARM-Systems?style=flat&color=blue)](https://github.com/Lyellr88/MARM-Systems/network)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.4-blue)](https://fastapi.tiangolo.com/)
[![Docker Pulls](https://img.shields.io/docker/pulls/lyellr88/marm-mcp-server)](https://hub.docker.com/r/lyellr88/marm-mcp-server)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/marm-mcp-server?period=total&units=NONE&left_color=GREY&right_color=BLUE&left_text=downloads)](https://pepy.tech/projects/marm-mcp-server)

[![pip install](https://img.shields.io/badge/pip%20install-marm--mcp--server-blue)](https://pypi.org/project/marm-mcp-server/)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-LIVE-blue)](https://registry.modelcontextprotocol.io/)

[![Official MARM](https://img.shields.io/badge/Official-MARM-blue?style=for-the-badge)](https://github.com/Lyellr88/MARM-Systems)

**Note:** This is the *official* MARM repository. All official versions and releases are managed here.

Forks may experiment, but official updates will always come from this repo.  

</div>

---

## MARM Demo Video: Docker Install + Seeing Persistent AI Memory in Action  

<https://github.com/user-attachments/assets/c7c6a162-5408-4eda-a461-610b7e713dfe>

This demo video walks through a Docker pull of MARM MCP and connecting it to Claude using the claude add mcp transport command and then shows multiple AI agents (Claude, Gemini, Qwen) instantly sharing logs and notebook entries via MARM’s persistent, universal memory proving seamless cross-agent recall and “absolute truth” notebooks in action.

---

## Why MARM MCP: The Problem & Solution

**Your AI forgets everything. MARM MCP doesn't.**

Modern LLMs lose context over time, repeat prior ideas, and drift off requirements. MARM MCP solves this with a unified, **persistent**, MCP‑native memory layer that sits beneath any AI client you use. It blends semantic search, structured session logs, reusable notebooks, and smart summaries so your agents can remember, reference, and build on prior work—consistently, across sessions, and across tools.

> MCP in One Sentence:
> MARM MCP provides persistent memory and structured session context beneath any AI tool, so your agents learn, remember, and collaborate across all your workflows.

### The Problem → The MARM Solution

- Problem: Conversations reset; decisions get lost; work scatters across multiple AI tools.
- Solution: A universal, persistent memory layer that captures and classifies the important bits (decisions, configs, code, rationale), then recalls them by meaning—not keywords.

### Before vs After

- Without MARM: lost context, repeated suggestions, drifting scope, "start from scratch."
- With MARM: session memory, cross-session continuity, concrete recall of decisions, and faster, more accurate delivery.

<br>
<div align="center">
<picture>
  <img src="https://raw.githubusercontent.com/Lyellr88/MARM-Systems/MARM-main/media/google-overview.png"
       alt="MARM appears in Google AI Overview for AI memory protocol queries"
       width="900"
       height="550"
  />
</picture>
</div>
<p align="center"><i>Appears in Google AI Overview for AI memory protocol queries (as of Aug 2025)</i></p>

### What MARM MCP Delivers

| **Memory** | **Multi-AI** | **Architecture** |
|------------|--------------|------------------|
| **Semantic Search** - Find by meaning using AI embeddings | **Unified Memory Layer** - Works with Claude, Qwen, Gemini, MCP clients | **18 Complete MCP Tools** - Full Model Context Protocol coverage |
| **Auto-Classification** - Content categorized (code, project, book, general) | **Cross-Platform Intelligence** - Different AIs learn from shared knowledge | **Database Optimization** - SQLite with WAL mode and connection pooling |
| **Persistent Cross-Session Memory** - Memories survive across agent conversations | **User-Controlled Memory** - "Bring Your Own History," granular control | **Rate Limiting** - IP-based tiers for stability |
| **Smart Recall** - Vector similarity search with context-aware fallbacks | | **MCP Compliance** - Response size management for predictable performance |
| | | **Docker Ready** - Containerized deployment with health/readiness checks |

### Learn More

- Protocol walkthrough, commands, and reseeding patterns: [`MARM-HANDBOOK.md`](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MARM-HANDBOOK.md)
- Join the community for updates and support: [MARM Discord](https://discord.gg/nhyJWPz2cf)

---

## What Users Are Saying

> “MARM successfully handles our industrial automation workflows in production. We've validated session management, persistent logging, and smart recall across container restarts in our Windows 11 + Docker environment. The system reliably tracks complex technical decisions and maintains data integrity through deployment cycles.”  
> @Ophy21, GitHub user (Industrial Automation Engineer)

> “MARM proved exceptionally valuable for DevOps and complex Docker projects. It maintained 100% memory accuracy, preserved context on 46 services and network configurations, and enabled standards-compliant Python/Terraform work. Semantic search and automated session logs made solving async and infrastructure issues far easier. **Value Rating:** 9.5/10 - indispensable for enterprise-grade memory, technical standards, and long-session code management.”
> @joe_nyc, Discord user (DevOps/Infrastructure Engineer)  

---

## 🚀 Quick Start for MCP

<br>
<div align="center">
<picture>
<img src="https://raw.githubusercontent.com/Lyellr88/MARM-Systems/MARM-main/media/installation-flow.svg"
   width="850"
   height="500"
</picture>
</div>
<br>

**Docker (Fastest - 30 seconds):**

```bash
docker pull lyellr88/marm-mcp-server:latest
docker run -d --name marm-mcp-server -p 8001:8001 -v ~/.marm:/home/marm/.marm lyellr88/marm-mcp-server:latest
claude mcp add --transport http marm-memory http://localhost:8001/mcp
```

**Quick Local Install:**

```bash
pip install marm-mcp-server==2.2.6
marm-mcp-server
claude mcp add --transport http marm-memory http://localhost:8001/mcp
```

**STDIO Transport (Alternative):**

For MCP clients that require STDIO transport (orchestration platforms, CLI tools):

```bash
# Install STDIO dependencies
pip install -r marm-mcp-server/requirements_stdio.txt

# Run STDIO server
python3 marm-mcp-server/server_stdio.py run
```

Configure in your MCP client with STDIO transport:
```json
{
  "mcpServers": {
    "marm-memory": {
      "command": "python3",
      "args": ["path/to/marm-mcp-server/server_stdio.py", "run"]
    }
  }
}
```

**Transport Comparison:**

| Feature | HTTP/WebSocket | STDIO |
|---------|---------------|-------|
| **Deployment** | Requires HTTP server | Process-based |
| **Resource Isolation** | Shared server | Per-process |
| **Platform Support** | Web-based clients | CLI/orchestration tools |
| **Setup Complexity** | Medium (port management) | Low (direct execution) |
| **Use Case** | Web apps, remote access | Local tools, automation |

**Key Information:**

- **Server Endpoint**: `http://localhost:8001/mcp`
- **API Documentation**: `http://localhost:8001/docs`
- **Supported Clients**: Claude Code, Qwen CLI, Gemini CLI, and any MCP-compatible LLM client or LLM platform

**All Installation Options:**

- **Docker** (Fastest): One command, works everywhere
- **Automated Setup**: One command with dependency validation  
- **Manual Installation**: Step-by-step with virtual environment
- **Quick Test**: Zero-configuration trial run

**Choose your installation method:**

| Installation Type | Guide | Best For |
|-------------------|-------|----------|
| **Docker** | **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)** | Cross-platform, production deployment |
| **Windows** | **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)** | Native Windows development |
| **Linux** | **[INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)** | Native Linux development |
| **Platforms** | **[INSTALL-PLATFORM.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORM.md)** | App & API integration |

---

# 🛠️ MARM MCP Server Guide

Now that you understand the ecosystem, here's info and how to use the MCP server with your AI agents

---

<div align="center">
<picture>
<img src="https://raw.githubusercontent.com/Lyellr88/MARM-Systems/MARM-main/media/feature-showcase.svg"
   height="550"
   width="800"
</picture>
</div>

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

<div align="center">
<picture>
<img src="https://raw.githubusercontent.com/Lyellr88/MARM-Systems/MARM-main/media/memory-intelligence.svg"
   width="900"
   height="625"
</picture>
</div>

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

## 📚 Documentation for MCP

| Guide Type | Document | Description |
|------------|----------|-------------|
| **Docker Setup** | **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)** | Cross-platform, production deployment |
| **Windows Setup** | **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)** | Native Windows development |
| **Linux Setup** | **[INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)** | Native Linux development |
| **Platform Integration** | **[INSTALL-PLATFORM.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORM.md)** | App & API integration |
| **MCP Handbook** | **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)** | Complete usage guide with all 18 MCP tools, cross-app memory strategies, pro tips, and FAQ |

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

---

## 🤝 Contributing

**Aren't you sick of explaining every project you're working on to every LLM you work with?**

MARM is building the solution to this. Support now to join a growing ecosystem - this is just **Phase 1 of a 3-part roadmap** and our next build will complement MARM like peanut butter and jelly.

**Join the repo that's working to give YOU control over what is remembered and how it's remembered.**

### **Why Contribute Now?**

- **Ground floor opportunity** - Be part of the MCP memory revolution from the beginning
- **Real impact** - Your contributions directly solve problems you face daily with AI agents
- **Growing ecosystem** - Help build the infrastructure that will power tomorrow's AI workflows
- **Phase 1 complete** - Proven foundation ready for the next breakthrough features

### **Development Priorities**

1. **Load Testing**: Validate deployment performance under real AI workloads
2. **Documentation**: Expand API documentation and LLM integration guides
3. **Performance**: AI model caching and memory optimization
4. **Features**: Additional MCP protocol tools and multi-tenant capabilities

---

## Join the MARM Community

**Help build the future of AI memory - no coding required!**

**Connect:** [MARM Discord](https://discord.gg/nhyJWPz2cf) | [GitHub Discussions](https://github.com/Lyellr88/MARM-Systems/discussions)

### Easy Ways to Get Involved

- **Try the MCP server or Coming soon CLI** and share your experience
- **Star the repo** if MARM solves a problem for you
- **Share on social** - help others discover memory-enhanced AI
- **Open [issues](https://github.com/Lyellr88/MARM-Systems/issues)** with bugs, feature requests, or use cases
- **Join discussions** about AI reliability and memory

### For Developers

- **Build integrations** - MCP tools, browser extensions, API wrappers
- **Enhance the memory system** - improve semantic search and storage
- **Expand platform support** - new deployment targets and integrations
- **Submit [Pull Requests](https://github.com/Lyellr88/MARM-Systems/pulls)** - Every PR helps MARM grow. Big or small, I review each with respect and openness to see how it can improve the project

### ⭐ Star the Project

If MARM helps with your AI memory needs, please star the repository to support development!

---

<div align="center">

  [![Star History Chart](https://api.star-history.com/svg?repos=Lyellr88/MARM-Systems&type=Date)](https://star-history.com/#Lyellr88/MARM-Systems&Date)
</div>

---

### License & Usage Notice

This project is licensed under the MIT License. Forks and derivative works are permitted.  

However, use of the **MARM name** and **version numbering** is reserved for releases from the [official MARM repository](https://github.com/Lyellr88/MARM-Systems).

Derivatives should clearly indicate they are unofficial or experimental.

---

## 📁 Project Documentation

### **Usage Guides**

- **[MARM-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MARM-HANDBOOK.md)** - Original MARM protocol handbook for chatbot usage
- **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)** - Complete MCP server usage guide with commands, workflows, and examples
- **[PROTOCOL.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/PROTOCOL.md)** - Quick start commands and protocol reference
- **[FAQ.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/FAQ.md)** - Answers to common questions about using MARM

### **MCP Server Installation**

- **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)** - Docker deployment (recommended)
- **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)** - Windows installation guide
- **[INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)** - Linux installation guide
- **[INSTALL-PLATFORMS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORMS.md)** - Platform installation guide

### **Chatbot Installation**

- **[CHATBOT-SETUP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHATBOT-SETUP.md)** - Web chatbot setup guide

### **Project Information**

- **[README.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/README.md)** - This file - ecosystem overview and MCP server guide
- **[CONTRIBUTING.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CONTRIBUTING.md)** - How to contribute to MARM
- **[DESCRIPTION.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/DESCRIPTION.md)** - Protocol purpose and vision overview
- **[CHANGELOG.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHANGELOG.md)** - Version history and updates
- **[ROADMAP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ROADMAP.md)** - Planned features and development roadmap
- **[LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/LICENSE)** - MIT license terms

---

mcp-name: io.github.Lyellr88/marm-mcp-server

>Built with ❤️ by MARM Systems - Universal MCP memory intelligence
