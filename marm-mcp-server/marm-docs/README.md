# MARM: The AI That Remembers Your Conversations v2.6.0</h1>

---

## Table of Contents

- [Why MARM MCP](#why-marm-mcp-the-problem--solution)
- [Quick Start](#-quick-start-for-mcp-http--stdio)
- [Connect Your Client Fast](#connect-your-client-fast)
- [Complete MCP Tool Suite](#complete-mcp-tool-suite-8-tools)
- [MARM Dashboard](#marm-dashboard)
- [Architecture Overview](#architecture-overview)

---

## Why MARM MCP: The Problem & Solution

**Your AI forgets everything. MARM MCP doesn't.**

Modern LLMs lose context over time, repeat prior ideas, and drift off requirements. MARM MCP solves this with a unified, **persistent**, MCP‑native memory layer that sits beneath any AI client you use. It blends semantic search, structured session logs, reusable notebooks, and smart summaries so your agents can remember, reference, and build on prior work—consistently, across sessions, and across tools.

### Before vs After

- Without MARM: lost context, repeated suggestions, drifting scope, "start from scratch."
- With MARM: session memory, cross-session continuity, concrete recall of decisions, and faster, more accurate delivery.

### What MARM MCP Delivers

| **Memory** | **Multi-AI** | **Architecture** |
|------------|--------------|------------------|
| **Semantic Search** - Find by meaning using AI embeddings | **Unified Memory Layer** - Works with Claude, Qwen, Gemini, MCP clients | **Lean MCP Tool Surface** - Focused tools with lifecycle automation |
| **Auto-Classification** - Content categorized (code, project, book, general) | **Cross-Platform Intelligence** - Different AIs learn from shared knowledge | **Database Optimization** - SQLite with WAL mode and connection pooling |
| **Persistent Cross-Session Memory** - Memories survive across agent conversations | **User-Controlled Memory** - "Bring Your Own History," granular control | **Rate Limiting** - IP-based tiers for stability |
| **Smart Recall** - Vector similarity search with context-aware fallbacks | | **MCP Compliance** - Response size management for predictable performance |
| | | **Docker Ready** - Containerized deployment with health/readiness checks |

---

## What Users Are Saying

> “MARM successfully handles our industrial automation workflows in production. We've validated session management, persistent logging, and smart recall across container restarts in our Windows 11 + Docker environment. The system reliably tracks complex technical decisions and maintains data integrity through deployment cycles.”  
> @Ophy21, GitHub user (Industrial Automation Engineer)

> “MARM proved exceptionally valuable for DevOps and complex Docker projects. It maintained 100% memory accuracy, preserved context on 46 services and network configurations, and enabled standards-compliant Python/Terraform work. Semantic search and automated session logs made solving async and infrastructure issues far easier. **Value Rating:** 9.5/10 - indispensable for enterprise-grade memory, technical standards, and long-session code management.”
> @joe_nyc, Discord user (DevOps/Infrastructure Engineer)  

---

## 🚀 Quick Start for MCP (HTTP & STDIO)

### Use this quick rule of thumb to choose your setup

- Local HTTP/STDIO = fastest single-machine setup.
- Docker HTTP = shared/always-on server (key required).
- Docker STDIO = private containerized local use (no HTTP key).

#### Local pip HTTP (zero config)

```bash
pip install marm-mcp-server
python -m marm_mcp_server
# most agents use this --transport command 
"agent" mcp add --transport http marm-memory http://localhost:8001/mcp
codex mcp add marm-memory --url http://localhost:8001/mcp
# xAI / Grok Remote MCP
# Use a hosted HTTPS MARM endpoint, not localhost. See Docker / hosted setup below.
```

#### Local pip STDIO

```bash
pip install marm-mcp-server
# most agents use this --transport command 
"agent" mcp add --transport stdio marm-memory-stdio marm-mcp-stdio
codex mcp add marm-memory-stdio -- marm-mcp-stdio
# xAI / Grok Remote MCP
# Use a hosted HTTPS MARM endpoint, not localhost. See Docker / hosted setup below.
python -m marm_mcp_server.server_stdio
```

---

#### Docker HTTP (key required)

```bash
# Step 1: generate key (do not add < > around the key)
docker run --rm lyellr88/marm-mcp-server:latest python -m marm_mcp_server --generate-key

# Step 2: run server
docker pull lyellr88/marm-mcp-server:latest
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  lyellr88/marm-mcp-server:latest

# Step 3: connect client
"agent" mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
```

#### Docker STDIO (no HTTP key)

```bash
docker run --rm -i \
  -v ~/.marm:/home/marm/.marm \
  lyellr88/marm-mcp-server:latest \
  python -m marm_mcp_server.server_stdio
```

**Most useful support info:**

- Docker HTTP requires a key; Docker STDIO does not.
- If you get `401`, verify key match and client restart after env var changes.
- For full key setup, rotation, and troubleshooting: [INSTALL-DOCKER.md](docs/INSTALL-DOCKER.md)

### Connect Your Client Fast

Claude Code remains the recommended first setup path, but MARM also works with other MCP clients and IDE agents.

<details>
<summary><strong>All supported clients and platforms</strong></summary>

**CLI clients** - [Claude Code](docs/INSTALL-WINDOWS.md#claude-code-recommended) · [Codex](docs/INSTALL-WINDOWS.md#codex-cli) · [Gemini CLI](docs/INSTALL-WINDOWS.md#gemini-cli) · [Qwen CLI](docs/INSTALL-WINDOWS.md#qwen-code) · [Linux variants](docs/INSTALL-LINUX.md#client-connections) · [Docker/key](docs/INSTALL-DOCKER.md#client-connections)

**IDE agents** - [VS Code / Copilot Agent](docs/INSTALL-WINDOWS.md#vs-code-mcp--github-copilot-agent) · [Cursor](docs/INSTALL-WINDOWS.md#cursor) · [Docker/key IDE setup](docs/INSTALL-DOCKER.md#vs-code-mcp--github-copilot-agent)

**Remote/API platforms** - [xAI / Grok Remote MCP](docs/INSTALL-DOCKER.md#xai--grok-remote-mcp) · [Platform integration](docs/INSTALL-PLATFORMS.md)

</details>

---

## Complete MCP Tool Suite (8 Tools)

**💡 Pro Tip:** You don't need to manually call these tools! Just tell your AI agent what you want in natural language:

- *"Claude, log this session as 'Project Alpha' and add this conversation as 'database design discussion'"*
- *"Remember this code snippet in your notebook for later"*
- *"Search for what we discussed about authentication yesterday"*

The AI agent will automatically use the appropriate tools. Manual tool access is available for power users who want direct control.

MARM now handles lifecycle work internally. Documentation loads on the first real tool call, session state initializes automatically, and documentation refreshes every 50 tool calls. Packaged docs are indexed into searchable memory with hash-based caching, so unchanged docs are skipped across restarts.

**Architecture note:** MARM uses targeted polymorphic tooling to keep MCP discovery lean without hiding behavior. Domain-specific tools such as `marm_notebook(action=...)` and `marm_delete(type=...)` group closely related operations behind explicit parameters, while recall, logging, and summaries stay separate so agents still choose the right capability clearly. This design ensures the total MCP schema footprint remains under 10KB while preserving full functionality.

| **Category** | **Tool** | **Description** |
|--------------|----------|-----------------|
| **Memory Intelligence** | `marm_smart_recall` | AI-powered semantic similarity search across all memories. Supports global search with `search_all=True` flag |
| | `marm_context_log` | Intelligent auto-classifying memory storage using vector embeddings |
| **Logging System** | `marm_log_session` | Create or switch to named session container |
| | `marm_log_entry` | Add structured log entry with auto-date formatting |
| | `marm_log_show` | Display all entries and sessions (filterable) |
| | `marm_delete` | Delete a log session, log entry, or notebook entry (`type="log"\|"notebook"`) |
| **Reasoning & Workflow** | `marm_summary` | Generate context-aware summaries with intelligent truncation for LLM conversations |
| **Notebook Management** | `marm_notebook` | Unified notebook tool: add, use, show, status, or clear entries with `action="add"\|"use"\|"show"\|"status"\|"clear"` |

**Internal automation:** lifecycle initialization, documentation refresh, current date context, and system checks are handled by the server instead of exposed as AI-facing tools. For server status, use the dashboard health panel or `curl http://localhost:8001/health`.

---

## MARM Dashboard

A local web UI for browsing and managing your MARM memory — separate from the MCP server, reads and writes the same `~/.marm/marm_memory.db`.

| What it gives you | How it works |
|-------------------|-------------|
| Browse/search/edit all memories | Direct SQLite — no MCP required |
| Manage sessions and protocol logs | Runs on port `:8002` alongside MCP on `:8001` |
| Notebook CRUD with inline editor | Same auth model (`MARM_API_KEY`) as the MCP server |
| Delete-all with count confirmation | Docker image included; WAL mode handles concurrent access |

```bash
# Quick start (pip)
cd marm-dashboard
pip install -e .
python -m marm_dashboard --open
```

```bash
# Docker (same key and volume as MCP)
docker build -t marm-dashboard:local ./marm-dashboard
docker run --rm -p 127.0.0.1:8002:8002 \
  -e MARM_API_KEY=your-key \
  -v ~/.marm:/home/marm/.marm \
  marm-dashboard:local
```

See [`marm-dashboard/README.md`](marm-dashboard/README.md) for the full guide.

---

## Architecture Overview

<details>
<summary><strong>Core Technology Stack (click to expand)</strong></summary>

```txt
FastAPI (0.115.4) + FastAPI-MCP (0.4.0)
├── SQLite with WAL Mode + Custom Connection Pooling  
├── Sentence Transformers (all-MiniLM-L6-v2) + Semantic Search
├── Structured Logging (structlog) + Memory Monitoring (psutil)
├── Auth Middleware (loopback enforcement + optional API key)
├── IP-Based Rate Limiting + Usage Analytics
├── MCP Response Size Compliance (1MB limit)
├── Event-Driven Automation System
├── Docker Containerized Deployment + Health Monitoring
└── Advanced Memory Intelligence + Auto-Classification
```

</details>

<details>
<summary><strong>Production Optimizations (click to expand)</strong></summary>

- **Custom SQLite Connection Pool**: Thread-safe with configurable limits (default: 5)
- **WAL Mode**: Write-Ahead Logging for concurrent access performance
- **Lazy Loading**: Semantic models loaded only when needed (resource efficient)
- **Intelligent Caching**: Memory usage optimization with cleanup cycles
- **Response Size Management**: MCP 1MB compliance with smart truncation

</details>

<details>
<summary><strong>Security & Configuration (click to expand)</strong></summary>

MARM defaults to **localhost-only** (`127.0.0.1`). No credentials are required for local pip use — the loopback interface is the trust boundary.

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `SERVER_HOST` | `127.0.0.1` | Bind address. Set to `0.0.0.0` to allow network/Docker access. |
| `SERVER_PORT` | `8001` | Port the server listens on. |
| `MARM_API_KEY` | *(unset)* | Bearer token required on all capability endpoints when set. |

**Pip + localhost (default):** zero config, no key, no friction.

**Pip + `SERVER_HOST=0.0.0.0`:** MARM auto-generates a key on first start, saves it to `~/.marm/.env`, and prints the client connection command once. Subsequent starts load silently.

**Docker HTTP:** always requires `MARM_API_KEY` — Docker bridge networking means requests never arrive as loopback. Generate with `docker run --rm lyellr88/marm-mcp-server:latest python -m marm_mcp_server --generate-key`, pass as `-e MARM_API_KEY=your-key`. Use HTTP for multi-agent workflows because one MARM process coordinates database access.

**Docker STDIO:** no port or API key, best for private single-agent/local use. Multiple STDIO containers can share the same mounted `~/.marm` database, but heavy concurrent writers may hit normal SQLite locking; use Docker HTTP for Hermes-style multi-agent runs.

**Resetting a Docker HTTP key:** removing an MCP client entry only removes the client config. To rotate the server key, stop the container, generate a new key, restart Docker HTTP with the new `MARM_API_KEY`, then re-add/update the client with the matching bearer token. Docker STDIO has no API key to rotate.

**Behind a reverse proxy:** bind to `127.0.0.1`, let the proxy handle TLS and auth forwarding.
</details>

<details>
<summary><strong>Competitive Advantage vs. Basic MCP Implementations (click to expand)</strong></summary>

| Feature | MARM | Basic MCP Servers |
|---------|-------------|-------------------|
| **Memory Intelligence** | AI-powered semantic search with auto-classification | Basic key-value storage |
| **Tool Coverage** | 8 focused MCP tools + lifecycle automation | 3-5 basic wrappers |  
| **Scalability** | Database optimization + connection pooling | Single connection |
| **MCP Compliance** | 1MB response size management | No size controls |
| **Deployment** | Docker containerization + health monitoring | Local development only |
| **Analytics** | Usage tracking + business intelligence | No tracking |

</details>
