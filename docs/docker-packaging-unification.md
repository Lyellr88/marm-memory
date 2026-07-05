# Docker Packaging Unification (memory + graph + dashboard, one image)

**Status**: Planned
**Version Target**: v2.16.0 (same release as the pip unification — one MINOR bump covers both)
**Priority**: High
**Parent docs**: `docs/current/graph-index/packaging-integration.md` (the original design brief), `docs/current/graph-index/pip-packaging-unification.md` (sibling spec — this doc assumes graph is already embedded in `marm-mcp-server` via `graph_supervisor`, per that spec, and builds the dashboard fold-in on top of it).

---

## Problem

Today there are three Docker images (`lyellr88/marm-mcp-server`:8001, a `marm-dashboard` image:8002, and `marm-graph`:8003), each built and run separately. `packaging-integration.md`'s target is `docker run ... lyellr88/marm:latest` giving a normal user memory + dashboard + graph in one command. Unlike the pip spec — where dashboard stays a separate install on purpose — **Docker scope explicitly includes dashboard**: this is the one place everything really does become one artifact.

## Solution Overview

`marm-mcp-server`'s existing Docker image gains the dashboard (mounted as a sub-app on the same FastAPI process, same port) and the graph backend (via the `graph_supervisor` already built for pip, plus the binary baked at build time using marm-graph's own hardened checksum-verification pattern). The result ships under the **same Docker Hub repository name** (`lyellr88/marm-mcp-server`) to preserve its ~30,000 existing pulls — only the tag semantics change: `:latest` becomes the new all-in-one, and the old memory-only image shape is preserved under an explicit tag so nobody already depending on `:latest` today is silently broken.

---

## Architecture Decisions

| Decision | Chosen Direction | User Impact |
|---|---|---|
| Install/runtime shape | One image, `docker run lyellr88/marm-mcp-server:latest`. | One `docker run` gets memory + graph + dashboard. |
| Service boundary | **Dashboard**: sub-app mounted (`app.mount("/dashboard", dashboard_app)`) onto the same FastAPI process as memory+graph — one process, one port (8001). **Graph**: internal child process via `graph_supervisor` (from the pip spec) — no separate port. | Only port 8001 is ever exposed. Dashboard reachable at `http://host:8001/dashboard`. |
| Failure behavior | Same posture as the pip spec for graph (degraded mode, never fatal). Dashboard sub-app exceptions must not propagate into the parent app or affect memory/graph endpoints — Starlette's `Mount` already isolates a sub-app's routing tree, but startup-time dashboard errors (e.g. DB path unwritable) must be caught the same way graph's are, not left to crash the whole container. | A broken dashboard can never take memory or graph down with it. |
| Tool surface | Unchanged from the pip spec (7 core + 5 graph = 12). Dashboard adds **zero** MCP tools — it's mounted via `app.mount()`, not `app.include_router()`. **Empirically verified this session** against the actual installed `fastapi-mcp==0.4.0`: a mounted sub-app's routes do not appear in `FastApiMCP`'s `operation_map`/`tools/list` output, even when explicitly requested via `include_operations=[...]` — `FastApiMCP` builds its tool list from the root app's OpenAPI schema, and OpenAPI does not inline mounted sub-application routes. As defense-in-depth, `mcp = FastApiMCP(app)` (currently unwhitelisted at `server.py:517`) should still gain an explicit `include_operations=[...]` listing the 12 real tool operation_ids, matching the stricter pattern marm-graph's own `server.py` already uses — belt-and-suspenders, not load-bearing on its own. | No agent-visible change from adding dashboard. Confirmed, not assumed. |
| Data ownership | No new DB. Dashboard keeps reading `~/.marm/marm_memory.db` directly (unchanged code path); graph keeps `~/.marm/graph`. Both are the same volume mount (`~/.marm`) already used by today's `docker-compose.yml`. | One volume mount covers all three components' state. |
| Docker Hub naming | **Same repository**, `lyellr88/marm-mcp-server` — not a new repo name. `:latest` is redefined to mean the all-in-one build; the pre-unification image shape is preserved under an explicit tag (`:memory-only`, cut from the last pre-unification commit) so existing `:latest` pullers aren't silently broken without an escape hatch. | Preserves the ~30k pull count tied to the repository name. Requires a clear CHANGELOG/README migration note since `:latest`'s meaning changes without a version bump forcing anyone to notice. |

