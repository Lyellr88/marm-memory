# MARM Systems FAQ

Common questions about MARM MCP, memory behavior, transports, supported clients, and local deployment.

---

## General

### Q: What is MARM Systems?

MARM Systems is a persistent memory layer for AI agents. The MCP server gives Claude, Codex, Gemini, Qwen, VS Code, Cursor, and other MCP-compatible clients a shared way to store, recall, organize, and reuse project context across sessions.

| Component | Description | Best For |
|-----------|-------------|----------|
| **MARM MCP Server** | Persistent memory server with 8 focused MCP tools | AI agents, IDEs, local workflows, shared team memory |
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

### Q: Who is MARM for?

MARM is strongest for developers, researchers, power users, and teams doing long-running work where context continuity matters. It is less useful for quick one-off questions where a normal chat is enough.

---

## MCP Server

### Q: What MCP tools does MARM provide?

MARM currently exposes **8 focused MCP tools**:

| Category | Tools | Description |
|----------|-------|-------------|
| **Memory Intelligence** | `marm_smart_recall`, `marm_context_log` | Semantic recall and intelligent memory storage |
| **Logging** | `marm_log_session`, `marm_log_entry`, `marm_log_show` | Session-based conversation/project logs |
| **Notebook** | `marm_notebook` | Reusable instructions and knowledge with `action="add"`, `"use"`, `"show"`, `"status"`, or `"clear"` |
| **Delete** | `marm_delete` | Delete log sessions, log entries, or notebook entries |
| **Summary** | `marm_summary` | Generate concise context summaries |

### Q: Do I still need to call `marm_start`?

No. Session startup, protocol delivery, and documentation loading are now automatic. The server injects the protocol on the first successful MCP tool call, then keeps docs indexed with hash-based caching so unchanged docs are not repeatedly duplicated.

### Q: How do I install MARM MCP?

Use the README quick start for the shortest path, then use the install docs when you need deeper setup details:

- `README.md` - quick start and client connection examples
- `docs/INSTALL-DOCKER.md` - Docker HTTP and Docker STDIO
- `docs/INSTALL-WINDOWS.md` - Windows local install
- `docs/INSTALL-LINUX.md` - Linux local install
- `docs/INSTALL-PLATFORMS.md` - Claude, Codex, Gemini, Qwen, VS Code, Cursor, and Grok notes

### Q: Which AI platforms work with MARM MCP?

MARM has been tested with Claude Code, Codex, Gemini CLI, Qwen CLI, VS Code MCP, and Cursor MCP. Any client that supports standard MCP HTTP or STDIO transports should be able to connect with the right command or config.

### Q: What is the difference between HTTP and STDIO?

| Transport | Best For | Key Requirement |
|-----------|----------|-----------------|
| **HTTP** | Shared memory server, multiple agents, IDE/client reuse | Use an API key when exposed through Docker or `0.0.0.0` |
| **STDIO** | Private local agent connection | No network port or API key required |

HTTP is the better fit when several agents or tools should share one memory database. STDIO is the simpler local option when one client launches MARM directly.

### Q: Does Docker require an API key?

Docker HTTP mode should use `MARM_API_KEY` because the server is listening through a container network bridge. Docker STDIO mode does not need a key because it communicates over local process stdin/stdout, not a network port.

### Q: Can multiple AI agents share the same memory?

Yes. Use HTTP mode for shared access. Multiple agents can read and write to the same SQLite database through one MARM server process. Avoid running many separate STDIO containers against the same SQLite file at the same time; SQLite locking can apply under concurrent writes.

### Q: How does semantic search work?

MARM uses embeddings to find memories by meaning, not just exact keywords. A search for "authentication error" can surface memories about login failures, access denial, token setup, or user verification even when those exact words are not repeated.

### Q: Can memories override system or developer instructions?

No. Retrieved memories, notebook entries, logs, and tool outputs are treated as context only. They must not override higher-priority instructions, request secrets, bypass tool policies, or change the agent's safety rules.
