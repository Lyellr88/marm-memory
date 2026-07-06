# MARM: Local-First Persistent Multi-Agent Memory Layer for MCP Clients v2.17.0

## Table of Contents

- [Why MARM MCP](#why-marm-mcp-the-problem--solution)
- [Quick Start](#-quick-start-for-mcp-http--stdio)
- [Code Graph](#code-graph-repo-indexing-and-code-lookup)
- [Complete MCP Tool Suite](#complete-mcp-tool-suite-12-tools)
- [MARM Dashboard](#marm-dashboard)
- [Performance & Scaling Benchmarks](#performance--scaling-benchmarks)
- [Contributing](#contributing)
- [Project Documentation](#project-documentation)

## Why MARM MCP: The Problem & Solution

**Your AI forgets everything. MARM MCP doesn't.**

MARM MCP is a local memory infrastructure layer for AI agents. It gives Claude, Codex, Gemini, Qwen, IDE agents, and other MCP clients one persistent place to store decisions, retrieve context, reuse notebooks, and keep long-running work from drifting.

MARM is built around two focused surfaces: **7 core memory tools** for daily agent context and **5 HTTP code-graph tools** for repo intelligence. The server handles the heavy work behind those tools: protocol delivery, hybrid recall, serialized writes, rate-limit presets, write-time consolidation, agent-assisted compaction, and lazy graph startup. Agents get a compact memory workflow plus codebase lookup when they need it, without rereading the whole project or flooding the model with duplicate context.

### How It Works

| Layer | What it does | Why it matters |
|-------|--------------|----------------|
| **Memory model** | Sessions, structured logs, notebooks, summaries, and semantic memories | Keeps project history searchable instead of trapped in one chat |
| **Scale layer** | SQLite WAL mode, connection pooling, serialized write queue, and HTTP rate-limit presets | Lets one server support solo use, multi-agent work, and swarm-style bursts |
| **Intelligence layer** | FTS filter, semantic re-rank, bounded semantic fallback, auto-classification, write-time consolidation, and compaction candidates | Keeps recall useful as memory grows instead of letting duplicates pile up |
| **Code graph layer** | Repo indexing, symbol lookup, call tracing, architecture overview, and change-impact analysis | Gives agents project structure without rereading the whole codebase |
| **Token layer** | Lightweight 7-tool core surface (12 over HTTP with bundled graph tools), semantic re-rank before retrieval, and write-time deduplication | Reduces tokens sent to the model on every recall and cost stays predictable as memory scales |
| **Deployment layer** | Pip, Docker, STDIO, HTTP, `--swarm`, `--swarm-max`, and `--trusted` | Lets you run private local memory or shared multi-agent memory with the same MCP surface |

See [Performance & Scaling Benchmarks](#performance--scaling-benchmarks) for retrieval latency, concurrency, and write-cost numbers.

### Start Now

**Recommended: guided setup with `marm-init`**

The easiest way to install MARM is to let your agent do the setup with you. `marm-init` turns the usual MCP setup mess into one guided conversation: Python or Docker, HTTP or STDIO, local or remote server, API keys, config paths, dashboard startup, and multi-agent linking for Claude, Codex, Gemini, Qwen, Cursor, VS Code, and other MCP clients. No hunting through install docs, no guessing which config file your client uses, and no rewriting the same connection by hand for every agent.

```bash
npx degit Lyellr88/MARM-Systems/skills
```

Then tell your agent: **"Use the marm-init skill to set up MARM."**

**Manual pip install**

```bash
pip install marm-mcp-server
```

| If you are... | Start the server | Connect your MCP client |
|---------------|------------------|-------------------------|
| **Solo developer / researcher** | `python -m marm_mcp_server` | `"agent" mcp add --transport http marm-memory http://localhost:8001/mcp` |
| **Private local STDIO user** | `marm-mcp-stdio` | `"agent" mcp add --transport stdio marm-memory-stdio marm-mcp-stdio` |
| **Multiple agents sharing memory** | `python -m marm_mcp_server --swarm` | `"agent" mcp add --transport http marm-memory http://localhost:8001/mcp` |
| **Private high-throughput swarm** | `python -m marm_mcp_server --swarm-max` | `"agent" mcp add --transport http marm-memory http://localhost:8001/mcp` |
| **Trusted private lab/server** | `python -m marm_mcp_server --trusted` | `"agent" mcp add --transport http marm-memory http://localhost:8001/mcp` |

### Code Graph: repo indexing and code lookup

`marm-graph` is bundled into the HTTP server. It indexes a repository once, then lets agents ask code-structure questions without repeatedly scanning files. The graph backend starts lazily on first graph-tool use, so normal memory, logging, notebook, and summary tools still start fast.

Use HTTP mode, then ask your agent to index the repo:

```text
Use marm_graph_index to index this repository.
Then use marm_code_lookup when you need symbols, files, or source snippets.
Use marm_graph_trace for call paths, marm_graph_architecture for an overview, and marm_graph_impact for change-risk checks.
```

Graph tools are currently part of the HTTP MCP surface. STDIO remains focused on the 7 core memory tools for private local use.

## 🚀 Quick Start for MCP (HTTP & STDIO)

### Use this quick rule of thumb to choose your setup

- Local HTTP/STDIO = fastest single-machine setup.
- Docker HTTP = shared/always-on server (key required).
- Docker STDIO = private containerized local use (no HTTP key).

**Swarm / multi-agent note:** The write queue is enabled by default to serialize memory writes through one worker. For shared HTTP deployments, use `--swarm` (200 RPM) or `--swarm-max` (600 RPM) when starting the server. `--trusted` disables rate limiting entirely for private deployments. STDIO is still best for private single-agent/local use. See [MCP-HANDBOOK.md](MCP-HANDBOOK.md) for more info.

<details>
<summary><strong>Local pip HTTP (zero config)</strong></summary>

> "agent" refers to claude, gemini, grok, qwen, or any MCP client. Codex uses --url instead of --transport to add MCP tools.

```bash
pip install marm-mcp-server
python -m marm_mcp_server
# Stuck on client setup? Open a Q&A thread: https://github.com/Lyellr88/MARM-Systems/discussions
# most agents use this --transport command
"agent" mcp add --transport http marm-memory http://localhost:8001/mcp
codex mcp add marm-memory --url http://localhost:8001/mcp

</details>

<details>
<summary><strong>Local pip STDIO</strong></summary>

#### Local pip STDIO

```bash
pip install marm-mcp-server
python -m marm_mcp_server.server_stdio
# most agents use this --transport command
"agent" mcp add --transport stdio marm-memory-stdio marm-mcp-stdio
codex mcp add marm-memory-stdio -- marm-mcp-stdio
```

</details>

<details>
<summary><strong>Local Python swarm modes (HTTP & STDIO)</strong></summary>

Use HTTP when multiple agents need to share one live MARM server. STDIO is still best for private single-agent use because each client owns its own local process.

```bash
# HTTP shared server, normal multi-agent use
python -m marm_mcp_server --swarm

# HTTP shared server, heavier private swarm
python -m marm_mcp_server --swarm-max

# HTTP trusted private lab/server, rate limiting disabled
python -m marm_mcp_server --trusted

# STDIO remains keyless/private and does not use swarm flags
marm-mcp-stdio
```

</details>

---

<details>
<summary><strong>Docker HTTP (key required)</strong></summary>

> Docker HTTP requires an API key because it exposes MARM as a network server; STDIO stays local to the client process and does not need one.

```bash
# Step 1: generate key (do not add < > around the key)
docker run --rm lyellr88/marm-mcp-server:latest --generate-key

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

</details>

<details>
<summary><strong>Docker HTTP swarm mode</strong></summary>

```bash
# --swarm: write queue on, 200 RPM - recommended for multi-agent shared servers
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  lyellr88/marm-mcp-server:latest --swarm
```

</details>

<details>
<summary><strong>Docker STDIO (no HTTP key)</strong></summary>

```bash
docker run --rm -i \
  -v ~/.marm:/home/marm/.marm \
  --entrypoint python \
  lyellr88/marm-mcp-server:latest \
  -m marm_mcp_server.server_stdio
```

</details>

---

<details>
<summary><strong>Support notes</strong></summary>

- Docker HTTP requires a key; Docker STDIO does not.
- If you get `401`, verify key match and client restart after env var changes.
- For full key setup, rotation, and troubleshooting: [INSTALL-DOCKER.md](docs/INSTALL-DOCKER.md)

</details>

<details>
<summary><strong>Connect your client fast</strong></summary>

Claude Code remains the recommended first setup path, but MARM also works with other MCP clients and IDE agents.

**CLI clients** - [Claude Code](docs/INSTALL-WINDOWS.md#claude-code-recommended) · [Codex](docs/INSTALL-WINDOWS.md#codex-cli) · [Gemini CLI](docs/INSTALL-WINDOWS.md#gemini-cli) · [Qwen CLI](docs/INSTALL-WINDOWS.md#qwen-code) · [Linux variants](docs/INSTALL-LINUX.md#client-connections) · [Docker/key](docs/INSTALL-DOCKER.md#client-connections)

**IDE agents** - [VS Code / Copilot Agent](docs/INSTALL-WINDOWS.md#vs-code-mcp--github-copilot-agent) · [Cursor](docs/INSTALL-WINDOWS.md#cursor) · [Docker/key IDE setup](docs/INSTALL-DOCKER.md#vs-code-mcp--github-copilot-agent)

**Remote/API platforms** - [xAI / Grok Remote MCP](docs/INSTALL-DOCKER.md#xai--grok-remote-mcp) · [Platform integration](docs/INSTALL-PLATFORMS.md)

> Using a client that isn't listed? [Open an issue](https://github.com/Lyellr88/MARM-Systems/issues/new/choose) and let us know; client adapters are a first-class feature request.

</details>

## MARM Dashboard

A local web UI for browsing and managing your MARM memory. It is bundled with `marm-mcp-server` and mounts at `/dashboard` when the HTTP server starts.

| What it gives you | How it works |
|-------------------|-------------|
| Browse/search/edit all memories | Direct SQLite access to the same `~/.marm/marm_memory.db` |
| Manage sessions and protocol logs | Open `http://localhost:8001/dashboard` beside the MCP endpoint on `:8001` |
| Notebook CRUD with inline editor | Same `MARM_API_KEY` auth model as the MCP server |
| Delete-all with count confirmation | Included in the unified pip package and Docker image |
| View the write queue in real time | Pulls live data from the write queue |

Start MARM HTTP, then open the dashboard:

```bash
python -m marm_mcp_server
# browser: http://localhost:8001/dashboard
```

Docker uses the same unified image and key:

```bash
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e MARM_API_KEY=your-key \
  -v ~/.marm:/home/marm/.marm \
  lyellr88/marm-mcp-server:latest
# browser: http://localhost:8001/dashboard
```

## Complete MCP Tool Suite (12 Tools)

**💡 Pro Tip:** You don't need to manually call these tools! Just tell your AI agent what you want in natural language:

- *"Claude, log this session as 'Project Alpha' and add this conversation as 'database design discussion'"*
- *"Remember this code snippet in your notebook for later"*
- *"Search for what we discussed about authentication yesterday"*

The AI agent will automatically use the appropriate tools. Manual tool access is available for power users who want direct control.

| **Category** | **Tool** | **Description** |
|--------------|----------|-----------------|
| **Memory Intelligence** | `marm_smart_recall` | Hybrid recall with automatic exact-query detection for config keys, commands, API names, and file paths; semantic reranking; bounded fallback search; and chunk-aware scoring for long memories. Supports `search_all=True`, `project`/`platform` filters, `exact_mode="auto"\|"exact"\|"semantic"`, and `detail=1/2/3` depth controls |
| **Logging System** | `marm_log_entry` | Add structured session log entries. Session/topic routing, summary-cache invalidation, and context summary preparation are handled by the server |
| | `marm_log_show` | Display all entries and sessions (filterable) |
| | `marm_delete` | Delete a log session, log entry, or notebook entry (`type="log"\|"notebook"`) |
| **Reasoning & Workflow** | `marm_summary` | Generate cached session summaries with intelligent truncation for LLM conversations |
| **Notebook Management** | `marm_notebook` | Unified notebook tool: add, use, show, status, or clear entries with `action="add"\|"use"\|"show"\|"status"\|"clear"` |
| **Memory Maintenance** | `marm_compaction` | Unified compaction workflow with `action="status"\|"candidates"\|"review"\|"stage"\|"apply"\|"discard"` for agent-assisted memory cleanup |
| **Code Graph (bundled, HTTP only)** | `marm_graph_index` | Index a repo into the code-structure graph, or check status / list indexed projects |
| | `marm_code_lookup` | Find symbols, text patterns, or a symbol's source — use instead of grep/glob |
| | `marm_graph_trace` | Trace call paths / data flow through the graph from a function |
| | `marm_graph_architecture` | High-level architecture overview: node/edge breakdown, modules, and schema |
| | `marm_graph_impact` | Blast radius of code changes: git diff → affected symbols + risk |

### A Deeper Look

MARM keeps the core MCP surface lean with 7 tools by grouping domain operations behind explicit parameters like `marm_notebook(action=...)`, `marm_delete(type=...)`, and `marm_compaction(action=...)`. Behind those tools, the server handles lifecycle setup, protocol refresh, docs indexing, date context, summary-cache maintenance, write queue handling, project/platform attribution, and health checks. Over HTTP, marm-graph's 5 code-structure tools are bundled by default, bringing the discoverable surface to 12; the code-graph engine starts lazily on first use and never blocks the 7 core tools if it fails to start (`GRAPH_ENABLED=false` disables it outright).

Under the hood, MARM uses SQLite WAL mode, connection pooling, serialized writes, HTTP swarm presets, safe local defaults, exact-query routing for syntax-heavy lookups, FTS→semantic reranking, bounded fallback search, chunk-aware long-memory recall, and summary/context/full recall depths to keep memory fast, stable, and token-efficient as projects grow.

For a deeper look into the MCP behavior, tool parameters, automation, and workflows, see [MCP-HANDBOOK.md](MCP-HANDBOOK.md) and [FAQ.md](marm-mcp-server/marm-docs/FAQ.md).

## Performance & Scaling Benchmarks

MARM is tuned for fast recall first, even as memory grows and multiple agents hit the same server.

### 1. Retrieval Latency Scaling

| Session Size ($N$) | Min Latency | Median Latency | p95 Latency |
| :--- | :--- | :--- | :--- |
| **N = 100** | 12.0 ms | 17.4 ms | 20.8 ms |
| **N = 500** | 12.4 ms | 20.5 ms | 22.6 ms |
| **N = 1,000** | 15.9 ms | 23.3 ms | 25.1 ms |
| **N = 4,000** | 23.1 ms | 30.4 ms | 31.3 ms |

### 2. Multi-Agent Concurrency

- **Parallel recall wins:** 10 concurrent recalls completed in `316.3ms` vs `647.0ms` serial, a `51%` time reduction.

### 3. Write-Time Ingestion Cost

- **Write-time tradeoff:** consolidation raises median ingest from `20.3ms` to `85.2ms` (`4.2x`) so dedupe/clustering cost stays off the hot recall path.

Benchmarks used a real SQLite database and the live `all-MiniLM-L6-v2` encoder on local hardware. Reproduce them: [`marm-mcp-server/scripts/bench_hotpath.py`](marm-mcp-server/scripts/bench_hotpath.py)