---

## UX Flow

1. User runs `docker run -p 8001:8001 -v ~/.marm:/home/marm/.marm lyellr88/marm-mcp-server:latest` (same command shape as today — only the port count is now "just one" instead of needing three separate `docker run`s).
2. Container starts: memory + graph (lazy-started per the pip spec) + dashboard, all in one process on port 8001.
3. `http://localhost:8001/` — MCP endpoints, unchanged.
4. `http://localhost:8001/dashboard` — the dashboard UI, now reachable under a path prefix instead of its own port. All its `/api/*` calls and `/assets/*` references resolve correctly under that prefix (this is the frontend fix below — without it, the UI loads but every API call and asset 404s).
5. Advanced users who want the old three-image split can still `docker pull lyellr88/marm-dashboard` and the dedicated `:memory-only` tag, or use a (new, optional) compose file that wires the three images together as separate services — not the default path, but not removed either.

---

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `marm-mcp-server/marm_mcp_server/core/dashboard_mount.py` | Small module: `from marm_dashboard.server import app as dashboard_app` (guarded — see Edge Cases for what happens if `marm-dashboard` isn't installed in a given build variant), returns the app for mounting. Keeps the import/failure-handling logic out of `server.py` itself, matching the existing pattern of small `core/` modules owning one integration concern. |

### Modified Files

| File | Change Summary |
|------|---------------|
| `marm-mcp-server/marm_mcp_server/server.py` | (1) Add `app.mount("/dashboard", get_dashboard_app())` near the existing `app.include_router(...)` block (current lines 508-514) and **before** `mcp = FastApiMCP(app)` (current line 517) — order doesn't structurally matter since `Mount` isn't scanned by `FastApiMCP`, but keeping it grouped with the other "attach things to the app" calls is clearest. (2) Change `mcp = FastApiMCP(app)` (line 517) to `mcp = FastApiMCP(app, include_operations=[...])` listing the 12 real tool operation_ids (7 core + 5 graph) — defense-in-depth on top of the verified mount-isolation behavior, matching marm-graph's own stricter whitelist pattern. This is a deliberate hardening added by this spec, not something marm-mcp-server does today. |
| `marm-mcp-server/pyproject.toml` | Add `"marm-dashboard==1.2.0"` to `dependencies` (same list as the pip spec's `marm-graph==0.1.0` addition, lines 29-44) — but **only in the Docker build path**, not the plain pip install (dashboard stays out of the default pip install per that spec's explicit scope boundary). Concretely: keep it as a `[project.optional-dependencies]` extra (e.g. `docker-image = ["marm-dashboard==1.2.0"]`) that only the Dockerfile installs, so a plain `pip install marm-mcp-server` still does NOT pull in dashboard. |
| `marm-mcp-server/Dockerfile` | (1) Switch the install step from `requirements.txt` to `pip install ".[docker-image]"` (resolves the pre-existing requirements.txt/pyproject.toml inconsistency flagged in the pip spec — Docker now installs `marm-graph` and `marm-dashboard` the same way pip users installing `marm-mcp-server` get `marm-graph`, plus the docker-only dashboard extra). (2) Add the hardened binary-bake block from `marm-graph/Dockerfile` (current lines 21-37: independent curl download + SHA256 verification + extraction, curl installed and purged in the same layer), adapted to install into this image instead. |
| `marm-mcp-server/docker-compose.yml` | Update image tag reference and env vars for the unified image; optionally add commented-out alternative services block for advanced users who want the split-image compose form. |
| `marm-dashboard/marm_dashboard/static/assets/app.js` | Frontend fix (see Insertion Points) — make API calls prefix-safe by using relative URLs (`api/...`, `health`) instead of root-absolute URLs (`/api/...`, `/health`). Do **not** compute a prefix from `document.currentScript`; this file is loaded as an ES module, where `document.currentScript` is `null`. |
| `marm-dashboard/marm_dashboard/static/index.html` | Change the two absolute asset references (`/assets/app.css`, `/assets/app.js`) to relative (`assets/app.css`, `assets/app.js`) so they resolve under `/dashboard/` when mounted there, and still resolve correctly when dashboard is run standalone at its own root. |
| `CHANGELOG.md` / `marm-mcp-server/README.md` | Migration note: `:latest` now means the all-in-one image; anyone who needs today's memory-only shape should pin `:memory-only` (or the last pre-unification version tag) going forward. |

---

## Implementation Plan

### Insertion Points

**`marm-dashboard/marm_dashboard/static/assets/app.js`**

1. **Remove root-absolute API paths** (line 1 currently has `const API = "";`; API calls appear throughout the file)
   What: delete the prefix-computation idea and convert API/health fetch paths from root-absolute to relative. Examples: `"/api/summary"` -> `"api/summary"`, `` `/api/sessions${params}` `` -> `` `api/sessions${params}` ``, `${API}/api/auth/unlock` -> `"api/auth/unlock"`, `${API}/health` -> `"health"`.
   Context: browsers resolve relative fetch URLs against the current page URL. When served at `/dashboard/`, `api/summary` resolves to `/dashboard/api/summary`. When served standalone at `/`, the same string resolves to `/api/summary`. This is simpler than a runtime prefix and avoids the ES-module `document.currentScript === null` trap.

2. **Delete or stop using `API`** (line 1: `const API = "";`)
   What: remove the constant if no longer used after converting fetch paths, or leave it only if every remaining use is proven harmless. Prefer removal so future edits do not restart the prefix-computation pattern.
   Context: the existing `${API}/...` pattern is only useful when `API` is a reliable prefix. The better fix has no prefix variable at all.

3. **Stale status copy** (line 270: `<span class="pill ok">Live on :8002</span>`)
   What: this hardcodes the old standalone port in UI copy. Update to reflect that the dashboard no longer implies a fixed port when embedded (e.g. drop the port-specific text, or make it dynamic from `window.location`).
   Context: cosmetic, but would otherwise show wrong information to every unified-image user.

**`marm-dashboard/marm_dashboard/static/index.html`**

1. **Asset references** (lines 7 and 249)
   What: `href="/assets/app.css?v=3"` → `href="assets/app.css?v=3"`, `src="/assets/app.js?v=3"` → `src="assets/app.js?v=3"` (relative, not absolute).
   Context: relative paths resolve correctly under any mount prefix automatically (browsers resolve them against the current document URL) — no runtime JS needed for this part, unlike the `/api/...` calls which are `fetch()`-issued and need the explicit `${API}` prefix.

**`marm-mcp-server/marm_mcp_server/server.py`**

1. **Dashboard mount** (near the `app.include_router(...)` block, current lines 508-514)
   What: `from .core.dashboard_mount import get_dashboard_app` + `app.mount("/dashboard", get_dashboard_app())`.
   Context: placed alongside the existing router-registration calls, before `mcp = FastApiMCP(app)` at line 517.

**`marm-mcp-server/marm_mcp_server/core/dashboard_mount.py`** (new)

What: 
```python
def get_dashboard_app():
    try:
        from marm_dashboard.server import app as dashboard_app
        return dashboard_app
    except ImportError:
        return None  # not installed in this build variant
```
`server.py`'s mount call must handle the `None` case (skip `app.mount(...)` entirely) so a hypothetical non-Docker build that doesn't include the `docker-image` extra doesn't crash on import.

**`marm-mcp-server/Dockerfile`**

1. **Install step**
   What: replace `COPY requirements.txt .` / `pip install ... -r requirements.txt` with `COPY pyproject.toml README.md ./` + `COPY marm_mcp_server ./marm_mcp_server` + `pip install --no-cache-dir ".[docker-image]"`.
   Context: this is the actual fix for the pre-existing requirements.txt/pyproject.toml drift — the Docker build currently can silently diverge from what `pyproject.toml` declares (it already doesn't list `marm-graph` today, and never will unless this changes). Re-verify the CPU-only torch pin from `requirements.txt` (`--index-url https://download.pytorch.org/whl/cpu`, `torch==2.8.0+cpu`) is preserved some other way (e.g. a pip constraints file or an extra index URL flag on the `pip install` line) so the CUDA-bloat regression this session's CHANGELOG shows was already fixed once (`v2.15.2`, "Forced CPU torch for builds") doesn't silently reappear.

2. **Binary bake** (new block, modeled on `marm-graph/Dockerfile` current lines 21-37)
   What: same independently-verified download+checksum+extract pattern, targeting this image's filesystem instead of marm-graph's.
   Context: reuse verbatim where possible — this exact hardening (curl installed and purged in one layer, archive re-verified against `checksums.txt` rather than trusting the shim's best-effort check) was written and tested this session; don't re-derive a weaker version.

**`marm-mcp-server/docker-compose.yml`**

1. **Image/tag reference**
   What: point at the new `:latest` (all-in-one) by default; add a comment explaining `:memory-only` is available for the old shape.
   Context: current file is single-service already (lines 1-30ish) — no structural change needed, just the tag/env update plus the migration comment.

---

## State & Data Flow

- No new state. Dashboard's `db.py` module continues reading `~/.marm/marm_memory.db` directly via the same file-path convention (`MARM_DB_PATH` env override, else `~/.marm/marm_memory.db`) it uses standalone — completely unaffected by being mounted as a sub-app instead of run as its own process, since it never talked to marm-mcp-server over HTTP for data access (only for the `/api/mcp-status` health-check ping, which still resolves to `127.0.0.1:8001/health` correctly since it's the same container, same loopback).
- The dashboard's own `auth_middleware` (its own `MARM_API_KEY` check, separate from marm-mcp-server's) continues to run — `app.mount()` preserves the mounted sub-app's own middleware stack, so this needs no code change, just confirmation via testing (see checklist).

---

## !! EDGE CASES & GOTCHAS -- READ BEFORE WRITING A SINGLE LINE OF CODE !!

- **The old `${API}` prefix idea is deprecated.** `const API = ""` at `app.js:1` was a half-finished abstraction, but the safer fix is to remove root-absolute URLs entirely and let the browser resolve relative paths.
- **Do not use `document.currentScript` for prefix detection.** `index.html` loads `app.js` with `type="module"`, and `document.currentScript` is `null` inside ES modules. A prefix computed from it would silently fail. Use relative URL strings instead.
- **Relative URLs are the intended fix.** `api/summary` resolves under the current dashboard page prefix automatically. This works both when mounted at `/dashboard/` and when served standalone at `/`.
- **Trailing slash matters.** Relative URLs work correctly from `/dashboard/`; from `/dashboard` without the slash, browsers treat `dashboard` like a file and `api/summary` can resolve to `/api/summary`. The mounted route must redirect `/dashboard` -> `/dashboard/`, or tests must verify Starlette already does this for the mounted sub-app.
- **Manual edit risk is real.** This is a hand-written frontend with no bundler and no JS test suite. After editing, run a grep guard for root-absolute API paths (`/api/`, `"\/api`, `'\/api`, template literals containing `/api`) and manually exercise dashboard actions under `/dashboard/`.
- **`Mount` vs `include_router` — verified, not just reasoned about.** Empirically tested this session against the actual installed `fastapi-mcp==0.4.0`: `root.mount("/dashboard", sub_app)` routes do not appear in `FastApiMCP`'s `operation_map` or `tools/list`, even with an explicit (wrong) `include_operations=["mounted_tool"]` naming a mounted route's operation_id — it still comes back empty, confirming `FastApiMCP` reads only the root app's OpenAPI schema, which never inlines mounted sub-apps. Add `include_operations=[...]` to `mcp = FastApiMCP(app)` anyway as defense-in-depth (marm-graph already does this; marm-mcp-server currently doesn't), and add the regression test below — but this is no longer an open risk requiring verification during implementation, it's a closed one.
- **Torch CPU pin regression risk.** `requirements.txt` currently pins `torch==2.8.0+cpu` via `--index-url https://download.pytorch.org/whl/cpu` specifically to avoid pulling CUDA/nvidia/triton packages (this was an actual CI/image-size fix landed in v2.15.2, per `CHANGELOG.md`). Moving the Docker install to `pyproject.toml`-based (`pip install ".[docker-image]"`) must preserve this constraint explicitly — `pyproject.toml`'s plain `"torch>=1.13.0"` dependency has no such guard today. Do not lose this fix while resolving the file-format inconsistency.
- **`:latest` tag semantic change is a real breaking change for automated pullers**, even though it's "just a tag." Anyone with `docker pull lyellr88/marm-mcp-server:latest` in a script, cron job, or compose file gets new behavior (new port count is actually the same — 8001 — but new processes running inside the same container, larger image size from the baked 269MB binary, etc.) with zero action on their part. The `:memory-only` escape hatch must exist and be documented *before* `:latest` changes meaning, not after.
- **Dashboard's own auth is separate from marm-mcp-server's.** Two different `MARM_API_KEY` checks exist in the codebase today (dashboard's `auth.py`/`config.py`, marm-mcp-server's own middleware) that happen to read the same env var and the same `~/.marm/.env` fallback file by convention — but they are two independent implementations. Mounting doesn't merge them; both continue running independently on their respective route trees. Don't assume "one middleware now" — verify both still gate their own routes correctly after the mount.
- **Image size**: baking the 269MB `codebase-memory-mcp` binary into what's now also carrying dashboard's static assets and dependencies makes this a meaningfully larger image than today's `marm-mcp-server:latest`. Worth a mention in the migration note so nobody is surprised by pull/storage size jumping.

