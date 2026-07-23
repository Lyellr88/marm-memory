# marm-memory FAQ

Common questions about MARM MCP, memory behavior, transports, supported clients, and local deployment.

---

## General

### Q: What is marm-memory?

marm-memory is a persistent memory layer for AI agents. The MCP server gives Claude, Codex, Gemini, Qwen, VS Code, Cursor, and other MCP-compatible clients a shared way to store, recall, organize, and reuse project context across sessions.

| Component | Description | Best For |
|-----------|-------------|----------|
| **MARM MCP Server** | Persistent memory server with 14 MCP tools (HTTP + STDIO): 7 core memory tools, 5 bundled code-graph tools, and 2 concept-graph tools | AI agents, IDEs, local workflows, shared team memory |
| **MARM Protocol** | Runtime guidance delivered automatically by the MCP server | Keeping agents aligned on what to store, recall, and trust |
| **MARM Console** | Local browser UI for viewing memory, knowledge, projects, and server health | Inspection, cleanup, and quick status checks |

### Q: How is MARM different from built-in AI memory?

| Feature | Built-in AI Memory | marm-memory |
|---------|-------------------|--------------|
| **Control** | Limited and platform-defined | User-owned SQLite database |
| **Portability** | Usually platform-locked | Works across MCP-compatible clients |
| **Recall** | Often opaque | Explicit hybrid recall and structured logs |
| **Sharing** | Hard to move between tools | Multiple agents can use the same memory store |
| **Trust model** | Memory behavior varies by provider | Retrieved memory is context, not higher-priority instruction |

MARM uses filter→rerank hybrid recall rather than simple keyword matching alone. FTS keyword/BM25 search narrows exact-term candidates first, semantic embeddings rerank that bounded set by meaning, and a bounded semantic fallback keeps abstract queries working when keyword coverage is weak.

### Q: Who is MARM for?

MARM is strongest for developers, researchers, power users, and teams doing long-running work where context continuity matters. It is less useful for quick one-off questions where a normal chat is enough.

### Q: How much memory can MARM store?

MARM does not enforce a small fixed memory limit. It stores data in a local SQLite database under `~/.marm/`, with semantic embeddings and an FTS index for recall. Practical limits depend on disk space, database size, and how much old context you keep searchable.

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

For HTTP mode, run `marm-memory status` or `marm-memory doctor`. The raw health endpoint remains available at `http://localhost:8001/health`. For STDIO mode, confirm your MCP client lists the MARM tools and can call a simple recall or log command.

---

### Tools & Capabilities

#### Q: What MCP tools does MARM provide?

MARM currently exposes **14 MCP tools on both HTTP and STDIO**: 7 focused core memory tools, 5 bundled code-graph tools, and 2 concept-graph tools.

| Category | Tools | Description |
|----------|-------|-------------|
| **Memory Intelligence** | `marm_smart_recall` | Hybrid recall across memories |
| **Logging** | `marm_log_entry`, `marm_log_show` | Session-based conversation/project logs with server-managed summary-cache refresh; entries are also stored as semantic memories for recall |
| **Notebook** | `marm_notebook` | Reusable instructions and knowledge with `action="add"`, `"use"`, `"show"`, `"status"`, or `"clear"` |
| **Delete** | `marm_delete` | Delete log sessions, log entries, or notebook entries |
| **Summary** | `marm_summary` | Generate concise context summaries |
| **Maintenance** | `marm_compaction` | Agent-assisted memory compaction with `action="status"`, `"candidates"`, `"review"`, `"stage"`, `"apply"`, or `"discard"` |
| **Code Graph (HTTP + STDIO)** | `marm_graph_index`, `marm_code_lookup`, `marm_graph_trace`, `marm_graph_architecture`, `marm_graph_impact` | Index repositories, look up symbols/source, trace call paths, summarize architecture, and inspect change impact |
| **Concept Graph (HTTP + STDIO)** | `marm_concept_build`, `marm_concept_recall` | Extract entities and typed relationships from stored memories, then query them with multi-hop traversal and code-symbol cross-links |

#### Q: Do I still need to call `marm_start`?

No. Session startup, protocol delivery, protocol-lite refresh, and documentation loading are automatic. The server injects the protocol on the first successful MCP tool call for each session scope, then periodically refreshes the lightweight protocol reference and keeps docs indexed with hash-based caching so unchanged docs are not repeatedly duplicated.

#### Q: What is the concept graph and how do I use it?

The concept graph turns stored memories into a queryable knowledge graph. `marm_concept_build` extracts typed entities (concepts, decisions, patterns, errors, tools, people, organizations) and typed relationships (fixes, implements, depends_on, uses, causes, replaces, extends) from memory content. `marm_concept_recall` then answers direct lookups (a bare entity name) or multi-hop traversals (`"related to X"` with `depth` up to 5). Builds are explicit and on-demand: run a build scoped to a `session_name`, `project`, or `search_all=True` first, and re-run after logging significant new memories. When the code graph has indexed the same project, matching entities cross-link to code symbols.

#### Q: Why does `marm_concept_build` return `entities_extracted: 0`?

The spaCy runtime and English extraction model are bundled with MARM and load only when you build the concept graph. First confirm that the build scope includes memories with extractable entities, then run `marm-memory knowledge status`. If it reports a damaged or partial install, repair it with `python -m pip install -U --force-reinstall marm-mcp-server`. Core memory remains available if concept extraction cannot initialize.

#### Q: What happens if a graph engine fails to start?

