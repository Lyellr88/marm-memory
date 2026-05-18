# MARM MCP - Current Issues & Priorities

**Last Updated:** 2026-05-16

---

## ✅ Resolved

### 1. Pip Install Broken (v2.2.6) — FIXED

**Was:** `ImportError: cannot import name 'create_server'` + `ModuleNotFoundError: No module named 'middleware'`

**Fix:** Converted all absolute imports to relative imports across 16 files in `marm_mcp_server/`. Added `create_server()` and `main()` functions to `marm_mcp_server/server.py`. Added `__main__.py` so `python -m marm_mcp_server` works.

**Pending:** Bump to v2.2.7 and republish to PyPI.

---

## 🐛 Active Bugs

### 2. `marm_log_session` Not Switching Sessions

**Symptom:** Calling `marm_log_session` to create/switch a named session, then immediately calling `marm_log_entry` — entries land in `main` instead of the named session.

**Impact:** Cross-project organization breaks. `/summary: [session-name]` returns empty. All entries pile up in `main`.

**Root Cause:** Session switch in `marm_log_session` is not persisting the active session state before `marm_log_entry` fires. Needs investigation in the session management logic.

**Fix Required:** Investigate session state persistence in `marm_log_session` endpoint — ensure active session is set before returning success response.

---

### 3. Rate Limiter Too Aggressive — No Retry Logic

**Symptom:** `marm_smart_recall` (and other tools) return HTTP 429 after hitting the 20 req/60s limit, then block the client for **600 seconds** (10 minutes). fastapi-mcp surfaces this as a hard exception with no retry.

```
Exception: Error calling marm_smart_recall. Status code: 429.
Response: {"error":"Rate limit exceeded","message":"Rate limit exceeded: 20 requests per 60s. Blocked for 600s."}
```

**Impact:** A single burst of tool calls (common when Claude runs multiple MCP calls in quick succession at session start) trips the limit and locks out the client for 10 minutes. Server is unreachable until the block expires.

**Root Cause:** Two separate issues:
1. **Block duration too long** — 600s penalty for hitting a soft limit is excessive for a local server where the client is always `127.0.0.1`
2. **No retry / backoff on the server side** — server returns 429 immediately with no queue, jitter, or graceful retry guidance

**Fix Options to Explore:**
- Raise the rate limit threshold for `127.0.0.1` (localhost should be trusted)
- Reduce block duration from 600s to something reasonable (e.g. 30–60s)
- Add `Retry-After` header with exact seconds so MCP clients can auto-retry
- Investigate if fastapi-mcp supports 429 retry handling natively

**Status:** Needs investigation in `marm_mcp_server/middleware/rate_limiting.py`.

---

### 4. `marm_notebook_delete` Leaves Deleted Entry Active

**Symptom:** During a VS Code MCP smoke test, `marm_notebook_add` created `codex_mcp_smoke_test_temp`, `marm_notebook_use` activated it, and `marm_notebook_delete` returned success for that same entry. A follow-up `marm_notebook_status` still reported the deleted entry as active until `marm_notebook_clear` was called.

**Impact:** Deleted notebook entries can remain in the active instruction list. An AI client may continue treating deleted instructions as active, causing stale or unexpected behavior until the active list is cleared manually.

**Repro:**
1. Call `marm_notebook_add(name="codex_mcp_smoke_test_temp", data="temporary test entry")`
2. Call `marm_notebook_use(names="codex_mcp_smoke_test_temp")`
3. Call `marm_notebook_delete(name="codex_mcp_smoke_test_temp")`
4. Call `marm_notebook_status`
5. Observe the deleted entry still listed as active

**Expected:** `marm_notebook_delete` should remove the entry from both persistent notebook storage and the active notebook list.

**Observed:** Delete succeeds, but active state still contains the deleted entry until `marm_notebook_clear` runs.

**Fix Required:** Update notebook delete handling so deleting an entry also removes that name from the active notebook state. Add regression coverage for add -> use -> delete -> status.

**Status:** Needs investigation in notebook state management.

---

### 5. Windows asyncio `ConnectionResetError` Noise on MCP Disconnect

**Symptom:** During VS Code MCP testing on Windows with Python 3.14, the server logged repeated asyncio cleanup exceptions after successful MCP requests:

```
Exception in callback _ProactorBasePipeTransport._call_connection_lost()
ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host
```

The surrounding access logs still showed successful MCP responses, including `POST /mcp` returning `200 OK` / `202 Accepted`, `DELETE /mcp` returning `200 OK`, and `GET /mcp` returning `200 OK`.

