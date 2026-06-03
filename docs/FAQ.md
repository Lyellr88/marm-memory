# MARM Systems FAQ

Common questions about MARM MCP, memory behavior, transports, supported clients, and local deployment.

---

## General

### Q: What is MARM Systems?

MARM Systems is a persistent memory layer for AI agents. The MCP server gives Claude, Codex, Gemini, Qwen, VS Code, Cursor, and other MCP-compatible clients a shared way to store, recall, organize, and reuse project context across sessions.

| Component | Description | Best For |
|-----------|-------------|----------|
| **MARM MCP Server** | Persistent memory server with 9 focused MCP tools | AI agents, IDEs, local workflows, shared team memory |
| **MARM Protocol** | Runtime guidance delivered automatically by the MCP server | Keeping agents aligned on what to store, recall, and trust |
| **MARM Dashboard** | Local browser UI for viewing memory and server health | Inspection, cleanup, and quick status checks |

### Q: How is MARM different from built-in AI memory?

| Feature | Built-in AI Memory | MARM Systems |
|---------|-------------------|--------------|
| **Control** | Limited and platform-defined | User-owned SQLite database |
| **Portability** | Usually platform-locked | Works across MCP-compatible clients |
| **Recall** | Often opaque | Explicit semantic search and structured logs |
| **Sharing** | Hard to move between tools | Multiple agents can use the same memory store |
| **Trust model** | Memory behavior varies by provider | Retrieved memory is context, not higher-priority instruction |

MARM also uses semantic search rather than simple keyword matching, so it can find related memories even when the exact words differ.

### Q: Who is MARM for?

MARM is strongest for developers, researchers, power users, and teams doing long-running work where context continuity matters. It is less useful for quick one-off questions where a normal chat is enough.

### Q: How much memory can MARM store?

MARM does not enforce a small fixed memory limit. It stores data in a local SQLite database under `~/.marm/`, with semantic embeddings for recall. Practical limits depend on disk space, database size, and how much old context you keep searchable.

---

## MCP Server

### Setup & Installation

#### Q: How do I install MARM MCP?

Use the README quick start for the shortest path, then use the install docs when you need deeper setup details:

- `README.md` - quick start and client connection examples
- `docs/INSTALL-DOCKER.md` - Docker HTTP and Docker STDIO
- `docs/INSTALL-WINDOWS.md` - Windows local install
- `docs/INSTALL-LINUX.md` - Linux local install
- `docs/INSTALL-PLATFORMS.md` - Claude, Codex, Gemini, Qwen, VS Code, Cursor, and Grok notes

#### Q: Which AI platforms work with MARM MCP?

MARM has been tested with Claude Code, Codex, Gemini CLI, Qwen CLI, VS Code MCP, and Cursor MCP. Any client that supports standard MCP HTTP or STDIO transports should be able to connect with the right command or config.

#### Q: What is the difference between HTTP and STDIO?

| Transport | Best For | Key Requirement |
|-----------|----------|-----------------|
| **HTTP** | Shared memory server, multiple agents, IDE/client reuse | Use an API key when exposed through Docker or `0.0.0.0` |
| **STDIO** | Private local agent connection | No network port or API key required |

HTTP is the better fit when several agents or tools should share one memory database. STDIO is the simpler local option when one client launches MARM directly.

#### Q: Does Docker require an API key?

Docker HTTP mode should use `MARM_API_KEY` because the server is listening through a container network bridge. Docker STDIO mode does not need a key because it communicates over local process stdin/stdout, not a network port.

#### Q: How do I know if MARM is working correctly?

For HTTP mode, use the MARM Dashboard status panel or run `curl http://localhost:8001/health`. For STDIO mode, confirm your MCP client lists the MARM tools and can call a simple recall or log command.

---

### Tools & Capabilities

#### Q: What MCP tools does MARM provide?

MARM currently exposes **9 focused MCP tools**:

