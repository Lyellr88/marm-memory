# MARM Directory

Source of truth for the full codebase layout. Three active packages: `marm-mcp-server` (agent-facing memory MCP), `marm-dashboard` (human-facing web UI), and `marm-graph` (code-structure graph wrapper). The default product direction is one system externally, modular internally.

---

## marm-mcp-server/ (root)

```markdown
marm-mcp-server/
├── Dockerfile                     # Docker build — ENTRYPOINT uses python -m marm_mcp_server; CLI flags (--swarm etc.) append after image name
├── docker-compose.yml             # Docker Compose config
├── docker-build.sh                # Local Docker build helper
├── docker-run.bat                 # Windows Docker run script
├── install.sh                     # Clone-based install script
├── pyproject.toml                 # Pip package definition — name, version, dependencies
├── requirements.txt               # Docker/build dependency mirror; currently keeps CPU Torch wheel constraints
├── requirements_stdio.txt         # STDIO transport dependencies
├── validate_server_json.py        # CI script — validates server.json shape
├── publish_to_mcp.py              # MCP Registry publish helper
├── server.json                    # MCP Registry manifest
├── server_stdio.py                # STDIO shim entry (delegates to package server_stdio.main)
│
├── marm_mcp_server/               # pip-installable package — single source of truth
│   ├── __init__.py
│   ├── __main__.py                # python -m marm_mcp_server entry point
│   ├── server.py                  # FastAPI app — registers all routers, mounts MCP
│   ├── server_stdio.py            # STDIO FastMCP transport (package copy)
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py            # Port, DB path, pool size, rate-limit config, rerank/temporal recall tuning, auto-key logic
│   ├── core/
│   │   ├── __init__.py
│   │   ├── memory.py              # MARMMemory facade — encoder lifecycle, module wiring, compatibility surface
│   │   ├── memory_db.py           # Connection pool, schema setup, FTS triggers, migrations, compaction DB helpers
│   │   ├── memory_utils.py        # Sanitization, query helpers, text chunking, async chunk writes
│   │   ├── memory_scoring.py      # FTS candidate fetch, semantic scoring, chunk-aware parent dedup
│   │   ├── memory_ops.py          # Store/update/delete/recall operations and queued memory writes
│   │   ├── consolidation.py       # Layer 1/2 consolidation — hash dedup + semantic merge helpers
│   │   ├── compaction.py          # Layer 3 compaction — cluster detection, staging, nudge logic
│   │   ├── models.py              # Pydantic request/response models (shared across endpoints)
│   │   ├── rate_limiter.py        # IP-based rate limiter logic
│   │   ├── response_limiter.py    # MCPResponseLimiter — 1MB MCP compliance
│   │   ├── events.py              # Server lifecycle events (startup/shutdown hooks)
│   │   ├── shutdown_manager.py    # Graceful shutdown coordination
│   │   └── write_queue.py         # Default-on serialized write queue for high-concurrency workflows
│   ├── endpoints/
│   │   ├── __init__.py
│   │   ├── memory.py              # marm_smart_recall
│   │   ├── compaction.py          # Unified marm_compaction + hidden legacy compaction routes
│   │   ├── session.py             # legacy startup/session endpoints (HTTP route layer only)
│   │   ├── logging.py             # marm_log_entry, marm_log_show, marm_delete log paths
│   │   ├── notebook.py            # unified marm_notebook endpoint (action-dispatched)
│   │   ├── reasoning.py           # marm_summary
│   │   └── system.py              # health/readiness/info endpoints
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py                # Bearer token middleware — loopback passthrough or key check
│   │   └── rate_limiting.py       # HTTP rate limiting middleware
│   ├── services/
│   │   ├── __init__.py
│   │   ├── automation.py          # Event-driven automation engine
│   │   ├── compaction_apply.py    # Atomic staged compaction apply transaction
│   │   ├── compaction_summarize.py # Server-side fallback summarization for nudge-exhausted candidates
│   │   ├── documentation.py       # Lazy doc loader + hash index (doc_index), auto-refresh lifecycle hooks
│   │   ├── notebook.py            # Notebook action dispatcher shared by HTTP + STDIO
│   │   ├── recall.py              # Shared smart-recall response logic, detail-layer truncation
│   │   └── summary.py             # Shared cached session summary via session_summary_cache
│   └── utils/
│       ├── __init__.py
│       ├── helpers.py             # Shared utility functions
│       └── security.py            # generate_api_key() — 40-char, ~244 bits, shell-safe alphabet
│
├── marm-docs/                     # Server-loaded docs (injected into context at startup)
│   ├── README.md
│   ├── MCP-HANDBOOK.md
│   ├── PROTOCOL.md
│   ├── QUICK-INSTALL.md
│   └── ROADMAP.md
│
└── tests/
    ├── conftest.py                        # load_isolated_server(), local_client(), remote_client() fixtures
    ├── test_cli_entrypoint.py             # --generate-key, --check-deps, import clean stdout, server startup + /health
    ├── test_compaction_auto_apply.py      # Compaction scheduler/write-queue/direct apply behavior
    ├── test_compaction_staging.py         # Unified compaction staging/review/apply/discard behavior
    ├── test_compaction_worker.py          # Cluster detection, reports, stale cleanup
    ├── test_consolidation_exact_dedup.py  # Content hash dedup + collision/race regressions
    ├── test_consolidation_write_time.py   # Semantic write-time merge behavior
    ├── test_docker_transports.py          # Docker HTTP auth + STDIO stdout purity (skip if Docker unavailable)
    ├── test_http_app.py                   # FastAPI app structure, route registration, health endpoint
    ├── test_http_rate_limit.py            # Rate limiter enforcement via HTTP — 429 on 21st request
    ├── test_http_security_regressions.py  # Auth bypass attempts, header injection, SQL injection probes
    ├── test_http_tools.py                 # All MCP tool endpoints — deep assertions on content, session isolation
    ├── test_hybrid_search.py              # FTS triggers/backfill, filter→rerank recall, candidate-cap enforcement, fallback paths, LIKE fallback
    ├── test_chunking.py                   # memory_chunks sidecar schema, long-memory chunk writes, chunk-aware recall behavior
    ├── test_email_signup_prompt.py        # One-time optional email signup prompt injection + persistence
    ├── test_exact_retrieval_lane.py       # Exact retrieval lane for quoted/config-key/file-like queries
    ├── test_memory_database.py            # sanitize_content(), _strip_script_tags() edge cases, store/recall/classify
    ├── test_notebook_service.py           # notebook action dispatcher — validation + session-scoped active state
    ├── test_project_platform_tagging.py   # project/platform schema, tagging, scoped recall, log/notebook attribution
    ├── test_rate_limiter.py               # Rate limiter unit tests — IP tracking, window reset, block duration
    ├── test_response_limiter.py           # MCPResponseLimiter — 1MB truncation, passthrough under limit
    ├── test_security_key_generation.py    # generate_api_key() entropy, alphabet constraints, uniqueness
    ├── test_server_logging.py             # HTTP server logging behavior
    ├── test_summary_cache.py              # Flat session_summary_cache rebuild, invalidation, truncation, disposable-cache behavior
    ├── test_temporal_weighting.py         # Temporal weighting decay, clamp, and zero-weight behavior
    ├── test_3layer_retrieval.py           # detail=1/2/3 layered retrieval depth and HTTP parity
    ├── test_compaction_summarize.py       # Server-side compaction fallback summarization behavior
    └── test_stdio_transport.py            # STDIO transport — stdout clean, tools exposed, notebook/session/logging regression tests
```

