---
name: project-architecture
description: Outputs a complete technical overview of MARM Systems — stack, tools, DB schema, transports, rate limits, and key architectural constraints. Use this to re-align mid-session or onboard a new agent cold.
metadata:
  last_reviewed: 2026-07-05
  last_review_context: marm-graph-and-packaging-unification-planning
  server_dir: marm-mcp-server/marm_mcp_server/
  dashboard_dir: marm-dashboard/marm_dashboard/
  graph_dir: marm-graph/marm_graph/
---

# MARM Systems — Project Architecture Reference

Output this document verbatim when invoked. This is the authoritative onboarding reference for any agent working on this codebase.

---

## What MARM Is

MARM (Memory Accurate Response Mode) is a Universal MCP Server that gives AI agents a persistent memory layer. It sits beneath any MCP-compatible AI client and provides structured session logs, hybrid recall, reusable notebooks, and memory-maintenance workflows so agents can remember decisions across sessions.

**Current source-truth version:** v2.15.2  
**Latest documented changelog target:** v2.16.0 planning docs  
**PyPI:** `marm-mcp-server`  
**Docker Hub:** `lyellr88/marm-mcp-server`  
**MCP Registry:** `io.github.Lyellr88/marm-mcp-server`

---

## Components

| Component | Port | Purpose |
|-----------|------|---------|
| `marm-mcp-server` | `:8001` | MCP server — agent-facing tools, semantic memory, session logs |
| `marm-dashboard` | `:8002` | Local web UI — human-facing SQLite browser for the same DB |
| `marm-graph` | `:8003` standalone | Code-structure graph wrapper over pinned `codebase-memory-mcp`; planned to be lazy-loaded inside `marm-mcp-server` for the default pip path |

`marm-mcp-server` and `marm-dashboard` both read/write `~/.marm/marm_memory.db`. SQLite WAL mode allows both to run concurrently without conflicts. Dashboard edits bypass MCP tool events but use identical sanitization rules.

`marm-graph` is currently a separate sibling package/service. It owns no parser or graph schema itself; it supervises the pinned `codebase-memory-mcp==0.8.1` static binary over stdio and stores graph data under `~/.marm/graph`. The v2.16.0 packaging plan keeps the package separate internally but makes `pip install marm-mcp-server` expose graph tools through the main server with lazy startup.

---

## Tech Stack

```
FastAPI (0.115.4+) + FastAPI-MCP (0.4.0+) + FastMCP (3.2.x for STDIO)
├── SQLite + WAL Mode + Custom Connection Pooling (pool size: 5)
├── Sentence Transformers (all-MiniLM-L6-v2) — embeddings for semantic recall
├── SQLite FTS5 — exact-term recall for commands, config keys, filenames, and errors
├── marm-graph (0.1.0) — code-structure graph wrapper over codebase-memory-mcp
├── codebase-memory-mcp (0.8.1) — pinned static binary, spawned over stdio by marm-graph
├── structlog — structured logging
├── psutil — memory monitoring
├── IP-Based Rate Limiting (middleware layer)
├── MCP Response Size Compliance — 1MB hard limit (MCPResponseLimiter)
├── Serialized Write Queue — default-on protection for concurrent writes
├── Consolidation Worker — exact hash dedup + semantic write-time merge
├── Compaction Worker — staged memory cleanup plus server-side fallback summarization
├── Event-Driven Automation (services/automation.py)
├── utils/security.py — pure key generation, zero side effects (generate_api_key())
└── Docker multi-stage build — production containerized deployment
```

**Note:** Mock OAuth removed in v2.3.0. Auth is now API key only — loopback-free for localhost, bearer token for Docker/exposed.

**Python:** 3.10+  
**Run command:** `python -m marm_mcp_server`  
**Health check:** `curl http://localhost:8001/health`  
**API docs:** `http://localhost:8001/docs`

**Graph standalone run command:** `python -m marm_graph` or `marm-graph`  
**Graph standalone STDIO:** `python -m marm_graph.server_stdio`  
**Graph status:** standalone service defaults to `127.0.0.1:8003`; default user path is planned to become internal/lazy under `marm-mcp-server`, not a separate port.

---

## Transport Modes

