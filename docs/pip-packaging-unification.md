# Pip Packaging Unification (marm-mcp-server + marm-graph)

**Status**: Planned
**Version Target**: v2.16.0 (MINOR — new install capability, no breaking change to the existing 7 tools/params)
**Priority**: High
**Parent doc**: `docs/current/graph-index/packaging-integration.md` — this spec answers that doc's pip-direction open question and non-negotiables checklist. Docker unification is a separate spec (not covered here).

---

## Problem

Today `marm-mcp-server` (port 8001, memory) and `marm-graph` (port 8003, code-structure graph) are separate pip packages a user must install and run independently to get the full MARM experience. `packaging-integration.md` sets the target: "MARM should feel like one system." A normal user should not have to know a second service exists, choose whether to start it, or reach it on its own port. Dashboard is explicitly **out of scope** here — it stays a separate, separately-installed package for pip users (decided this session; Docker is where dashboard gets folded in, in the follow-up spec).

## Solution Overview

`pip install marm-mcp-server` becomes the only command a memory+graph user needs. `marm-graph` is added as a normal pinned dependency (it keeps its own package, tests, and release cadence — no source merge). `marm-mcp-server` gains a small supervisor that owns the `codebase-memory-mcp` child process the same way `marm-graph`'s own `CbmClient` does today, and exposes the 5 existing `marm_graph_*` tools directly on its own FastAPI app/port — no second HTTP service, no port 8003 in the default path. If the graph backend fails to start (no network for the first-run binary download, disk full, schema drift, etc.), `marm-mcp-server` still boots and all 7 core memory tools work exactly as they do today; only the 5 graph tools degrade to a clean error response.

---

## Architecture Decisions

