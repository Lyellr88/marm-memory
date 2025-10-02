<div align="center">
<picture>
  <img src="https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/media/marm-main.jpg"
       alt="MARM - The AI That Remembers Your Conversations"
       width="700"
       height="350"
</picture>
<h1 align="center">MARM: The AI That Remembers Your Conversations</h1>

Memory Accurate Response Mode v2.2.5 - The intelligent memory system for AI agents with WebSocket support. Stop losing context. Stop hallucinations. Start controlling your LLM conversations.  

[![GitHub stars](https://img.shields.io/github/stars/Lyellr88/MARM-Systems?style=flat&color=blue)](https://github.com/Lyellr88/MARM-Systems/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Lyellr88/MARM-Systems?style=flat&color=blue)](https://github.com/Lyellr88/MARM-Systems/network)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.4-blue)](https://fastapi.tiangolo.com/)
[![Docker Pulls](https://img.shields.io/docker/pulls/lyellr88/marm-mcp-server)](https://hub.docker.com/r/lyellr88/marm-mcp-server)
[![Pip Downloads](https://pepy.tech/badge/marm-mcp-server)](https://pepy.tech/project/marm-mcp-server)

[![pip install](https://img.shields.io/badge/pip%20install-marm--mcp--server-blue)](https://pypi.org/project/marm-mcp-server/)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-LIVE-blue)](https://registry.modelcontextprotocol.io/)

[![Official MARM](https://img.shields.io/badge/Official-MARM-blue?style=for-the-badge)](https://github.com/Lyellr88/MARM-Systems)

**Note:** This is the *official* MARM repository. All official versions and releases are managed here.

Forks may experiment, but official updates will always come from this repo.  

</div>

---

## 🚀 Quick Start for MCP

<br>
<div align="center">
<picture>
    <img src="https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/media/installation-flow.svg"
         width="850"
         height="500"
</picture>
</div>
<br>

**Docker (Fastest - 30 seconds):**

```bash
docker pull lyellr88/marm-mcp-server:latest
docker run -d --name marm-mcp-server -p 8001:8001 -v marm_data:/app/data lyellr88/marm-mcp-server:latest
claude mcp add marm-memory http://localhost:8001/mcp
```

**Quick Local Install:**

```bash
pip install marm-mcp-server==2.2.5
marm-mcp-server
claude mcp add marm-memory http://localhost:8001/mcp
```

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

## 🚀 Quick Start for Chatbot

The MARM Chatbot is a web-based interface for interacting with the MARM protocol. To install it, you'll need Node.js and a Replicate API key.

### 1. Clone the repository

```bash
git clone https://github.com/Lyellr88/MARM-Systems.git
```

### 2. Install dependencies

```bash
cd MARM-Systems/webchat
npm install
```

### 3. Add your Replicate API key to a .env file

```bash
echo "REPLICATE_API_TOKEN=your_replicate_api_token_here" > .env
```

### 4. Start the server

```bash
npm start
```

**Fastest**
[MARM Chatbot](https://marm-systems-chatbot.onrender.com)

---

## 🎯 Why MARM?

MARM (Memory Accurate Response Mode) is a comprehensive AI memory ecosystem I designed to solve the problem of context loss in large language models. What started as a simple protocol has evolved into a suite of tools that provide a persistent, intelligent, and cross-platform memory for any AI agent.

The MARM ecosystem consists of three main components:

- **The MARM Protocol:** A set of rules and commands for structured, reliable AI interaction.
- **The MARM Universal MCP Server:** A production-ready memory intelligence platform that provides a powerful, stateful backend for any MCP-compatible AI client.
- **The MARM Chatbot:** A web-based interface for interacting with the MARM protocol directly.

Whether you're a developer looking to build the next generation of AI agents, a researcher studying AI behavior, or simply a power user who wants to have more productive conversations with your AI, the MARM ecosystem provides the tools you need to unlock the full potential of large language models.

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

### Discord

Join Discord for upcoming features and builds, plus a safe space to share your work and get constructive feedback.

[MARM Discord](https://discord.gg/EuBsHvSRks)

<div align="center">
<picture>
    <img src="https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/media/google-overview.PNG"
         alt="MARM - The AI That Remembers Your Conversations"
         width="700"
         height="350"
</picture>
</div>
<p align="center">*Appears in Google AI Overview for AI memory protocol queries (as of Aug 2025)*

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

<div align="center">
  <h3>🚀 Try MARM Chatbot Now - No Setup Required</h3>
  <a href="https://marm-systems-chatbot.onrender.com">
    <img src="https://img.shields.io/badge/Launch_Live_Demo-MARM_Chatbot-FF6B6B?style=for-the-badge&logo=rocket&logoColor=white" width="300">
  </a>
  <p><i>Experience all features instantly in your browser</i></p>
</div>

<div align="center">
<picture>
  <img src="https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/media/chatbot-dark.png"
       width="700"
       height="350">
</picture>
</div>

### Need detailed steps, troubleshooting, or multi-provider setup?

See [CHATBOT-SETUP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHATBOT-SETUP.md) for complete installation guide with Node.js setup and troubleshooting.

# 🛠️ MARM MCP Server Guide

Now that you understand the ecosystem, here's info and how to actually use the MCP server with your AI agents

---

<div align="center">
<picture>
    <img src="https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/media/feature-showcase.svg"
      height="550"   
      width="800"
         
</picture>
</div>

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

| Feature | MARM v2.2.5 | Basic MCP Servers |
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

**Connect:** [MARM Discord](https://discord.gg/EuBsHvSRks) | [GitHub Discussions](https://github.com/Lyellr88/MARM-Systems/discussions)

### Easy Ways to Get Involved

- **Try the MCP server or Chatbot** and share your experience
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
- **[INSTALL-PLATFORMS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORMS.md)** - Platfrom installtion guide

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