**Impact:** Appears to be noisy disconnect cleanup rather than a functional tool failure. It can still confuse users during local testing because the traceback looks severe even when MCP calls succeed.

**Likely Cause:** Windows `ProactorEventLoop` cleanup path is calling `socket.shutdown()` after the MCP client has already closed or reset the local connection. This may be triggered by VS Code reloads, MCP stream/session teardown, or normal client disconnect behavior. Python 3.14 may expose this more visibly than older runtimes.

**Fix Options to Explore:**
- Reproduce on Python 3.12/3.13 vs 3.14 to see if this is runtime-specific
- Check whether the ASGI server/transport has a known Windows Proactor disconnect handling issue
- Add graceful handling or log filtering for expected local disconnect resets
- Document this as benign local Windows noise if requests continue returning success

**Status:** Needs investigation. Treat as non-blocking unless tool calls fail or the server process exits.

---

### 6. Documentation Auto-Loaded at Server Startup (Database Bloat)

**Symptom:** MARM documentation (Protocol, Handbook, etc.) is automatically loaded into the server's SQLite database (`notebook_entries` and `memories`) immediately upon server startup, regardless of whether a session has been started.

**Impact:**
- **Server Resources:** Wastes memory and disk space on the server before it's needed.
- **Protocol Violation:** Contrary to the intended design where documentation should only be loaded/available after `marm_start` is explicitly called.
- **Session Confusion:** Documentation appears in `marm_system_info` even in a "cold" state.

**Root Cause:** The `lifespan` context manager in `marm_mcp_server/server.py` calls `await load_marm_documentation()` during the startup phase.

**Fix Required:** 
1. Remove `await load_marm_documentation()` from the `lifespan` startup logic in `marm_mcp_server/server.py`.
2. Integrate documentation loading into the `marm_start` endpoint in `marm_mcp_server/endpoints/session.py`. 
3. Ensure `marm_reload_docs` in `marm_mcp_server/endpoints/system.py` is also functional and points to the correct service.

**Status:** Identified. Needs implementation to align with session-based context injection.

---

## 📋 Planned Improvements

### Documentation Consolidation Pass (Install Docs + MCP Handbook)

**Problem:** Core docs are getting too long and harder to scan quickly during onboarding and setup.

**Scope:** `docs/INSTALL-DOCKER.md`, `docs/INSTALL-WINDOWS.md`, `docs/INSTALL-LINUX.md`, and `MCP-HANDBOOK.md`.

**Goal:** Keep quick-start paths short and practical, move deep reference material into clearly linked sections, and remove duplicated guidance across install docs.

**Success Criteria:**
- Install docs focus on actionable setup + troubleshooting.
- Repeated transport/auth/client examples are centralized where possible.
- MCP handbook keeps depth, but trims redundant examples and repeated explanations.

**Status:** Planned docs cleanup after tests/CI stabilization.

---

### Token Optimization — Reduce Context Bloat

**Problem:** MARM loads full markdown documentation files as token context on every session start, eating tokens like Pac-Man at scale.

**Original idea:** Cache prompts to API/cloud to avoid re-injecting protocol content every call.
**Status:** Not viable — MARM is an MCP server, not running its own LLM. Can't use provider-level prompt caching directly.

**Alternative approaches to explore:**
- Local doc DB — store docs in SQLite, MCP agent queries on-demand instead of bulk-loading at startup
- Lazy loading — only inject docs when a relevant tool is called, not on every session start
- Compressed summaries — replace full markdown files with condensed reference versions in the startup load

---

### Directory-Based Memory Architecture (Per-Project Isolation with Cross-Reference)

**Problem:** MARM currently uses a single flat SQLite database as one large memory pool. All sessions and entries from all projects — MarketWise, computer-dx, MARM itself, anything else — pile into the same pool. At scale with multiple builds and multiple AI agents logging simultaneously, this pool will overflow, become noisy, and make meaningful recall increasingly unreliable.

**The Vision:** Mirror how CLI agents like Claude Code handle project context — each working directory gets its own memory partition. Similar to how `.claude/` is created per directory, MARM would maintain a per-project SQLite database scoped to that directory.

**How It Works:**
- Each project directory gets its own lightweight SQLite DB (e.g., `~/.marm/projects/computer-dx/memory.db`)
- A global index tracks all known project databases and their locations
- The active project DB is the primary search target for `marm_smart_recall`
- Cross-project recall is opt-in — when a query doesn't get strong matches locally, MARM can pull and reference other project DBs via the index
- `main` stays as the global/general memory pool for non-project-specific entries