---

## marm-graph/ (root)

```markdown
marm-graph/
├── Dockerfile                     # Standalone graph image — bakes verified codebase-memory-mcp binary
├── pyproject.toml                 # Pip package definition — name marm-graph, pinned codebase-memory-mcp dependency
├── README.md                      # Graph-specific usage, trust boundary, tools, Docker notes
│
├── marm_graph/                    # pip-installable graph package
│   ├── __init__.py
│   ├── __main__.py                # python -m marm_graph entry point
│   ├── server.py                  # Standalone FastAPI/FastApiMCP graph server, strict 5-tool MCP whitelist
│   ├── server_stdio.py            # Standalone graph STDIO transport
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py            # Host/port/API key, store dir, binary path, timeout, response limit, neutral CBM cwd
│   ├── core/
│   │   ├── __init__.py
│   │   ├── cbm_client.py          # Long-lived stdio client for codebase-memory-mcp; JSON unwrap, timeouts, respawn
│   │   ├── deps.py                # Singleton CbmClient factory for standalone graph server
│   │   ├── models.py              # Pydantic request/response models for graph tools
│   │   └── tool_router.py         # Maps 5 MARM graph tools to upstream codebase-memory-mcp calls
│   ├── endpoints/
│   │   ├── __init__.py
│   │   ├── graph_ai.py            # 5 AI-facing MCP routes: index, lookup, trace, architecture, impact
│   │   └── graph_ui.py            # UI-only REST routes for MARMIS; never included in MCP tools/list
│   └── middleware/
│       ├── __init__.py
│       └── auth.py                # Loopback passthrough or bearer check for standalone graph HTTP
│
└── tests/
    ├── conftest.py                # Graph test fixtures; binary-dependent tests skip cleanly
    ├── test_cbm_client.py         # JSON-RPC framing, unwrap, timeout/crash behavior
    ├── test_graph_endpoints.py    # HTTP/MCP route exposure, auth, UI endpoint separation
    ├── test_tool_router.py        # Router behavior for the 5 graph tools
    └── TEST-HYGIENE.md            # Deferred test isolation note for shared upstream graph store
```