| Decision | Chosen Direction | User Impact |
|---|---|---|
| Install/runtime shape | One package: `pip install marm-mcp-server`. Graph is **bundled by default**, not an extra. | One command gets memory + graph. First use of a graph tool may trigger a one-time ~269MB binary download — must be visibly logged, not silent. |
| Package structure | `marm-graph` stays a **separate PyPI package** with its own `pyproject.toml`/tests/release cadence; `marm-mcp-server` adds it as a normal pinned dependency. | No behavior change to marm-graph's own standalone install (advanced/manual users can still `pip install marm-graph` directly, or run it via Docker in the separate-images path). |
| Service boundary | **Internal child process**, no separate user-facing port. `marm-mcp-server` supervises the `codebase-memory-mcp` binary in-process (via `marm_graph`'s `CbmClient`, imported as a library) and calls `marm_graph.core.tool_router` functions directly. `marm-graph`'s own FastAPI/FastApiMCP app (`server.py`) and HTTP auth layer are **not used** in this path at all. | Users never see port 8003 unless they explicitly run `marm-graph` standalone. |
| Failure behavior | **Degraded mode, never fatal.** If the graph backend fails to start for any reason, `marm-mcp-server` logs a warning and continues; core memory tools are unaffected. Graph tools return `{"status": "error", "message": "..."}` until the backend recovers (not attempted automatically — same posture as any other backend-unavailable response in this codebase). | A broken/unavailable graph engine can never block memory, logging, notebook, or recall. |
| Tool surface | No new tool *concepts*. But `marm-mcp-server`'s `tools/list` grows from **7 to 12** (the same 5 `marm_graph_*` tools that already exist in `marm-graph`, now also registered on the unified server). This is a direct, unavoidable consequence of "bundled by default" — flagged explicitly since it changes what every agent sees in tool discovery, even for memory-only users. | Agents connecting to `marm-mcp-server` will see 12 tools instead of 7 after upgrade, regardless of whether they ever use graph. |
| Data ownership | No new database. Graph continues to own `~/.marm/graph` exactly as it does standalone; memory continues to own `~/.marm/marm_memory.db`. | No migration, no schema change to existing data. |
| Startup timing | **Lazy by design**: the graph child process is only spawned (and the binary download only triggered) on the **first** `marm_graph_*` tool call, not at `marm-mcp-server` boot. | Memory-only users get instant, network-free startup identical to today. Graph users pay the one-time setup cost only when they actually use graph. First graph use may take a minute or two if the engine binary is not cached yet. |

---

## UX Flow

1. User runs `pip install marm-mcp-server` (or upgrades). No `[graph]` extra needed — this is the only install step.
2. User starts the server as today: `marm-mcp-server`. Startup logs look identical to today's 7-tool boot; no graph-related network activity happens yet (lazy start).
3. User (or their agent) calls any `marm_graph_*` tool for the first time.
   - If the `codebase-memory-mcp` binary isn't cached yet, the supervisor logs an explicit INFO line before spawning: e.g. `MARM: downloading graph engine (~269MB, one-time)...` — this must not be buried at DEBUG the way the child's own stderr chatter already is (see Edge Cases).
   - Binary downloads, verifies, spawns, handshakes — same sequence `marm-graph` already performs standalone.
   - The tool call proceeds normally once the backend is ready.
4. If step 3 fails (no network, disk full, schema drift against the pinned `codebase-memory-mcp` version): the calling tool returns `{"status": "error", "message": "graph backend unavailable: <reason>"}`. Every other tool (memory, notebook, logging, etc.) is completely unaffected — this is verified by a dedicated test (see Testing Checklist).
5. Advanced users who still want graph as an independent, network-reachable service can `pip install marm-graph` directly and run `marm-graph` — unchanged, standalone path untouched by this spec.

---

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `marm-graph/marm_graph/core/backend.py` | **Prerequisite refactor in marm-graph.** Extracts `AI_OPERATIONS`, `_EXPECTED_UPSTREAM_TOOLS`, `verify_and_start(client)`, and `check_schema(names)` out of `marm_graph/server.py` (currently private module-level functions coupled to the FastAPI app) into a framework-agnostic module. Both `marm_graph/server.py`'s own lifespan and marm-mcp-server's new supervisor call the same functions — no duplicated verification logic. |
| `marm-mcp-server/marm_mcp_server/core/graph_supervisor.py` | Owns one `marm_graph.core.cbm_client.CbmClient` instance for the lifetime of the process. Exposes `start()` (idempotent, lazy — called from the first graph tool invocation, not lifespan), `is_available() -> bool`, `get_client() -> CbmClient`, and the first-run download log line. Never raises; all failures are caught and logged, flipping `is_available()` to `False`. |
| `marm-mcp-server/marm_mcp_server/endpoints/graph.py` | The 5 `marm_graph_*` FastAPI routes. Each: checks `graph_supervisor.is_available()` (triggering lazy `start()` on first call), and either returns the clean error dict or calls the matching `marm_graph.core.tool_router.do_*` function via `asyncio.to_thread`, exactly like marm-graph's own `endpoints/graph_ai.py` does today. |

### Modified Files

| File | Change Summary |
|------|---------------|
| `marm-graph/marm_graph/server.py` | Replace the locally-defined `AI_OPERATIONS` / `_EXPECTED_UPSTREAM_TOOLS` / `_verify_backend` / `_check_schema` (current lines 28-84) with imports from the new `core/backend.py`. No behavior change to marm-graph's own standalone server — this is a pure relocation. PATCH version bump for marm-graph. |
| `marm-mcp-server/pyproject.toml` | Add `"marm-graph==0.1.0"` to `dependencies` (current list at lines 29-44, alongside `fastmcp`, `httpx`, etc.). Pinned exactly — a marm-graph bump is a reviewed change, matching marm-graph's own pinning philosophy for `codebase-memory-mcp`. |
| `marm-mcp-server/requirements.txt` | Add the same `marm-graph==0.1.0` pin as a temporary Docker/build mirror. Docker currently installs from `requirements.txt`, not `pyproject.toml`; without this mirror, the pip package would include graph while the Docker image silently would not. Do **not** refactor Docker dependency ownership in this pip spec — the Docker spec owns that larger cleanup. |
| `marm-mcp-server/marm_mcp_server/server.py` | (1) In `lifespan()` (lines 216-251): no eager supervisor start (lazy design — see Architecture Decisions), but register `graph_supervisor` shutdown in the existing shutdown block (after line 250, alongside `memory.stop_write_queue()`) so a running child process is cleaned up on server exit. (2) Add `from .endpoints.graph import router as graph_router` near the existing endpoint imports, and `app.include_router(graph_router)` alongside the existing block at lines 508-514. (3) No change needed to `mcp = FastApiMCP(app)` at line 517 — it has no `include_operations` whitelist today, so the new router's 5 operation_ids are automatically included in `tools/list`, same as the existing 7. |
| `marm-mcp-server/marm_mcp_server/config/settings.py` | Add `GRAPH_ENABLED = os.environ.get("GRAPH_ENABLED", "true").lower() != "false"` near the other `SERVER_*` settings (~line 100-108). Lets advanced users/CI explicitly disable graph without uninstalling the dependency — direct match for the parent doc's "optional capabilities by config" boundary. Default preserves "bundled by default." |
| `marm-mcp-server/README.md` | Quick-start section: state one install command covers memory + graph. Tool count reference updates from 7 to "7 core + 5 graph = 12" (or however the doc currently phrases tool count — read the current wording before editing, don't invent a section). |
| `MCP-HANDBOOK.md` (repo root) | Same tool-count and install-path updates as README, plus a short note under whatever section documents optional/degraded capabilities today, describing graph's degrade-to-error behavior. |

---

## Implementation Plan

### Insertion Points

**`marm-graph/marm_graph/server.py`**

1. **Extract backend verification** (lines 26-84: `AI_OPERATIONS`, `_EXPECTED_UPSTREAM_TOOLS`, `_verify_backend`, `_check_schema`)
   What: move these four names verbatim into the new `marm_graph/core/backend.py`, renaming `_verify_backend`→`verify_and_start` and `_check_schema`→`check_schema` (drop the leading underscore — they're now a public cross-package API).
   Context: `server.py`'s `lifespan()` (line 95) currently calls `_verify_backend()` directly; update the call site to `backend.verify_and_start(get_client())` after the import change. No other behavior differs.

**`marm-mcp-server/pyproject.toml`**

1. **Dependency addition** (dependencies list, lines 29-44)
   What: add `"marm-graph==0.1.0",` to the list.
   Context: sits alongside `"fastmcp>=3.2.0,<3.5.0",` at line 43 — same section, same style (marm-graph itself is exact-pinned by design, per its own pyproject comment about `codebase-memory-mcp`).

**`marm-mcp-server/requirements.txt`**

1. **Temporary Docker mirror** (dependency list)
   What: add `marm-graph==0.1.0` to match the `pyproject.toml` dependency.
   Context: this is not making `requirements.txt` canonical for pip packaging. It only prevents Docker drift while the Dockerfile still installs from `requirements.txt`. The follow-up Docker spec must decide whether Docker continues using this file or switches to installing the package metadata from `pyproject.toml`.

**`marm-mcp-server/marm_mcp_server/server.py`**

1. **Shutdown hook** (shutdown block, lines 247-251)
   What: add `graph_supervisor.stop()` (or `await`-wrapped equivalent if the supervisor's stop needs the event loop) after `await memory.stop_write_queue()` (line 250).
   Context: mirrors the existing pattern of cleaning up long-lived resources in the same block right before `track_usage("server_shutdown")` (line 251).

2. **Router registration** (include_router block, lines 508-514)
   What: add `app.include_router(graph_router)` after `app.include_router(compaction_router)` (line 514).
   Context: import `graph_router` from the new `endpoints/graph.py` alongside the other endpoint imports near the top of the file (co-locate with however `compaction_router` etc. are currently imported — read that import block before editing, don't guess the exact line).

**`marm-mcp-server/marm_mcp_server/config/settings.py`**

1. **New setting** (near `SERVER_HOST`/`SERVER_PORT`, lines 100-108)
   What: add `GRAPH_ENABLED` bool setting, default true, parsed the same defensive way `_safe_int` handles `SERVER_PORT`.
   Context: sits right after the existing `SERVER_VERSION = "2.15.2"` line (108) — same settings block, same style.

**New: `marm-mcp-server/marm_mcp_server/core/graph_supervisor.py`**

What: a singleton module (matching `marm-graph`'s own `core/deps.py` singleton pattern for `CbmClient`) exposing:
- `is_available() -> bool`
- `get_client() -> CbmClient` (lazily calls `start()` on first access if `GRAPH_ENABLED` and not yet started)
- Internally: catches every exception from `CbmClient.start()` / `backend.verify_and_start()` / `backend.check_schema()`, logs a warning, and leaves `is_available()` `False` — **never propagates**, matching the existing precedent at `marm-graph/marm_graph/server_stdio.py:126-128` (`get_client().start()` wrapped in try/except, warning not crash).
- The first-run download log line: before calling `client.start()` for the first time, check whether the binary is already cached (`codebase_memory_mcp._cli._bin_path(codebase_memory_mcp._cli._version()).exists()`, transitively available once `marm-graph`'s `codebase-memory-mcp==0.8.1` pin is installed) and if not, `logger.info` an explicit human-readable line before the download starts. This is independent of the child's own stderr stream (see Edge Cases — that stream is already routed to DEBUG).

**New: `marm-mcp-server/marm_mcp_server/endpoints/graph.py`**

What: 5 routes (`marm_graph_index`, `marm_code_lookup`, `marm_graph_trace`, `marm_graph_architecture`, `marm_graph_impact`), same request models imported directly from `marm_graph.core.models`, same `operation_id`s as marm-graph's own `endpoints/graph_ai.py` (so any existing agent prompts/docs referencing these tool names by ID keep working unchanged). Each route:
```
if not graph_supervisor.is_available():
    return {"status": "error", "message": "graph backend unavailable"}
return await asyncio.to_thread(R.do_index, graph_supervisor.get_client(), req)
```
(pattern repeated per tool, matching `marm_graph.core.tool_router`'s existing `do_*` signatures exactly — no changes needed inside `tool_router.py` itself).

---

## State & Data Flow

- The `CbmClient` instance lives inside `graph_supervisor` (module-level singleton), started lazily on first graph-tool call, matching `marm-graph`'s existing `core/deps.py` singleton pattern one level up.
- No new state crosses into SQLite. Graph's own storage (`~/.marm/graph`) is managed entirely inside the `codebase-memory-mcp` binary, unchanged.
- `GRAPH_ENABLED=false` short-circuits `graph_supervisor.get_client()` before any subprocess spawn attempt — the 5 tools stay registered (schema-stable) but always return the clean error dict.

---

## !! EDGE CASES & GOTCHAS -- READ BEFORE WRITING A SINGLE LINE OF CODE !!

- **marm-graph's standalone server fails fast on purpose — that behavior must NOT leak into marm-mcp-server.** `marm_graph/server.py`'s `_check_schema` raises `RuntimeError` on upstream schema drift, and `_refuse_insecure_bind` calls `SystemExit(2)` — both are correct for a standalone service, both would be catastrophic if allowed to crash `marm-mcp-server`'s entire boot over a graph-only problem. The supervisor must catch `RuntimeError` (schema drift) specifically; `_refuse_insecure_bind`-equivalent logic doesn't apply here at all since there's no second port/bind to refuse.
- **The child's stderr is already routed to DEBUG.** `CbmClient._drain_stderr` (marm-graph's `cbm_client.py`) logs the binary's own output — including the PyPI shim's first-run "downloading v{version}..." progress line — at `logger.debug`. That will not surface to a normal user's default log level. The supervisor's own first-run INFO log (checking `_bin_path(...).exists()` before calling `start()`) is a separate, deliberate signal — don't rely on the stderr stream for user-visible messaging.
- **Do not override `CBM_CWD` to marm-mcp-server's own working directory.** This session's fix to `marm-graph` (`settings.py`) defaults `CBM_CWD` to a neutral store dir specifically to avoid the child accidentally deriving a session project from a CWD that happens to be an indexed project and silently starting upstream's own auto-index watcher. Let marm-graph's own default carry through unmodified.
- **Tool schema is static once registered — there is no dynamic "hide the 5 graph tools if the backend never starts" path** in this design. `FastApiMCP` builds `tools/list` from registered FastAPI routes at import/mount time, before any lazy backend start has happened. The 5 graph tools are always advertised; only call-time behavior degrades to the error dict. This is consistent with "core memory unaffected," but means an agent will see graph tools listed even on a machine where graph will never work (e.g. `GRAPH_ENABLED=false`) — acceptable and simpler than a dynamic surface, but worth knowing going in.
- **`codebase-memory-mcp` is exact-pinned (`==0.8.1`) inside marm-graph's own `pyproject.toml`.** Bumping `marm-graph`'s pin is already a reviewed change per its own docs; bumping the `marm-graph==0.1.0` pin inside marm-mcp-server is now a *second* reviewed change on top of that — both pins move independently and both need re-verification (mirrors the exact version-mismatch caution already documented in `protocol-proof.md` §3).
- **Graph startup is intentionally lazy.** Do not start the graph backend from FastAPI lifespan. The first graph-tool call owns startup and the one-time binary download if the engine is not cached yet. This keeps the core memory server light, prevents optional graph failures from blocking boot, and respects users who only want memory/logging.
- **Dependency source of truth is temporarily duplicated.** `pyproject.toml` is the pip/package contract. `requirements.txt` is still used by the existing Dockerfile to install the image dependencies, including the CPU-specific Torch wheel source. For this pip spec, mirror only the new `marm-graph==0.1.0` pin into `requirements.txt`; do not rewrite the Docker install strategy here.

---

## Testing Checklist

- [ ] `pip install marm-mcp-server` in a clean venv pulls in `marm-graph` and `codebase-memory-mcp` transitively (dependency resolution sanity check)
- [ ] `marm-mcp-server/requirements.txt` also contains `marm-graph==0.1.0` so the current Docker build path does not drift from the pip package before the Docker unification spec lands
- [ ] `marm-mcp-server` starts with **zero** graph-related network activity or child-process spawn when no graph tool has been called yet (lazy-start assertion)
- [ ] First call to any `marm_graph_*` tool triggers the download (mock/skip-guard the real 269MB fetch in CI, same `requires_binary`-style skip marm-graph's own tests use) and an INFO log line appears before the child spawns
- [ ] `tools/list` on the unified server returns all 12 operation_ids (7 core + 5 graph) — schema-stability test, mirrors marm-graph's own `test_mcp_exposes_exactly_five_ai_tools`
- [ ] Core memory tools (`marm_log_entry`, `marm_smart_recall`, etc.) work normally when the graph backend fails to start (simulate via `GRAPH_ENABLED=false` or a broken `CBM_BINARY_PATH`) — this is the critical failure-isolation test the whole spec exists to guarantee
- [ ] A forced schema-drift condition (mismatched `_EXPECTED_UPSTREAM_TOOLS`) is caught by the supervisor and downgrades to "graph unavailable," not a crashed server
- [ ] `GRAPH_ENABLED=false` short-circuits before any subprocess spawn attempt; graph tools return the clean error dict immediately
- [ ] Graceful shutdown: killing/stopping `marm-mcp-server` after graph has been used cleanly terminates the `codebase-memory-mcp` child (no orphaned process)
- [ ] Existing marm-graph standalone tests (`marm-graph/tests/`) still pass unchanged after the `core/backend.py` extraction — pure-refactor regression check

---

## Docs to Update

- [ ] `docs/current/graph-index/pip-packaging-unification.md` — mark Status: Complete when done
- [ ] `docs/current/graph-index/packaging-integration.md` — mark the pip-direction open question as resolved, link to this spec
- [ ] `marm-mcp-server/README.md` — quick start + tool count
- [ ] `MCP-HANDBOOK.md` — tool count + degraded-mode behavior note
- [ ] `marm-graph/README.md` — note that marm-mcp-server now embeds marm-graph by default; standalone install/Docker path is unchanged and still documented as-is

---

## Notes

- This spec deliberately does **not** touch Docker packaging — that's the next spec, and per this session's explicit scoping, dashboard folding only happens there, not here.
- Dashboard remains completely out of scope for pip: no changes to `marm-dashboard`'s package, install path, or docs in this spec.