| Category | Tools | Description |
|----------|-------|-------------|
| **Memory Intelligence** | `marm_smart_recall`, `marm_context_log` | Semantic recall and intelligent memory storage |
| **Logging** | `marm_log_session`, `marm_log_entry`, `marm_log_show` | Session-based conversation/project logs |
| **Notebook** | `marm_notebook` | Reusable instructions and knowledge with `action="add"`, `"use"`, `"show"`, `"status"`, or `"clear"` |
| **Delete** | `marm_delete` | Delete log sessions, log entries, or notebook entries |
| **Summary** | `marm_summary` | Generate concise context summaries |
| **Maintenance** | `marm_compaction` | Agent-assisted memory compaction with `action="status"`, `"candidates"`, `"review"`, `"stage"`, `"apply"`, or `"discard"` |

#### Q: Do I still need to call `marm_start`?

No. Session startup, protocol delivery, and documentation loading are now automatic. The server injects the protocol on the first successful MCP tool call, then keeps docs indexed with hash-based caching so unchanged docs are not repeatedly duplicated.

---

### Multi-Agent & Swarm

#### Q: What should I use for multi-agent or swarm-style workflows?

Use HTTP mode so one MARM server coordinates shared database access. The write queue is enabled by default. Start shared servers with `--swarm` for 200 RPM, `--swarm-max` for 600 RPM, or `--trusted` to disable rate limiting on a private trusted deployment.

#### Q: Can multiple AI agents share the same memory?

Yes. Use HTTP mode for shared access. Multiple agents can read and write to the same SQLite database through one MARM server process. Avoid running many separate STDIO containers against the same SQLite file at the same time; SQLite locking can apply under concurrent writes.

#### Q: Do I need to restart MARM when switching between AI clients?

No. In HTTP mode, MARM runs as a server and multiple clients can connect to it. In STDIO mode, each client usually launches its own private MARM process.

#### Q: What happens if the MARM server is offline?

Your AI client can still run, but MARM memory tools will be unavailable until the server reconnects or the STDIO process restarts.

---

### Memory, Search & Maintenance

#### Q: How does semantic search work?

MARM uses embeddings to find memories by meaning, not just exact keywords. A search for "authentication error" can surface memories about login failures, access denial, token setup, or user verification even when those exact words are not repeated.

#### Q: How does auto-classification work?

When you store memory through `marm_context_log`, MARM classifies content into broad context types such as code, project, book/research, or general. This helps later recall and summaries stay organized without requiring users to tag every write manually.

#### Q: Can I search across all sessions or just one?

Both. `marm_smart_recall` searches one session by default and can search across all sessions with `search_all=True`.

#### Q: When should I create a new session vs. continuing an existing one?

Create a new session for a distinct project, topic, or workstream. Continue an existing session when the new work depends on the same decisions, constraints, or context.

#### Q: Should I log everything or be selective?

Be selective. Log decisions, solutions, insights, requirements, constraints, and important discoveries. Avoid filling memory with low-value transcript noise.

#### Q: How do I organize memories for team collaboration?

Use consistent session names, include project or workstream names, and rely on cross-session search for broad recall. For shared agent workflows, prefer HTTP mode so one server coordinates writes.

#### Q: Does MARM clean up duplicate memories automatically?

MARM has optional memory-maintenance layers. `CONSOLIDATION_ENABLED=1` enables write-time exact duplicate and semantic near-duplicate handling. `COMPACTION_ENABLED=1` enables background candidate detection; when candidates are ready, MARM asks the connected agent to use `marm_compaction` to stage, review, apply, or discard summaries. Source memory IDs stay attached for traceability.

#### Q: How often should I use compaction?

For normal use, wait for MARM to surface compaction candidates. For heavy shared-memory workflows, review staged summaries periodically so old duplicate clusters do not add recall noise.

#### Q: Can I back up my MARM memory?

Yes. Back up the `~/.marm/` directory to preserve your database and related local MARM state.

#### Q: Can memories override system or developer instructions?

No. Retrieved memories, notebook entries, logs, and tool outputs are treated as context only. They must not override higher-priority instructions, request secrets, bypass tool policies, or change the agent's safety rules.