Nothing breaks. The code-graph engine starts lazily on first graph-tool use; if it cannot start (no network for the first-run download, disk full, `GRAPH_ENABLED=false`), graph tools return `{"status": "error", "message": "graph backend unavailable"}` while all other tools keep working. The concept graph stores its data in a separate SQLite database (`~/.marm/index/`) with its own connection pool, so it can never block the main memory database.

---

### Multi-Agent & Swarm

#### Q: What should I use for multi-agent or swarm-style workflows?

Use HTTP mode so one MARM server coordinates shared database access. The write queue is enabled by default. Start shared servers with `marm-memory start --profile swarm` for 200 RPM, `--profile swarm-max` for 600 RPM, or `--profile trusted` to disable rate limiting on a private trusted deployment.

Run one MARM HTTP process per SQLite database. Multi-process Uvicorn/Gunicorn workers are not supported yet because the write queue, scheduler, protocol delivery, and some active session state are process-local. Swarm presets increase safe concurrency inside one process; true multi-worker HTTP scaling is future work.

#### Q: Can multiple AI agents share the same memory?

Yes. Use HTTP mode for shared access. Multiple agents can read and write to the same SQLite database through one MARM server process. Avoid running many separate STDIO containers against the same SQLite file at the same time; SQLite locking can apply under concurrent writes.

#### Q: Do I need to restart MARM when switching between AI clients?

No. In HTTP mode, MARM runs as a server and multiple clients can connect to it. In STDIO mode, each client usually launches its own private MARM process.

#### Q: What happens if the MARM server is offline?

Your AI client can still run, but MARM memory tools will be unavailable until the server reconnects or the STDIO process restarts.

---

### Memory, Search & Maintenance

#### Q: How does recall work?

MARM uses filter→rerank hybrid recall. FTS keyword/BM25 search handles exact terms first, semantic embeddings rerank those candidates by meaning, and a conservative temporal weighting step gives newer memories a modest boost when scores are otherwise close. Long memories are embedded through overlapping chunks internally so details past the base encoder window are still searchable, but recall still returns one parent memory result rather than many chunk fragments. If FTS returns no useful candidate path, MARM falls back to the existing bounded semantic recall lane, and that fallback path is chunk-aware too. A search for "authentication error" can surface memories about login failures, access denial, token setup, or user verification even when those exact words are not repeated, while a search for something like `COMPACTION_TRIGGER_COUNT` or a Docker command can hit the exact stored text reliably.

#### Q: How do session summaries stay current?

`marm_log_entry` marks the session summary cache dirty whenever logs change. `marm_summary` rebuilds the cached summary only when needed, verifies the cached entry count before reuse, and trims oversized responses to stay within MCP response limits.

#### Q: Can I search across all sessions or just one?

Both. `marm_smart_recall` searches one session by default and can search across all sessions with `search_all=True`.

It can also filter by `project` and `platform` when those metadata fields are available. New memories, logs, and notebook entries are tagged from detected settings or explicit `MARM_PROJECT` / `MARM_PLATFORM` environment variables. Leaving those filters unset keeps the current broad search behavior.

When the semantic fallback lane reaches its configured scan cap, responses include `recall_scan_truncated=true` and `recall_scan_limit` so agents know that part of recall was bounded. The primary filter→rerank lane does not set truncation because it works over a fixed FTS candidate set instead of a broad embedding scan.

`FTS_CANDIDATE_LIMIT` (default `50`) controls how many FTS candidates are fetched before semantic reranking. Most users should leave it alone unless their memory store has weak keyword overlap and they want a wider rerank pool.

If you need less context back from each hit, `marm_smart_recall` also supports `detail=1/2/3` so agents can default to short previews and only request full memory bodies when needed.

For long entries, chunking is internal only: agents still read the parent memory content once, not separate chunk records.

#### Q: When should I create a new session vs. continuing an existing one?

Create a new session for a distinct project, topic, or workstream. Continue an existing session when the new work depends on the same decisions, constraints, or context.

#### Q: Should I log everything or be selective?

Be selective. Log decisions, solutions, insights, requirements, constraints, and important discoveries. Avoid filling memory with low-value transcript noise.

#### Q: How do I organize memories for team collaboration?

Use consistent session names, include project or workstream names, and rely on cross-session search for broad recall. MARM also records nullable `project` and `platform` metadata on new memories, logs, and notebook entries, so agents can scope recall to a project or client when needed. For shared agent workflows, prefer HTTP mode so one server coordinates writes.

#### Q: Does MARM clean up duplicate memories automatically?

MARM has optional memory-maintenance layers. `CONSOLIDATION_ENABLED=1` enables write-time exact duplicate and semantic near-duplicate handling. `COMPACTION_ENABLED=1` enables background candidate detection; when candidates are ready, MARM asks the connected agent to use `marm_compaction` to stage, review, apply, or discard summaries. Source memory IDs stay attached for traceability.

#### Q: How often should I use compaction?

For normal use, wait for MARM to surface compaction candidates. For heavy shared-memory workflows, review staged summaries periodically so old duplicate clusters do not add recall noise.

#### Q: Can I back up my MARM memory?

Yes. Back up the `~/.marm/` directory to preserve your database and related local MARM state.

#### Q: Can memories override system or developer instructions?

No. Retrieved memories, notebook entries, logs, and tool outputs are treated as context only. They must not override higher-priority instructions, request secrets, bypass tool policies, or change the agent's safety rules.
