# MARM Systems Roadmap 

> Updated 05/17/2026 this roadmap reflects the current strategic direction and near-term priorities for MARM Systems. It is a living document that will evolve as we learn from users, research, and the rapidly changing AI landscape.

## Strategic Direction

MARM is focused on one clear goal: make AI memory practical across real tools, real projects, and real local workflows.

The active product direction has two tracks:

- **MARM MCP Server**: the agent-facing memory layer used by Claude, Codex, Gemini, Qwen, VS Code, Cursor, and other MCP clients.
- **MARM Dashboard**: the human-facing local admin UI for inspecting, editing, exporting, and maintaining the same memory database.

MARM is not currently being built as a paid upgrade product. The near-term focus is a strong open base: reliable local memory, clean transports, useful dashboard workflows, and future extension points for plugins, SDKs, research, and team workflows.

---

## Current Foundation

MARM now has the core pieces needed for a serious local memory system:

- **MCP server** with persistent SQLite memory, session logs, notebooks, semantic recall, and context tools
- **HTTP transport** for long-running or shared local server workflows
- **STDIO transport** for private local client-launched workflows
- **Docker support** with HTTP and STDIO modes from one image
- **API-key auth** for Docker, exposed, or shared HTTP deployments
- **VS Code and Cursor support** through native MCP config files
- **MARM Dashboard** as an optional local SQLite admin UI for human memory management
- **Fresh test suite** covering HTTP tools, auth, rate limits, response limits, database behavior, STDIO, and Docker smoke paths
- **Automation scripts** for version sync, test runs, stale-doc scans, Docker smoke, and release preflight

---

## MCP Server Roadmap

### 1. Automatic Memory Context Layer

Today, MARM memory is strongest when an agent explicitly calls recall. The next major improvement is making relevant memory easier to surface at the right time.

Planned direction:

- Add smarter recall paths that pull relevant memories based on active topic, session, and project context
- Let `marm_smart_recall` optionally include structured logs so one tool can return both memory and decision history
- Reduce reliance on separate context-bridge style tools when the agent can format the final reasoning itself
- Keep user/agent control explicit so automatic context does not become noisy or surprising

Why it matters:

AI agents should not have to remember exactly when to ask for memory. MARM should make useful context easier to retrieve while still staying transparent and controllable.

### 2. Memory Evolution and Relevance Learning

As memory grows, raw semantic recall is not enough. MARM needs to learn which memories remain useful and which ones are stale.

Planned direction:

- Track lightweight usage signals such as recalled, edited, deleted, reused, or ignored memories
- Improve ranking over time using recency, frequency, session/project relevance, and user cleanup behavior
- Identify related memories across sessions so solutions, decisions, and patterns are easier to rediscover
- Add stale-memory indicators so users can clean old or low-value entries from the dashboard

Why it matters:

The value of memory is not just storage. It is retrieval quality. The system should get better as it is used, not noisier.

### 3. Project-Scoped and Shared Memory

MARM already supports shared HTTP server mode through Docker/API-key deployments. That creates the foundation for shared workspaces, but the memory model needs better organization before team usage scales.

Planned direction:

- Keep a global/default memory pool for general knowledge
- Add optional per-project memory databases or project scopes
- Track known project memory locations in a lightweight index
- Search active project memory first, then allow cross-project recall when useful
- Support shared HTTP deployments where multiple authorized users/agents can write to the same memory store
- Label recall results by project/session/source so agents can tell where context came from

Why it matters:

One flat memory pool works at small scale. Larger multi-project and multi-agent workflows need cleaner boundaries without losing cross-project learning.

### 4. Research Memory Integration

This is the highest-leverage future feature: a separate research layer that helps bridge model knowledge cutoffs without dumping untrusted web content directly into curated memory.

Planned direction:

- Maintain a separate research database for external findings
- Let users or agents trigger research on specific topics, errors, APIs, libraries, or project questions
- Store source, date, summary, relevance score, and URL for each finding
- Keep research findings separate from curated MARM memory until promoted by the user or agent
- Add tools to review, search, promote, dismiss, or bookmark research findings
- Start with manual/on-demand research before considering background automation

Why it matters:

MARM can become a memory system plus a research staging area. That gives agents access to current external context while preserving trust: researched information is reviewed before it becomes core memory.

### 5. Tool Surface Cleanup

The MCP tool list should stay focused on actions an AI agent actually needs.

Planned direction:

- Combine overlapping delete operations where practical
- Retire redundant tools when one stronger tool can cover the same workflow
- Move internal/status-only behavior out of the AI-facing tool list
- Keep health checks, reloads, and maintenance actions available through HTTP or scripts where that is cleaner

Why it matters:

Fewer, clearer tools improve client discovery, reduce token overhead, and make agent tool selection more reliable.

---

## Dashboard Roadmap

### 1. Export and Reporting

The dashboard is the natural place for human-friendly memory export.

Planned direction:

- Export memories, logs, sessions, and notebooks to Markdown
- Add JSON export for backups and integrations
- Add CSV export for spreadsheet review and audit workflows
- Add filtered exports by session, project, date range, or context type
- Consider PDF summaries later if Markdown/JSON/CSV prove useful first

Why it matters:

Memory should be portable. Users need backups, reports, and ways to move MARM knowledge into docs, GitHub, Notion, Confluence, or other systems.

### 2. Safer Admin Workflows

The dashboard already asks before destructive actions. The next step is making high-impact edits even safer and easier to inspect.

Planned direction:

- Optional read-only launch mode
- Export-before-delete prompts for bulk actions
- Clearer distinction between viewing, editing, and deleting
- Better bulk-action summaries before confirmation
- More visible database path and active auth mode
- Backup/import helpers for `~/.marm/marm_memory.db`

Why it matters:

The dashboard can edit real memory. It should feel efficient, but not casual about destructive changes.

### 3. Dashboard and MCP Schema Alignment

The dashboard writes directly to SQLite, so it must stay aligned with MCP schema changes.

Planned direction:

- Add tests for dashboard compatibility with current MCP tables
- Keep dashboard CRUD behavior aligned with MCP sanitization and metadata conventions
- Surface MCP server reachability and database state clearly
- Avoid adding dashboard-only fields unless the MCP server also understands them

Why it matters:

The dashboard is useful because it manages the same data. Schema drift would make it dangerous.

---

## Shared Technical Priorities

These are not product features, but they keep both tracks trustworthy.

- Keep the test suite green and expand it around real workflows
- Run Docker HTTP and STDIO smoke checks before public releases
- Keep install docs aligned with tested client behavior
- Remove stale setup paths from active docs
- Keep version numbers synced from the latest changelog entry
- Maintain release automation that reports problems without hiding changes

---

## Long-Term Possibilities

These are conditional directions after the MCP server and dashboard are stable:

- **Plugin integrations** for editors, local tools, and MCP client ecosystems
- **SDKs** for developers who want MARM-backed memory in their own apps
- **Optional sync architecture** for cross-device memory access
- **Real multi-user identity and permissions** for hosted or team deployments
- **Research automation** after manual research review workflows prove useful

The guiding rule: new integrations should strengthen MARM as a memory layer, not pull it back into unrelated app sprawl.