| Transport | Endpoint | Status | Notes |
|-----------|----------|--------|-------|
| HTTP | `http://localhost:8001/mcp` | Stable | Default. Multiple concurrent clients. |
| STDIO | `server_stdio.py` via FastMCP | Stable | Per-process isolation. No key required. |
| Graph HTTP | `http://localhost:8003` standalone | New/planned integration | `marm-graph` standalone server; default v2.16 plan folds graph tools into `marm-mcp-server` with no separate user-facing port. |
| Graph STDIO | `marm_graph.server_stdio` | New | Standalone local MCP path for graph-only advanced use. |
| WebSocket | — | Removed from active paths | Purged from install docs in v2.4.0 |

**Docker dual-transport:** One image, two usage modes — HTTP (long-running/shared, requires `MARM_API_KEY`) or STDIO (local/private, no key required).

---

## STDIO Diagnostics 
STDIO mode writes to `~/.marm/logs/marm-stdio.log` and echoes to `stderr` alongside FastMCP output.

| Env Var | Default | Effect |
|---------|---------|--------|
| `MARM_STDIO_LOG_LEVEL` | `INFO` | Set to `DEBUG` for session name, query length, result counts |
| `MARM_STDIO_LOG_DIR` | `~/.marm/logs` | Override log path (used in tests) |

**What is logged:** tool name, CALL/OK/FAIL/EXCEPTION, startup (version + db path + semantic search), shutdown.  
**What is never logged:** memory content, notebook data, query text, API keys, raw JSON-RPC payloads.

Live tail: `Get-Content "$env:USERPROFILE\.marm\logs\marm-stdio.log" -Wait -Tail 20`

---

## Auth Model

| Deployment | Key Required | How |
|------------|-------------|-----|
| pip + `127.0.0.1` (default) | No | Loopback passthrough |
| pip + `SERVER_HOST=0.0.0.0` | Auto-generated | Key saved to `~/.marm/.env` on first start |
| Docker HTTP | Yes | `MARM_API_KEY` env var + `--generate-key` CLI |
| Docker STDIO | No | Per-process isolation |

**`--generate-key` CLI:** `python -m marm_mcp_server --generate-key` prints a 40-char key (68-char alphabet, ~244 bits) and exits without starting the server.

**Middleware order (LIFO):** Rate limiter registers after auth in code but runs first at request time — throttles floods before token validation.

---

## Verified MCP Clients

Claude Code, Codex, Gemini CLI, Qwen Code, VS Code (`.vscode/mcp.json`), Cursor (`.cursor/mcp.json`), xAI/Grok Remote MCP.

---

## Database Schema (Active Core Tables)

All tables live in a single SQLite file at `~/.marm/marm_memory.db`. Schema is managed through `marm_mcp_server/core/memory_db.py` and wired by the `MARMMemory` facade in `core/memory.py`. Always use `CREATE TABLE IF NOT EXISTS` — never drop columns. Add new columns via idempotent `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`.

**`memories`** — semantic memory storage
```sql
id TEXT PRIMARY KEY, session_name TEXT, content TEXT,
embedding BLOB, timestamp TEXT, context_type TEXT DEFAULT 'general',
metadata TEXT DEFAULT '{}', created_at TEXT,
content_hash TEXT, compaction_role TEXT, compacted_into TEXT,
project TEXT DEFAULT NULL, platform TEXT DEFAULT NULL
```

**`sessions`** — session containers
```sql
session_name TEXT PRIMARY KEY, marm_active BOOLEAN DEFAULT FALSE,
created_at TEXT, last_accessed TEXT, metadata TEXT DEFAULT '{}'
```

**`log_entries`** — structured session logs; nullable `project` / `platform` columns attribute entries to a project and client when detected  
**`notebook_entries`** — user-managed instruction/reference store (user territory — doc loader never writes here); nullable `project` / `platform` columns attribute saved entries  
**`user_settings`** — per-user config and one-time migration flags  

`project` and `platform` are additive metadata fields. `MARM_PROJECT` can override working-directory project detection; `MARM_PLATFORM` can override client/platform detection. `marm_smart_recall` accepts optional filters for both fields, including `include_logs=True`, and consolidation scopes duplicate detection to the current attribution pair so project/client boundaries are not merged accidentally.

**`doc_index`** — system-managed doc dedup tracker (never touched by user tools)
```sql
source_file TEXT PRIMARY KEY, content_hash TEXT NOT NULL,
memory_id TEXT, indexed_at TEXT NOT NULL
```
SHA-256 hash of each `marm-docs/*.md` file. On server start: skip unchanged docs, re-index if hash changed or `memory_id` row missing (external deletion recovery). `memory_id` column added via idempotent migration for existing DBs.