**Current packaging state:** standalone package/service on port 8003.  
**Planned v2.16 default:** `marm-mcp-server` depends on `marm-graph`, exposes the same 5 graph tools on port 8001, and lazy-loads the graph backend only on first `marm_graph_*` call. Standalone `marm-graph` remains an advanced/dev path.

---

## marm-dashboard/ (root)

```markdown
marm-dashboard/
├── Dockerfile                     # Docker build for dashboard — port 8002
├── README.md                      # Dashboard-specific readme with screenshot
├── pyproject.toml                 # Pip package definition
│
├── marm_dashboard/                # pip-installable package
│   ├── __init__.py
│   ├── __main__.py                # python -m marm_dashboard --open entry point
│   ├── server.py                  # FastAPI app — all /api/* routes (memories, sessions, logs, notebook, summary)
│   ├── db.py                      # Direct SQLite access — CRUD for all 4 data types, _strip_script_tags(), _sanitize_memory()
│   ├── auth.py                    # is_valid_key() — loopback passthrough or bearer check
│   ├── config.py                  # MARM_API_KEY from env, fallback to ~/.marm/.env; get_db_path()
│   └── static/
│       ├── index.html             # Single-page app shell
│       └── assets/
│           ├── app.js             # All tab logic — memories, sessions, logs, notebook, overview
│           └── app.css            # Dark theme, card layout, confirm dialogs, loading screen
│
└── tests/
    ├── conftest.py                      # load_dashboard(), local_client() fixtures — in-process, no live server
    ├── test_dashboard_auth.py           # Loopback passthrough, bearer key enforcement, security headers
    ├── test_dashboard_db.py             # Full CRUD — memories, sessions, logs, notebook; sanitization, pagination, search
    └── test_dashboard_mcp_status.py     # /api/summary MCP status probe — healthy, unreachable, non-200 responses
```

---

## Notes

- Root-level duplicate folders (`core/`, `endpoints/`, `middleware/`, etc.) have been deleted — `marm_mcp_server/` is the single source of truth
- `server_stdio.py` at `marm-mcp-server/` root is a thin shim to package STDIO entrypoint — keep it for compatibility
- WebSocket and mock-oauth source files were removed in v2.3.0–v2.4.0; only stale `__pycache__` artifacts may still reference them locally
- All new MCP code goes in `marm_mcp_server/` only; all new dashboard code goes in `marm_dashboard/` only
- Both packages share the same SQLite DB (`~/.marm/marm_memory.db`) — WAL mode handles concurrent access
- `marm-graph` stores graph data separately under `~/.marm/graph`; it does not write to `marm_memory.db`
- Graph/index planning lives under `docs/current/graph-index/`, with packaging unification specs currently in `docs/pip-packaging-unification.md` and `docs/docker-packaging-unification.md`
- Default product direction: one user-facing MARM system, separate internals only when they are lazy, optional, and failure-isolated
