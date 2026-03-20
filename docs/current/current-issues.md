# MARM MCP - Current Issues & Priorities

**Last Updated:** 2026-03-20

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

## 📋 Planned Improvements

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

### Remove Duplicate Root Files — Single Source of Truth

**Problem:** The `marm-mcp-server/` root contains duplicate copies of `server.py`, `middleware/`, `endpoints/`, `services/`, `core/`, and `utils/` alongside the `marm_mcp_server/` package subfolder. These two copies drift apart over time — exactly what caused the v2.2.6 pip install bug.

**Fix:** Delete the root-level duplicates. Use `python -m marm_mcp_server` as the single way to run the server. One source of truth, no sync issues.

**Impact:** `python server.py` stops working — any docs or scripts referencing it need updating to `python -m marm_mcp_server`.

**Status:** Low priority — straightforward cleanup, no logic changes required.

---