**Why SQLite (not Postgres):**
- Lightweight — keeps pip install and Docker image size low
- No server process required — each project DB is just a file
- Still packs full semantic search capability with embeddings
- Easy to copy, backup, or share individual project memory files

**Proposed Structure:**
```
~/.marm/
├── memory.db              ← global/main pool (current behavior preserved)
├── index.json             ← registry of all known project DBs + directory paths
└── projects/
    ├── computer-dx/
    │   └── memory.db      ← scoped to C:\Users\lyell\Desktop\computer-dx
    ├── marketwise/
    │   └── memory.db
    └── marm-systems/
        └── memory.db
```

**Cross-Reference Flow:**
1. Agent logs entry → goes to active project DB
2. `marm_smart_recall` searches active project DB first
3. On weak match, consults index → pulls relevant entries from other project DBs
4. Returns results with source project labeled so agent knows context origin

**Status:** Architectural design phase — needs spec before implementation.

---

### MCP Automation — Auto-Checkpoint After N Messages

**Concept:** Instead of requiring the AI to manually log every insight, MARM tracks message count per session and auto-triggers a semantic summary checkpoint after a threshold (e.g. every 5 messages). Non-aggressive — respects cooldown periods and is opt-in.

**Core Idea:**
- Add `message_count`, `last_auto_log`, `auto_log_enabled`, and `auto_log_threshold` columns to sessions table
- New `marm_auto_checkpoint` tool — checks threshold + cooldown before firing, then runs a semantic summary and logs it automatically
- Modify `marm_refresh` to increment message counter and optionally trigger a checkpoint when `auto_checkpoint=true`
- New `marm_automation_config` tool — lets the AI (or user) configure enabled/threshold/cooldown per session

**Design Principles:**
- Opt-in only — disabled by default, AI must explicitly enable it
- Cooldown enforced — won't auto-log more than once per 10 minutes regardless of message count
- Non-invasive — doesn't fire on lifecycle events like hooks, only on explicit `marm_refresh` calls
- Persisted in DB — state survives across tool calls, no in-memory session dependency

**Rough Flow:**
```
marm_start → marm_automation_config (enabled=true, threshold=5)
[5+ messages later]
marm_refresh (auto_checkpoint=true) → semantic summary logged → counter resets
```

**Reference:** Inspired by claude-mem's hook architecture — https://github.com/thedotmack/claude-mem

**Status:** Concept phase — needs spec and DB schema design before implementation.

---

### Combine `marm_log_delete` + `marm_notebook_delete` → `marm_delete`

**Problem:** Two separate delete tools doing the same job on different tables. Adds noise to the MCP tool list.

**Fix:** Single `marm_delete` tool with a `type` flag:
```
marm_delete(type="log"|"notebook", target, session_name=None)
```
- `type="log"` + `session_name` → delete specific log entry by id or topic
- `type="log"` (no session_name) → delete entire session + all its entries
- `type="notebook"` → delete notebook entry by name

**Note:** Both existing tools work correctly — this is a consolidation, not a bug fix. Check how fastapi-mcp handles DELETE with a body before implementing.

**Status:** Ready to implement when we do the tool cleanup pass.

---

### Retire `marm_context_bridge` → Add `include_logs` to `marm_smart_recall`

**Problem:** `marm_context_bridge` is almost entirely redundant with `marm_smart_recall`. The only unique thing it does is also search `log_entries` via text `LIKE` matching alongside the memory semantic search. The formatted markdown output and "Recommended Approach" boilerplate are things the AI can do itself.

**Fix:** Add `include_logs=False` parameter to `marm_smart_recall`. When `True`, also queries `log_entries` and merges results. Then retire `marm_context_bridge` entirely.

**Status:** Ready to implement when we do the tool cleanup pass.

---

### Tool List Trim — Remove Bloat, Automate Internals

**Goal:** Cut tools that don't need to be AI-facing. Less tools = faster MCP discovery, less rate limit pressure, cleaner AI decision-making.

**`marm_start` — automate on server activation**
- Currently requires the AI to call it manually at session start
- Fix: server runs `marm_start` logic automatically on startup, no tool call needed
- Remove from MCP tool list

**`marm_reload_docs` — remove, replace with auto-refresh**
- Currently a manual tool to reload documentation into context
- Fix: server auto-reloads docs after X tool calls internally, no AI involvement needed
- Remove from MCP tool list

**`marm_refresh` — remove, replace with auto-refresh**
- Currently called by AI every N turns to recenter context
- Fix: tie into the same auto-refresh counter as reload_docs — server handles it after X tool calls
- Remove from MCP tool list