**`compaction_staging`** — pending/staged/applied memory compaction candidates
```sql
id TEXT PRIMARY KEY, session_name TEXT NOT NULL,
source_memory_ids TEXT NOT NULL, preview TEXT NOT NULL,
suggested_summary TEXT, status TEXT NOT NULL DEFAULT 'pending_summary',
candidate_hash TEXT NOT NULL, source_updated_at_snapshot TEXT NOT NULL,
expires_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
reviewed_at TEXT, nudge_count INTEGER DEFAULT 0, last_nudged_at TEXT
```
Candidates are created by the compaction worker, summarized by the connected agent through `marm_compaction`, then applied through the write queue/direct `BEGIN IMMEDIATE` transaction path.

**`memories_fts`** — SQLite FTS5 virtual table for exact-term recall
```sql
content, content='memories', content_rowid='rowid'
```
Backfilled on startup for existing stores and kept in sync with `memories` through insert/update/delete triggers.

**`memory_chunks`** — sidecar embeddings for long memories
```sql
id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, chunk_index INTEGER NOT NULL,
chunk_text TEXT NOT NULL, embedding BLOB NOT NULL, created_at TEXT NOT NULL
```
Long memory content is split into chunk embeddings so recall can match body-specific sections without replacing the parent `memories.embedding` column. Short memories keep the original single-vector path. Chunk rows are deleted and rewritten when parent content changes.

**`session_summary_cache`** — flat cache for `marm_summary`
```sql
session_name TEXT PRIMARY KEY, summary_text TEXT NOT NULL,
entry_count INTEGER NOT NULL, dirty BOOLEAN DEFAULT TRUE, updated_at TEXT NOT NULL
```
Log writes and single-entry deletes mark the cache dirty. Whole-session deletes remove the cache row. `marm_summary` rebuilds from `log_entries` when dirty or entry counts mismatch, then applies the 1MB MCP response limiter.

---

## Core MCP Tool Suite (7 Tools)

Session init, doc loading, and refresh are fully automated — no `marm_start` or `marm_refresh` call needed from the AI. `ensure_marm_started()` + `maybe_auto_refresh()` are injected into every tool call via `_log_tool_call` (STDIO) and the MCP tool call tracker middleware (HTTP).

| Category | Tool | What It Does |
|----------|------|--------------|
| Memory | `marm_smart_recall` | FTS-first filter→semantic rerank recall with chunk-aware long-memory scoring. `search_all=True` for global. `include_logs=True` also searches log_entries. `detail=1/2/3` controls response depth. Response key: `results`. |
| Logging | `marm_log_entry` | Add structured log entry with auto-date. Routes to active session when `session_name` omitted. `Session:` / `Topic:` lines can switch or classify the active log session. |
| | `marm_log_show` | Display sessions/entries (filterable). |
| Delete | `marm_delete` | Unified delete. `type="log"` + optional `session_name` deletes entry or whole session. `type="notebook"` deletes notebook entry and removes from active state. |
| Reasoning | `marm_summary` | Cached session summary over `log_entries`, rebuilt through `session_summary_cache` when dirty and hard-limited to 1MB. |
| Notebook | `marm_notebook` | Unified notebook tool. `action="add"` saves entries, `action="use"` activates entries, `action="show"` lists saved entries, `action="status"` shows active entries, `action="clear"` clears active entries. Optional `session_name` (default `"main"`) scopes active state per agent — enables swarm-safe parallel notebook use. |
| Compaction | `marm_compaction` | Unified compaction workflow. `action="status"` checks readiness, `candidates` returns source clusters + prompt, `stage` submits summaries, `review` lists staged summaries, `apply` commits through write queue/direct transaction, `discard` rejects. |

### Graph Tool Surface (v2.16.0 planned unified path)

`marm-graph` standalone already exposes 5 AI tools. The pip unification plan adds those same 5 operation IDs to `marm-mcp-server`, growing the unified server from 7 core tools to 12 total tools without adding new graph concepts.

| Tool | What It Does |
|------|--------------|
| `marm_graph_index` | Index a repository, list indexed projects, or report index status. |
| `marm_code_lookup` | Search symbols, grep code, or read source by symbol/path through one routed graph lookup tool. |
| `marm_graph_trace` | Trace calls/data flow around a function or symbol. |
| `marm_graph_architecture` | Return codebase architecture overview and graph schema context. |
| `marm_graph_impact` | Estimate blast radius for code changes from git diff or symbol context. |