---

## Testing Checklist

- [ ] `docker build` succeeds using `pip install ".[docker-image]"` and produces a working image (replaces the `requirements.txt` install path)
- [ ] CPU-only torch constraint is verified in the built image (`pip show torch` reports `+cpu` build, no `nvidia-*`/`triton` packages present) — regression guard for the v2.15.2 fix
- [ ] Container starts with a single exposed port (8001); no process listens on 8002 or 8003
- [ ] `GET /health` (MCP) still returns the same shape as today
- [ ] `GET /dashboard/` serves the dashboard UI; loads its CSS/JS from `/dashboard/assets/...` with no 404s
- [ ] `GET /dashboard` either redirects to `/dashboard/` or otherwise preserves relative URL resolution correctly
- [ ] Grep guard after frontend edits finds no root-absolute dashboard API calls (`/api/...`) remaining in `app.js`
- [ ] Every dashboard `/api/*` call (create/list/delete memory, session, notebook, log, compaction, maintenance) works correctly when the browser is on `/dashboard/...` — exercise the real endpoints, not just page load
- [ ] Dashboard's `/dashboard/api/mcp-status` correctly reaches the MCP health endpoint on the same container's loopback
- [ ] `tools/list` (MCP) still returns exactly 12 operation_ids — confirms dashboard's ~25 REST routes do NOT leak into the MCP tool surface via the sub-app mount
- [ ] Regression test pairing both sides of the mount-visibility guarantee: a mounted dashboard route (e.g. `GET /dashboard/health`) is reachable over plain HTTP, AND absent from `tools/list` — both assertions in one test so a future refactor can't silently satisfy one while breaking the other
- [ ] Dashboard's own `MARM_API_KEY` gate still rejects unauthenticated `/dashboard/api/*` calls when a key is set, independently of marm-mcp-server's own auth gate
- [ ] Standalone `marm-dashboard` package/image (unchanged, still run at its own root) still works after the `app.js`/`index.html` path changes — the same bundle must serve correctly both mounted-at-a-prefix and served-at-root
- [ ] Graph capability inside the unified image behaves identically to the pip spec's own tests (lazy start, degrade-to-error-dict on failure, first-run download messaging) — this image doesn't get a separate test suite for that behavior, just confirmation it isn't broken by the Docker-specific packaging
- [ ] `docker-compose.yml` `up` brings up the unified container correctly with the `~/.marm` volume mount

---

## Docs to Update

- [ ] `docs/current/graph-index/docker-packaging-unification.md` — mark Status: Complete when done
- [ ] `docs/current/graph-index/packaging-integration.md` — mark the Docker-direction open question resolved, link to this spec
- [ ] `CHANGELOG.md` — explicit `:latest` semantic-change migration note, `:memory-only` tag introduction
- [ ] `marm-mcp-server/README.md` — Docker quick-start section, new image contents, `:memory-only` escape hatch
- [ ] `marm-dashboard/README.md` — note the dashboard is now also shipped embedded in the unified image at `/dashboard`, standalone install/Docker path unchanged

---

## Notes

- This spec assumes the pip spec's `graph_supervisor` design lands first (or alongside) — the Docker image's graph behavior is entirely inherited from it, not re-designed here.

