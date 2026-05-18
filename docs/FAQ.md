
# MARM Systems FAQ

## Table of Contents

- [Base Questions - General MARM](#-base-questions---general-marm)
- [MCP Server Questions](#-mcp-server-questions)  

---

## 🎯 Base Questions - General MARM

### Q: What is MARM Systems?

MARM Systems provides **Universal Memory Intelligence** for AI agents through three main offerings:

| Product | Description | Best For |
|---------|-------------|----------|
| **MCP Server** | Production-ready universal memory server with 18 tools | Claude, Gemini, Qwen, and any MCP-compatible AI |
| **Original Protocol** | Copy/paste instructions for manual memory management | Any AI platform (ChatGPT, Claude, local models) |
| **Live Chatbot Demo** | Interactive testing environment | Quick testing and feature exploration |

### Q: How is MARM different from built-in AI memory?

| Feature | Built-in AI Memory | MARM Systems |
|---------|-------------------|--------------|
| **Control** | Limited, opaque, no user control | Full user control over what gets remembered |
| **Portability** | Platform-locked (ChatGPT only works in ChatGPT) | Cross-platform (memory works everywhere) |
| **Validation** | No accuracy guarantees | Built-in validation and reasoning transparency |
| **Search** | Basic recency-based | Semantic similarity search by meaning |
| **Sharing** | Can't export or transfer | Memory database shared across all AI agents |

### Q: Who is MARM for?

**Perfect for:**

- **Developers** - Long coding projects requiring context continuity
- **Researchers** - Complex analysis with memory accuracy needs
- **Enterprise teams** - Shared AI memory across different platforms
- **Power users** - Anyone doing serious work with multiple AI agents

**Not ideal for:**

- Quick, one-off questions  
- Users wanting fully automated solutions

## 🚀 MCP Server Questions

### Q: How do I install the MARM MCP Server?

| Method | Commands | Time | Requirements |
|--------|----------|------|--------------|
| **Docker (Recommended)** | `docker run --rm lyellr88/marm-mcp-server:latest python -m marm_mcp_server --generate-key`<br>`docker run -d --name marm-mcp-server -p 127.0.0.1:8001:8001 -e SERVER_HOST=0.0.0.0 -e MARM_API_KEY=your-generated-key -v ~/.marm:/home/marm/.marm lyellr88/marm-mcp-server:latest`<br>`claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"` | 2 minutes | Docker installed |
| **PyPI Install** | `pip install marm-mcp-server==2.5.1`<br>`python -m marm_mcp_server` | 1 minute | Python 3.10+ |

### Q: What MCP tools does MARM provide?

**18 Complete MCP Tools organized by category:**

| Category | Tools | Description |
|----------|-------|-------------|
| **Memory Intelligence** | `marm_smart_recall`, `marm_contextual_log` | AI-powered semantic search and intelligent storage |
| **Session Management** | `marm_start`, `marm_refresh` | Memory activation and session state management |
| **Logging System** | `marm_log_session`, `marm_log_entry`, `marm_log_show`, `marm_log_delete` | Structured conversation history |
| **Notebook Management** | `marm_notebook_add`, `marm_notebook_use`, `marm_notebook_show`, etc. | Reusable instructions and knowledge storage |
| **Workflow Tools** | `marm_summary`, `marm_context_bridge` | Context summaries and workflow transitions |
| **System Utilities** | `marm_current_context`, `marm_system_info`, `marm_reload_docs` | System status and information |

### Q: Which AI platforms work with the MCP server?

**Currently Supported:**

- ✅ **Claude Code** - Full integration with CLI command
- ✅ **Qwen CLI** - Complete MCP tool access  
- ✅ **Gemini CLI** - All 18 tools available
- ✅ **Any MCP-compatible client** - Universal protocol support

**Coming Soon:**

- ChatGPT (when OpenAI adds MCP support)
- Additional enterprise AI platforms

### Q: How does semantic search work?

**Traditional keyword search:** "authentication error" only finds exact matches

**MARM semantic search:** "authentication error" finds related memories about "login problems", "user verification issues", "access denied", etc.

**Technical details:**

- Uses AI embeddings (`all-MiniLM-L6-v2` model)
- Vector similarity search finds content by meaning
- Global search across all sessions with `search_all=True`
- Intelligent auto-classification (code, project, book, general)

### Q: Can multiple AI agents share the same memory?

**Yes! This is MARM's key feature:**

- **One database** shared across all connected AI clients
- **Cross-platform intelligence** - Claude learns from Gemini's conversations
- **Collaborative workflows** - Different AIs contribute to same knowledge base
- **Session isolation** available when needed
- **User-controlled** sharing and memory management

---

## 📁 Project Documentation

### **Usage Guides**

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