Graph startup is lazy by design in the unified pip plan: no graph process, network check, or binary download occurs during normal `marm-mcp-server` boot. The first `marm_graph_*` call starts the backend and may take a minute or two if the ~269MB engine binary is not cached. Core memory/logging continues to work if graph is disabled or unavailable.

**Removed from MCP discovery:** `marm_start`, `marm_refresh`, `marm_current_context`, `marm_system_info`, `marm_reload_docs`, `marm_context_bridge`, `marm_context_log`, `marm_log_session`, `marm_log_delete`, `marm_notebook_delete`, `marm_notebook_add`, `marm_notebook_use`, `marm_notebook_show`, `marm_notebook_clear`, `marm_notebook_status`, legacy split compaction tools (`marm_get_compaction_candidates`, `marm_stage_compaction_summaries`, `marm_get_staged_summaries`, `marm_apply_compaction`). `/health` endpoint covers system status checks.

---

## Security — Sanitization

Content sanitization uses deterministic string scanning (no regex backtracking):

- `_strip_script_tags()` — pure `str.find()` walker in both `core/memory.py` and `marm-dashboard/db.py`. Handles valid close, malformed close (`</script foo>`), broken close (`< /script>`), and unterminated open tags.
- `sanitize_content()` — strips scripts, blocks `javascript:` protocols, strips `on*` event handlers, HTML-escapes remainder. Applied to all memory writes.
- Dashboard notebook uses `_strip_scripts()` — same script stripping, stores raw (not HTML-escaped) for display parity.
- CodeQL alerts resolved in v2.5.5 — no polynomial regex patterns remain on content paths.

---

## Rate Limiting (v2.9.x)

Managed in `marm_mcp_server/core/rate_limiter.py` + `middleware/rate_limiting.py`.

All three tiers (default/memory_heavy/search) share one configurable limit set via `IPRateLimiter.configure()`. `/mcp` traffic (all MCP tool calls) routes to the `default` bucket. RPM=0 disables limiting entirely.

**CLI startup presets** (`server.py` → `apply_runtime_preset()`):

| Flag | Rate Limit | Write Queue | Use When |
|------|------------|-------------|----------|
| *(none)* | 80 RPM | env default (`WRITE_QUEUE_ENABLED=1`) | Normal local use |
| `--swarm` | 200 RPM | enabled | Shared HTTP multi-agent server |
| `--swarm-max` | 600 RPM | enabled | Heavier private swarm |
| `--trusted` | disabled (0) | enabled | Trusted private deployments |
| `--rate-limit-rpm N` | N RPM | unchanged | Custom override; 0 disables |

Precedence: `--trusted` > `--rate-limit-rpm` > `--swarm-max` > `--swarm`.

Compaction trigger count is runtime-adjusted with presets: default/custom mode uses 5 writes per session, swarm/swarm-max/trusted use 20 writes per session.

**Env-backed defaults** (settings.py):
```
MARM_RATE_LIMIT_RPM=80     # default RPM; overridden at runtime by CLI presets
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_BLOCK_SECONDS=30
HYBRID_SEARCH_TEXT_WEIGHT=0.35
TEMPORAL_WEIGHT=0.1
TEMPORAL_HALF_LIFE_DAYS=30
```

Recall-ranking settings are clamped safely at settings load. Out-of-range values warn to `stderr` so STDIO JSON-RPC stays clean.

**IP spoofing fix (v2.6.0):** `X-Forwarded-For` and `X-Real-IP` only trusted when the direct TCP connection is from `127.0.0.1`/`::1`. Remote callers cannot spoof loopback to bypass rate limiting or auth.

---

## Code Layout (Source of Truth)

**MCP Server** — `marm-mcp-server/marm_mcp_server/`

| Folder | Owns |
|--------|------|
| `core/` | DB, models, rate limiter, response limiter, events, write queue, FTS/hybrid recall primitives, chunk-aware scoring, consolidation/compaction primitives |
| `endpoints/` | HTTP/MCP route handlers grouped by domain |
| `middleware/` | Rate limiting middleware |
| `services/` | Workflow services shared by endpoints/STDIO: automation, documentation, notebook, recall, summary, compaction apply, compaction summarize |
| `utils/` | Shared helpers incl. `security.py` (key generation) |
| `config/` | Settings (port, DB path, pool size, etc.) |

