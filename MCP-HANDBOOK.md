# MARM MCP Server Handbook

## Complete Usage Guide for Memory-Augmented AI

**MARM v2.9.1 - Universal MCP Server for AI Memory Intelligence**

---

## Table of Contents

- [Installation & Transport Options](#installation--transport-options)
- [Getting Started](#getting-started)
- [Example Workflow](#example-workflow-cross-ai-research-project)
- [Understanding MARM Memory](#understanding-marm-memory)
- [Complete Tool Reference (9 Tools)](#complete-tool-reference-9-tools)
- [Pro Tips & Best Practices](#pro-tips--best-practices)
- [Advanced Workflows](#advanced-workflows)
- [FAQ](#faq)
- [Troubleshooting Guide](#troubleshooting-guide)

---

## Installation & Transport Options

### HTTP vs STDIO

MARM MCP Server supports two transport modes for different deployment scenarios:

**HTTP Transport** (Default)

- Traditional server-client architecture
- Best for: Multiple concurrent AI clients, cloud/remote deployment, shared memory server
- Setup: Run `python -m marm_mcp_server` and connect via `http://localhost:8001/mcp`

**STDIO Transport** (Process-based)

- Direct stdin/stdout communication
- Best for: CLI tools, orchestration platforms, Cursor IDE, single AI client per process
- Setup: Run `marm-mcp-stdio` (installed console script) or `python -m marm_mcp_server.server_stdio`
- Advantage: No port management, process isolation per connection

### Quick Start Guide

**Docker (HTTP - Fastest):**

```bash
docker pull lyellr88/marm-mcp-server:latest
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  lyellr88/marm-mcp-server:latest
"agent" mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
```

**Local HTTP:**

Default pip/local startup is zero-config: MARM binds to localhost and does not require a key unless you expose it with `SERVER_HOST=0.0.0.0`.

```bash
pip install marm-mcp-server
python -m marm_mcp_server
"agent" mcp add --transport http marm-memory http://localhost:8001/mcp
```

**Codex CLI:**

```bash
# Direct Python install — no key needed
codex mcp add marm-memory --url http://localhost:8001/mcp

# Docker or exposed server — key required
export MARM_API_KEY="your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
```

```toml
[mcp_servers."marm-memory"]
url = "http://localhost:8001/mcp"
enabled = true
bearer_token_env_var = "MARM_API_KEY"
```

**STDIO:**

```bash
# After pip install, use the console script (no path needed):
pip install marm-mcp-server

# Claude Code
claude mcp add --transport stdio marm-memory-stdio marm-mcp-stdio

# Cursor / VS Code (add to mcp.json):
# { "command": "marm-mcp-stdio", "args": [] }

# Or run directly with Python:
python -m marm_mcp_server.server_stdio
```

Replace `marm-mcp-stdio` with `python -m marm_mcp_server.server_stdio` if using a virtualenv or a path-based setup. Works with Claude Code, Cursor, VS Code, Qwen, and Gemini CLI.

**For complete installation instructions, platform-specific configurations, JSON setup, troubleshooting, and detailed transport comparison, see the [README.md Quick Start section](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/README.md#-quick-start-for-mcp-http--stdio).**

### System Requirements

- **Python**: 3.10 or higher
- **SQLite3**: Included with Python (no separate install needed)
- **Storage**: ~100MB minimum for initial setup, scales with memory database size
- **RAM**: 512MB minimum (varies by concurrent clients and database size)
- **OS**: Windows, macOS, Linux

### Data Location & Backup

All MARM data is stored locally in your home directory:

- **Location**: `~/.marm/` (Linux/macOS) or `%USERPROFILE%\.marm\` (Windows)
- **Contents**: SQLite database with all memories, sessions, and notebooks
- **Backup**: Copy the entire `~/.marm/` directory to preserve all data
- **Privacy**: Everything stays on your machine — no cloud sync or external storage

### Verify Installation

After installation, verify MARM is working correctly:

Use the MARM Dashboard status panel for the easiest live check. It polls the MCP server health endpoint and shows reachability, version, status, latency, and last checked time.

For terminal validation:

```bash
curl http://localhost:8001/health
```

Expected output includes:

- Server version
- Feature availability (semantic search status)
- Database connection status
- Service health status

---

## Getting Started

### 💡 **Key Point: Natural Language Interface**

**You don't need to manually call MARM tools!** Just talk to your AI agent naturally:

- *"Claude, log this session as 'Project Alpha'"*
- *"Remember this code snippet for later"*
- *"Search for what we discussed about authentication"*
- *"Add this debugging approach to my notebook"*

Your AI agent will automatically use the appropriate MARM tools. Manual tool access is available for power users, but most users should just **talk naturally** and let the AI handle the tool usage.

MARM also handles lifecycle work internally. Docs and session state initialize on the first real tool call, and docs refresh automatically every 50 tool calls. Packaged docs are indexed into the `marm_system` memory namespace with source-file hash tracking, so unchanged docs are skipped and changed or missing rows are re-indexed.

### What is MARM?

MARM is a **Universal MCP Server** providing intelligent memory that saves across sessions for AI conversations with:

- **Semantic Search** - Find memories by meaning, not keywords
- **Cross-App Memory** - Share memories between AI clients (Claude, Qwen, Gemini)
- **Auto-Classification** - Content automatically categorized for intelligent recall
- **Session Management** - Organize conversations with structured logging

### Core Concepts

**Sessions**: Named containers for organizing memories
**Memories**: Stored content with semantic embeddings for intelligent search
**Notebooks**: Reusable instructions and knowledge snippets
**Logging**: Structured conversation history with timestamps

### Example Workflow: Cross-AI Research Project

Here's a realistic workflow showing MARM in action:

**Scenario:** You're researching authentication patterns for a new project using multiple AI clients.

#### Phase 1: Create Session (Claude)

``` markdown
You: "Claude, create a MARM session called 'auth-research-2025-01'"
Claude calls: marm_log_session("auth-research-2025-01")
Result: Session created. MARM lifecycle/docs initialize automatically.
```

#### Phase 2: Capture Research (Claude)

``` markdown
You: "Summarize OAuth2 vs JWT for API authentication and save it"
Claude calls: marm_context_log("OAuth2 is token-based with refresh cycles, better for delegated access. JWT is stateless, good for microservices...")
Result: Memory stored with auto-classification as "code" content
```

#### Phase 3: Add Reusable Reference (Claude)

``` markdown
You: "Save a JWT validation code snippet to my notebooks as 'jwt-validation-pattern'"
Claude calls: marm_notebook(action="add", name="jwt-validation-pattern", data="def verify_jwt(token):\n  # validation logic...")
Result: Reusable snippet stored for future projects
```

#### Phase 4: Recall Context (Gemini)

``` markdown
You: "Gemini, what authentication approaches did we research? Activate the JWT pattern."
Gemini calls: marm_smart_recall("authentication patterns", search_all=true)
Gemini calls: marm_notebook(action="use", names="jwt-validation-pattern")
Result: Gemini sees previous research + has JWT code available as context
```

#### Phase 5: Synthesis & Summary (Qwen)

``` markdown
You: "Qwen, pull everything from the auth research and create a summary"
Qwen calls: marm_smart_recall("authentication", session="auth-research-2025-01", limit=20)
Qwen calls: marm_summary("auth-research-2025-01")
Result: Qwen generates implementation guide from all captured research
```

#### Phase 6: End Session (Claude)

``` markdown
You: "Log final decision - we're using JWT for APIs and OAuth2 for user auth"
Claude calls: marm_log_entry("DECISION: JWT for API auth, OAuth2 for user flows. Rationale: stateless APIs + delegated user access", session="auth-research-2025-01")
Result: Decision logged and searchable by all future AI clients
```

**Result**: Three different AI clients collaboratively researched a topic, shared insights, and documented decisions—all without re-explaining the project to each new AI.

---

## Understanding MARM Memory

### How Memory Works

MARM uses **semantic embeddings** to understand content meaning, not exact word matches:

```txt
User: "I discussed machine learning algorithms yesterday"
MARM Search: Finds related memories about "ML models", "neural networks", "AI training"
```

### Memory Types

1. **Context Logs** - Auto-classified conversation memories
2. **Manual Entries** - Explicitly saved important information  
3. **Notebook Entries** - Reusable instructions and knowledge
4. **Session Summaries** - Compressed conversation history

### Content Classification

MARM automatically categorizes content:

- **Code** - Programming snippets and technical discussions
- **Project** - Work-related conversations and planning
- **Book** - Literature, learning materials, research
- **General** - Casual conversations and miscellaneous topics

---

## Complete Tool Reference (9 Tools)

| Category | Tool | Description | Usage Notes |
|----------|------|-------------|-------------|
| **🧠 Memory** | `marm_smart_recall` | Semantic similarity search across all memories | `query` (required), `limit` (default: 5), `session_name` (optional). Use natural language queries |
| | `marm_context_log` | Auto-classifying memory storage with embeddings | Store important information that should be remembered |
| **📚 Logging** | `marm_log_session` | Create or switch to named session container | Include LLM name, dates, be descriptive |
| | `marm_log_entry` | Add structured log entry with auto-date formatting | Use structured entries for best results; date-prefixed formats are parsed automatically when provided |
| | `marm_log_show` | Display all entries and sessions with filtering | `session_name` (optional) |
| | `marm_delete` | Delete a log session, log entry, or notebook entry | `type="log"` or `type="notebook"`, `target` (required), `session_name` (optional for log entries) |
| **📔 Notebook** | `marm_notebook` | Unified notebook management | `action="add"` saves entries, `action="use"` activates entries, `action="show"` lists saved entries, `action="status"` shows active entries, `action="clear"` clears active entries. `session_name` scopes active entries when needed |
| **🔄 Workflow** | `marm_summary` | Generate paste-ready context blocks with intelligent truncation | Create summaries for new conversations or context bridging |
| **🧹 Maintenance** | `marm_compaction` | Agent-assisted memory compaction | `action="status"`, `"candidates"`, `"review"`, `"stage"`, `"apply"`, or `"discard"`. Used when MARM detects duplicate memory clusters and asks the agent to summarize them |

**Internal automation:** lifecycle initialization, documentation refresh, current date context, serialized write queue handling, and system checks are no longer AI-facing tools. Documentation refresh uses `doc_index` hash tracking to avoid duplicate `marm_system` memories across restarts. Use the dashboard health panel for live server status, or `curl http://localhost:8001/health` for terminal checks.

**Swarm / multi-agent modes:** Use CLI presets when starting an HTTP server shared by multiple agents:

| Flag | Rate Limit | Write Queue | Use When |
|------|------------|-------------|----------|
| *(none)* | 80 RPM | enabled | Normal local use and small 3-5 agent setups |
| `--swarm` | 200 RPM | enabled | Shared HTTP server, roughly 15-30 agents depending on write style |
| `--swarm-max` | 600 RPM | enabled | Heavier local/private swarm, roughly 50-100 agents depending on write style |
| `--trusted` | disabled | enabled | Private/trusted deployments only |
| `--rate-limit-rpm N` | N RPM | unchanged | Custom override; 0 disables limiting |

```bash
python -m marm_mcp_server --swarm
python -m marm_mcp_server --swarm-max
python -m marm_mcp_server --trusted
```

The write queue is enabled by default and serializes memory writes through one internal async queue to reduce SQLite writer contention. Swarm presets tune the HTTP rate limit on top of that queue behavior. The queue controls write ordering; consolidation and compaction are separate memory-maintenance layers.

**Consolidation / compaction:** `CONSOLIDATION_ENABLED=1` activates write-time exact duplicate and semantic near-duplicate handling before memories accumulate unnecessary duplicates. `COMPACTION_ENABLED=1` activates background cluster detection after enough writes in a session. When compaction candidates are ready, MARM injects a bounded request asking the connected agent to call `marm_compaction`: get candidates, stage summaries, review staged proposals, then apply or discard them. Source memory IDs are preserved so compacted summaries remain traceable.

---

## Pro Tips & Best Practices

### Memory Management Tips

**Memory Compaction**: Let MARM surface compaction candidates, then use `marm_compaction` to stage, review, apply, or discard summaries
**Session Naming**: Include LLM name for cross-referencing
**Strategic Logging**: Focus on key decisions, solutions, discoveries, configurations

### Search Strategies

**Global Search**: Use `search_all=True` to search across all sessions
**Natural Language Search**: "authentication problems with JWT tokens" vs "auth error"
**Temporal Search**: Include timeframes in queries

### Workflow Optimization

**Notebook Stacking**: Combine multiple entries for complex workflows
**Session Lifecycle**: Start → Work → Reference → Review staged compaction when MARM asks

---

## Advanced Workflows

### Project Memory Architecture

```txt
Project Structure:
├── project-name-planning/          # Initial design and requirements
├── project-name-development/       # Implementation details
├── project-name-testing/          # QA and debugging notes  
├── project-name-deployment/       # Production deployment
└── project-name-retrospective/    # Lessons learned
```

### Knowledge Base Development

1. **Capture**: Use `marm_context_log` for new learnings
2. **Organize**: Create themed sessions for knowledge areas
3. **Synthesize**: Regular `marm_summary` for knowledge consolidation
4. **Apply**: Convert summaries to `marm_notebook(action="add", ...)` entries

### Multi-AI Collaboration Pattern

```txt
Phase 1: Individual Research
- Each AI works in dedicated sessions
- Focus on their strengths (Claude=code, Qwen=analysis, Gemini=creativity)

Phase 2: Cross-Pollination  
- Use marm_smart_recall to find relevant insights
- Build upon previous work

Phase 3: Synthesis
- Create collaborative sessions  
- Combine insights for comprehensive solutions
```

## FAQ

The canonical FAQ lives in [docs/FAQ.md](docs/FAQ.md). Use that file for current answers about memory behavior, transports, supported clients, compaction, backups, and troubleshooting.

---

## Troubleshooting Guide

### Server Issues

#### Server won't start

- Check Python version: `python --version` (must be 3.10+)
- Verify port 8001 isn't in use: `lsof -i :8001` (macOS/Linux) or `netstat -ano | findstr :8001` (Windows)
- Check for permission errors in home directory (`~/.marm/` must be readable/writable)
- See platform-specific troubleshooting: [INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md), [INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md), [INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)

#### STDIO connection fails

- Verify `marm-mcp-stdio` is on your PATH after pip install: `marm-mcp-stdio --help`
- Alternatively use: `python -m marm_mcp_server.server_stdio`
- Check AI client documentation for STDIO transport requirements
- Try direct execution to see error messages: `python -m marm_mcp_server.server_stdio`

### Connection & Integration

#### AI client can't connect to MARM

- Verify server is running in the dashboard health panel, or with `curl http://localhost:8001/health`
- Check firewall isn't blocking port 8001
- For STDIO: use `marm-mcp-stdio` (console script) or `python -m marm_mcp_server.server_stdio`
- Restart both server and AI client

#### Tools not appearing in AI client

- Verify HTTP mode in the dashboard health panel, or with `curl http://localhost:8001/health`
- Check server logs for initialization errors
- Disconnect and reconnect AI client to refresh tool list

### Memory & Data Issues

#### Memories not saving

- Verify `~/.marm/` directory exists and has write permissions
- Check available disk space
- Test with simple memory: ask AI to save a single line and check with `marm_log_show`
- For HTTP mode, verify server health in the dashboard health panel, or with `curl http://localhost:8001/health`

#### Search returns no results

- Verify memories exist: use `marm_log_show` to list entries
- Use `search_all=true` to search across all sessions
- Try simpler, more general search queries
- Wait a few seconds—first semantic search loads the ML model

#### Memories appear then disappear

- Check if MARM was restarted or crashed (data persists in `~/.marm/`)
- Verify disk space didn't fill up
- Check system logs for database errors

### Performance

**Slow search results**

- First search is slower (model loads from disk)—subsequent searches are faster
- Large databases (1000+ memories) may take a few seconds
- Limit searches: use `limit=10` instead of unlimited results
- Use `marm_summary` to compress old sessions

#### Server using too much memory

- Notebooks with many entries can accumulate—use `marm_notebook(action="clear")` to prune active entries
- Close unused AI client connections
- Use `marm_compaction(action="review")` to inspect staged compaction summaries when compaction is enabled

### Data Recovery

#### Lost or corrupted data

- Stop the server immediately
- Check `~/.marm/` directory for backup copies (if you created them)
- Restore from backup: copy your backup `~/.marm/` back to home directory
- Restart server

#### Database locked error

- Close all AI client connections
- Stop the server: `Ctrl+C`
- Remove lock file if present: `rm ~/.marm/marm_memory.db-wal` (Linux/macOS)
- Restart server

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `address already in use` | Port 8001 occupied | Kill process on 8001 or use different port |
| `permission denied: ~/.marm/` | Database directory not writable | `chmod 755 ~/.marm/` or check ownership |
| `module not found: core.memory` | Missing dependencies | Reinstall from `marm-mcp-server/`: `pip install -e ".[dev]"` |
| `database is locked` | Multiple processes accessing DB | Close other connections, restart server |
| `embedding model not found` | Semantic search model didn't download | First run takes time—be patient, check internet connection |

---

## Project Documentation

### **Usage Guides**

- **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)** - Complete MCP server usage guide with commands, workflows, and examples
- **[PROTOCOL.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/PROTOCOL.md)** - MCP operating protocol
- **[FAQ.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/FAQ.md)** - Answers to common questions about using MARM

### **MCP Server Installation**

- **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)** - Docker deployment (recommended)
- **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)** - Windows installation guide
- **[INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)** - Linux installation guide
- **[INSTALL-PLATFORMS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORMS.md)** - Platform installation guide

### **Project Information**

- **[README.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/README.md)** - This file - ecosystem overview and MCP server guide
- **[CONTRIBUTING.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/CONTRIBUTING.md)** - How to contribute to MARM
- **[CHANGELOG.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/CHANGELOG.md)** - Version history and updates
- **[ACKNOWLEDGMENTS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ACKNOWLEDGMENTS.md)** - Contributors and acknowledgments
- **[ROADMAP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ROADMAP.md)** - Planned features and development roadmap
- **[LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/LICENSE)** - MIT license terms