**`marm_current_context` — remove, internalize**
- Currently exposes server context state as a callable tool
- Fix: server tracks and injects current context internally wherever it's needed (already used as a background call in `marm_log_session`)
- Remove from MCP tool list

**`marm_system_info` — remove, use `/health` curl**
- Already have a `/health` HTTP endpoint that covers system status
- MCP tool is redundant overhead
- Fix: document `curl http://localhost:8001/health` in the handbook as the replacement
- Remove from MCP tool list

**Net result:** ~5 tools removed from the MCP list. Server becomes self-managing — AI only calls tools that actually need AI judgment.

**Status:** Needs implementation plan before touching — server-side automation logic required first.

---

### Remove Legacy Chatbot Code & Docs

**Problem:** The repo still carries the full webchat codebase, archived chatbot docs, and related tooling. MARM's focus is the MCP server — the chatbot is retired and this dead weight clutters the repo.

**What to remove:**
- `docs/archived/webchat/` — full webchat source (JS, CSS, tests, server)
- `docs/archived/marm-new-ui/` — React UI prototype
- `docs/archived/marm-cli/` — old CLI prototype
- `docs/archived/Upgrades or Edits-chatbot/` — chatbot analysis docs
- `docs/archived/marm-mcp-server(old)/` — old server files
- Any remaining chatbot references in core docs

**Keep:** `docs/archived/` planning docs, market research, onboarding files — those are still useful reference.

**Status:** Low risk, do as a dedicated cleanup commit.

---

### Test Suite Overhaul — Stale, Weak, and Live-Server Dependent

**Problem:** The entire `tests/` suite is broken and misaligned with the current API. Tests were written against an older version and never updated.

**Specific failures identified:**
- `marm_notebook_add` called with `memory` + `context_type` — actual model takes `name` + `data`
- `marm_smart_recall` response read as `data["memories"]` — actual response key is `data["results"]`
- `marm_summary` called as POST with body — actual endpoint is GET with query params
- `marm_session_status` and `marm_session_clear` called — these endpoints do not exist
- All tests hit `http://localhost:8001` directly — server must already be running, can't run cold

**Broader issue:** The test philosophy is shallow — mostly asserting `status_code == 200` and response key existence. No adversarial testing, no edge cases, no verification that the actual data returned is correct.

**What good tests look like for MARM:**
- Call an endpoint with bad input and assert it fails correctly
- Write a memory, recall it, assert the content matches
- Test session isolation — data from session A must not appear in session B recall
- Test MCP size limiting — response over 1MB must be truncated, not crash
- Test rate limiter behavior — 21st request should return 429

**Tests to add after root-files cleanup (root-files-cleanup.md):**
- `python -m marm_mcp_server` starts and `/health` returns 200
- Docker build completes and container `/health` returns 200
- `python3 -c "import marm_mcp_server"` succeeds (covers the install.sh import check)

**Fix Required:**
1. Rewrite all tests to match current API signatures and response shapes
2. Add a test server fixture so tests can spin up the server themselves (no manual start needed)
3. Replace shallow status checks with deep assertions on actual response content
4. Add adversarial/edge case coverage

**Status:** High priority — a broken test suite provides false confidence. Needs dedicated session.

---

### Return Type Annotations — Expand to Full Codebase

**Current state:** mypy is configured with `disallow_untyped_defs = true` in `pyproject.toml` but endpoint functions have no return type annotations. Running mypy against `endpoints/` would generate a wall of errors for minimal safety gain since endpoints return plain dicts.

**Decision:** Scope mypy to `core/` only for now (`memory.py`, `models.py`, `response_limiter.py`) where type relationships actually matter.

**Future consideration:** Expand mypy coverage to `endpoints/` and `middleware/` once test suite is solid and the codebase is stable. FastAPI supports typed response models (returning a Pydantic model instead of a raw dict) which would make full annotation meaningful rather than just noise.

**Status:** Parked — revisit after test suite overhaul.

---

### Remove Duplicate Root Files — Single Source of Truth

**Problem:** The `marm-mcp-server/` root contains duplicate copies of `server.py`, `middleware/`, `endpoints/`, `services/`, `core/`, and `utils/` alongside the `marm_mcp_server/` package subfolder. These two copies drift apart over time — exactly what caused the v2.2.6 pip install bug.

**Fix:** Delete the root-level duplicates. Use `python -m marm_mcp_server` as the single way to run the server. One source of truth, no sync issues.

**Impact:** `python server.py` stops working — any docs or scripts referencing it need updating to `python -m marm_mcp_server`.

**Status:** Low priority — straightforward cleanup, no logic changes required.

---