**Entry point:** `marm_mcp_server/server.py` — registers all routers, mounts FastAPI-MCP  
**Package entry:** `marm_mcp_server/__main__.py` — `python -m marm_mcp_server`

**Dashboard** — `marm-dashboard/marm_dashboard/`

| File | Owns |
|------|------|
| `server.py` | FastAPI app, all `/api/*` routes |
| `db.py` | Direct SQLite access — memories, sessions, logs, notebook |
| `auth.py` | `is_valid_key()` — loopback passthrough or bearer check |
| `config.py` | `MARM_API_KEY` from env then `~/.marm/.env` fallback |
| `static/` | Frontend HTML/CSS/JS, cache-busted assets |

**Graph** — `marm-graph/marm_graph/`

| Folder | Owns |
|--------|------|
| `core/` | `CbmClient` stdio subprocess wrapper, typed models, tool router, singleton deps |
| `endpoints/` | 5 AI graph endpoints plus UI-only REST endpoints for MARMIS |
| `middleware/` | Bearer auth for non-loopback standalone graph HTTP |
| `config/` | Host/port/API key, store dir, binary path, timeout, response limit |

**Graph entry point:** `marm_graph/server.py` — standalone FastAPI/FastApiMCP app with a strict 5-tool whitelist  
**Graph package entry:** `marm_graph/__main__.py` — `python -m marm_graph`  
**Graph STDIO entry:** `marm_graph/server_stdio.py`

**Graph/index planning docs**
- `docs/current/graph-index/packaging-integration.md` — one-system packaging direction and non-negotiables
- `docs/pip-packaging-unification.md` — v2.16.0 pip plan: graph dependency, lazy supervisor, 12-tool unified server
- `docs/docker-packaging-unification.md` — v2.16.0 Docker plan: all-in-one image with dashboard mounted and graph baked/lazy
- `docs/current/graph-index/graph/` — marm-graph spec, protocol proof, research notes
- `docs/current/graph-index/index/` — concept-graph/memory-index specs folded into marm-mcp, not a sibling package

---

## Write Queue (v2.9.x)

Serialized write layer for multi-agent / swarm workflows. Default-on in v2.9.x for local cushion; enabled automatically by `--swarm`, `--swarm-max`, and `--trusted` startup presets.

| Env Var | Default | Meaning |
|---------|---------|---------|
| `WRITE_QUEUE_ENABLED` | `1` | Set to `0` only for direct-write debugging/tests |
| `MAX_QUEUE_SIZE` | `100` | Max queued writes before callers block |

**How it works:**
```
Agents → memory write → store_memory_queued() → asyncio.Queue → single worker → SQLite
```
- `core/write_queue.py` — `WriteQueue` class: `start()` / `stop()` / `put()` / `put_callable()`. Worker resolves caller futures; errors propagate back to caller.
- `memory.store_memory_queued()` — routes through queue when enabled, falls back to direct `store_memory()` when disabled. Queue starts lazily on first write; subsequent writes skip startup check.
- Compaction apply also uses `put_callable()` when the queue is available, keeping summary/source-row mutations serialized with normal memory writes.
- HTTP lifespan: queue started at `server.py` startup, drained and stopped at shutdown.

---

### Memory Core Split

`core/memory.py` is now a facade, not the owner of every memory behavior. The extracted modules are:

- `memory_db.py` — connection pool, schema setup, FTS triggers, migration helpers, compaction state helpers
- `memory_utils.py` — sanitization, query helpers, text chunking, and async chunk writes
- `memory_scoring.py` — FTS candidate fetch, semantic row scoring, chunk-aware scoring, dedup-by-parent with `MAX(similarity)`
- `memory_ops.py` — store, update, delete, recall, and queued memory operations
- `memory.py` — `MARMMemory` facade, encoder lifecycle, and compatibility wiring

## Recall Stack (current)

`marm_smart_recall` is no longer plain semantic search. The current recall stack is layered:

1. FTS5 BM25 filter for keys, commands, filenames, and error text
2. Semantic rerank over the bounded FTS candidate set using MiniLM embeddings
3. Bounded semantic fallback when FTS coverage is weak, malformed, or unscoreable
4. Chunk-aware scoring for long memories through `memory_chunks`, deduplicated by parent memory before ranking
5. Conservative temporal weighting so fresher memories get a modest boost when scores are otherwise close
6. Layered retrieval depth via `detail=1/2/3`
7. MCP response limiting for 1MB compliance

Current ranking controls:

| Setting | Default | Purpose |
|---------|---------|---------|
| `FTS_CANDIDATE_LIMIT` | `50` | Max FTS candidate IDs fetched before semantic rerank |
| `HYBRID_SEARCH_TEXT_WEIGHT` | `0.35` | Legacy weighted-fusion knob still present in settings; no longer used by the primary recall path |
| `TEMPORAL_WEIGHT` | `0.1` | Conservative recency bias in final ranking |
| `TEMPORAL_HALF_LIFE_DAYS` | `30` | Decay rate for temporal weighting |
| `RECALL_SCAN_LIMIT` | `10000` | Bounded semantic scan ceiling for fallback lane |

`recall_scan_truncated` only has meaning on the semantic fallback lane. The primary filter→rerank path scores a bounded FTS candidate set and reports non-truncated metadata.
- STDIO: queue starts lazily on first queued memory write. `put()` awaits the write future before returning — queue is empty between tool calls, so no drain-on-shutdown is needed for serial STDIO transport.
- Reads are always concurrent — only writes are serialized.

---

## Consolidation + Compaction (v2.9.x)

**Layer 1 — Content hash dedup:** `core/consolidation.py` computes SHA-256 over normalized content and re-checks exact content equality under `BEGIN IMMEDIATE` before insert. Hash collisions store as new rows rather than false dedup.

**Layer 2 — Write-time semantic merge:** when `CONSOLIDATION_ENABLED=1`, new writes precompute embeddings, search for a near-duplicate in the same session, and merge into the existing memory when similarity is at or above `CONSOLIDATION_THRESHOLD` (default `0.92`). If the encoder is unavailable, writes continue normally.

**Layer 3 — Compaction worker:** when `COMPACTION_ENABLED=1`, per-session write counts trigger cluster detection after `COMPACTION_TRIGGER_COUNT` writes. Candidates are staged in `compaction_staging`; agents are nudged through MCP/STDIO/HTTP injection to call `marm_compaction`; apply writes summary rows and marks sources as compacted. Auto-apply is disabled by default (`COMPACTION_AUTO_APPLY_ENABLED=0`) until explicitly enabled.

Primary modules:
- `core/consolidation.py` — content hash + semantic duplicate helpers
- `core/compaction.py` — cluster detection, staging, stale cleanup, nudge claim logic
- `services/compaction_apply.py` — atomic staged-summary apply transaction
- `endpoints/compaction.py` — unified MCP/HTTP compaction tool wrapper

---

## Key Architectural Rules

- Session state lives in SQLite — never in endpoint functions
- New MCP endpoints: add Pydantic model to `core/models.py`, implement in `endpoints/`, register router in `server.py`
- All large-response endpoints must wrap with `MCPResponseLimiter` from `core/response_limiter.py`
- mypy scoped to `core/` only — `endpoints/` excluded until coverage is solid
- `python -m marm_mcp_server` is the single run command — root-level duplicate `server.py` pending removal
- Dashboard edits are direct SQLite writes — they bypass MCP tool events intentionally
- Notebook is user territory — `doc_index` and `documentation.py` never write to `notebook_entries`
- `_log_tool_call` (STDIO) wraps every tool: calls `ensure_marm_started()` before and `maybe_auto_refresh()` after — no manual init required
- DB schema changes: always `CREATE TABLE IF NOT EXISTS` + idempotent `ALTER TABLE ADD COLUMN` via `PRAGMA table_info` check — never drop or recreate
- Notebook active state is session-scoped (`active_notebook_entries_by_session` dict keyed by `session_name`) — multiple agents can hold different active sets simultaneously
- Write queue is the default safety path. Only disable for targeted direct-write debugging/tests.
- Public MCP compaction surface is unified behind `marm_compaction`; do not re-add split user-facing compaction tools.
- Keep large endpoint/transport files thin: extract self-contained business logic into `services/` only when there is a real workflow boundary, not for line count alone.
- Default product direction is one system externally, modular internally. Do not add a required new package, port, daemon, image, database, or user-managed process without an explicit architecture decision.
- Graph/index failures must degrade cleanly and must never block core memory, logging, notebook, recall, or server startup.
- Keep graph dependency/version changes reviewed. `marm-graph` pins `codebase-memory-mcp==0.8.1`; any bump changes a third-party binary trust boundary and schema contract.
