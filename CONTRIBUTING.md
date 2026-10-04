# Contributing to marm-memory

_Last updated: September 28, 2026 (v2.54.1)_

You do not need to write code to contribute. Testing MARM with your client setup, reporting what broke, sharing your workflow in [Discussions](https://github.com/Lyellr88/marm-memory/discussions), or jumping into [Discord](https://discord.gg/nhyJWPz2cf) to help someone get unstuck are all real contributions.

If you do want to go deeper, MARM is focused on the MCP server, local memory workflows, the code and concept knowledge graphs, Docker/STDIO transports, IDE and client integrations, and marm-console for inspecting local memory data. This guide covers that practical development workflow. For project history and community recognition, see [ACKNOWLEDGMENTS.md](docs/ACKNOWLEDGMENTS.md).

## AI-Assisted Contributions

AI coding tools, including Claude Code, Codex, and Copilot, are welcome for generating code and draft reviews. The account owner remains responsible for every contribution: PR descriptions, issue comments, and code reviews must be personally reviewed and submitted by that person. Automated bot-to-bot conversational responses on issue and pull-request threads are not permitted.

When opening a PR or issue, complete the human-review confirmation in the template. This keeps discussion grounded in a contributor's own understanding of the change, report, or recommendation.

## Questions or Ideas

Drop a message in [MARM Discord](https://discord.gg/nhyJWPz2cf) or reach out directly at support@marmemory.com.

## Getting Started

```powershell
git clone https://github.com/Lyellr88/marm-memory.git
cd marm-memory
```

Install the MCP server in editable mode:

```powershell
cd marm-mcp-server
pip install -e ".[dev]"
```

For source development, fetch the bundled extraction model into package data:

```powershell
python scripts/bundle-concept-model.py
```

Run the HTTP server:

```powershell
python -m marm_mcp_server
```

Run the STDIO server:

```powershell
python -m marm_mcp_server.server_stdio
```

Generate an API key when using exposed HTTP mode or Docker HTTP:

```powershell
python -m marm_mcp_server --generate-key
```

To work on the Console frontend, you also need Node.js 20+ and pnpm 10+. From `marm-console/`, run the dev launcher, which starts the Console API on `127.0.0.1:8002` and the frontend dev server. See [marm-console/README.md](marm-console/README.md) for details.

```powershell
cd marm-console
.\run-dev.ps1
```

## Development

### Project Structure

```text
marm-mcp-server/
  marm_mcp_server/
    __main__.py                # `python -m marm_mcp_server` entry, delegates to cli
    cli.py                     # HTTP CLI, dependency checks, and server factory
    server.py                  # FastAPI HTTP composition root
    server_stdio.py            # STDIO bootstrap and core-tool registration
    config/
      settings.py              # Paths, host/port, auth, feature flags
      env_parsing.py           # Safe typed parsing of environment variables
      api_key_bootstrap.py     # Private key directory and key file writes
    core/
      memory.py                # MARMMemory facade and public memory object wiring
      memory_utils.py          # Shared memory helpers, chunking, and encoding utilities
      memory_db.py             # SQLite schema, connection pool, and DB maintenance routines
      memory_scoring.py        # Semantic, FTS, temporal, and chunk-aware recall scoring
      memory_ops.py            # Store/update/recall/delete/list memory operations
      memory_recall.py         # Recall orchestration across the scoring lanes
      memory_delete.py         # Delete paths and their cascade handling
      write_queue.py           # Serialized write queue for SQLite writer stability
      consolidation.py         # Content-hash and semantic write-time consolidation
      compaction.py            # Background compaction candidate detection and nudges
      compaction_scheduler.py  # Optional compaction maintenance scheduler
      docs_db.py               # Indexed copy of the shipped docs served to agents
      concept_db.py            # Concept graph schema and isolated SQLite pool
      concept_extraction.py    # spaCy entity/relationship extraction (bundled model)
      concept_queue.py         # Durable outbox: one indexing task per stored memory
      concept_worker.py        # Background worker draining that queue into the graph
      concept_build_lock.py    # Concept-graph binding of the cross-process lease
      concept_review.py        # Duplicate-concept review decisions
      lease_lock.py            # Leased-row mutual exclusion, shared by both graphs
      graph_supervisor.py      # Lazy singleton supervisor for the embedded graph engine
      graph_client.py          # Concept graph's in-process link into the code graph
      graph_index_lock.py      # The one gate every code-graph store mutation takes
      graph_index_worker.py    # Keeps code graphs current: watcher wakeups plus reconciliation
      graph_index_watcher.py   # Filesystem watcher that wakes the worker on a real change
      code_project_bindings.py # Links code-graph projects to memory projects
      code_link_queue.py       # Queue of memory-to-code link refreshes
      _link_distinctiveness.py # Gate that keeps generic words from linking to code
      distill.py               # Proposes durable memories from conversation text
      runtime_flags.py         # Persisted on/off switches and watch suppressions
      runtime_manager.py       # Local runtime discovery and background start/stop
      protocol_delivery_state.py  # Bounded HTTP protocol-delivery state
      models.py                # Shared Pydantic request/response models
      events.py                # Internal event hooks
      rate_limiter.py          # Rate limiting primitives
      response_limiter.py      # MCP response size controls
      shutdown_manager.py      # Graceful shutdown handling
      stdio_logging.py         # STDERR-only STDIO logger setup
      stdio_tool_lifecycle.py  # STDIO protocol, logging, and compaction wrapper
    endpoints/
      session.py               # Session tools
      logging.py               # Log tools
      reasoning.py             # Reasoning/deep-dive tools
      notebook.py              # Notebook tools
      memory.py                # Recall/search tools
      compaction.py            # Unified compaction tool and hidden helper routes
      graph.py                 # 5 bundled code-graph tools (routed through marm_graph)
      concepts.py              # 2 concept-graph tools (build + recall)
      code_context.py          # Task-scoped code context in one call
      distill.py               # Propose, review, apply, and discard memory candidates
      system.py                # Health/system tools
    middleware/
      auth.py                  # Bearer auth for HTTP mode
      protocol_injection.py    # HTTP MCP protocol/compaction response injection
      rate_limiting.py         # HTTP rate limiting middleware
    services/
      analytics.py             # Best-effort local usage analytics
      documentation.py         # Startup documentation loading
      automation.py            # Event handler registration
      notebook.py              # Notebook dispatch service
      recall.py                # Shared smart-recall response logic
      summary.py               # Shared session summary formatting
      graph_context.py         # Bounded read-only concept context for recall
      log_entry.py             # Shared log-entry/notebook data ops, both transports
      compaction_apply.py      # Atomic compaction apply transaction
      compaction_summarize.py  # Compaction cluster summarization helpers
      concept_build_engine.py  # Concept extraction loop for manual and background builds
      code_context/            # Seeding, ranking, snippets, and formatting for code context
      distill.py               # Stages distill proposals and applies the kept ones
      local_llm.py             # Optional local OpenAI-compatible generation backend
      model_discovery.py       # Finds language models already on this machine
      hardware.py              # Accelerator and free-memory detection
      backup.py                # Online snapshots of the memory database
      stdio_entry_tools.py     # STDIO log entry/show/delete workflow bodies
      stdio_graph_tools.py     # STDIO graph/concept bodies and registration helper
      cli_parser.py            # Argument parsers for the product and legacy CLIs
      cli_output.py            # Human-readable status/doctor/maintenance rendering
      product_help.py          # Terminal-aware root help rendering
      product_workflows.py     # High-level local workflows (start, upgrade, uninstall)
      product_logs.py          # Bounded managed-runtime log display
      runtime_status.py        # Read-only status aggregation for diagnostics
      projects_cli.py          # `projects` code-index commands
      graph_auto_cli.py        # `projects auto` / `knowledge auto` on-off switches
      key_management.py        # Persistent local API-key operations
      package_management.py    # Installer detection and registry checks
      skill_install.py         # Installs the bundled marm-init skill into agent folders
      docker_cli.py            # Docker parser registration and dispatch
      docker_commands.py       # Safe Docker command planning and execution
    utils/
      dependency_check.py      # Runtime dependency validation
      helpers.py               # Shared helpers
      logging_filters.py       # Process logging noise filters
      multiprocess_guard.py    # Unsupported multi-worker runtime warning
      security.py              # API key generation
      embedding_state.py       # Inspect persisted embedding compatibility, no runtime init
      embedding_migration.py   # Resumable stopped-server embedding vector migration
      chunk_backfill.py        # Stopped-server backfill of memory_chunks after config change
    console/                   # Console API served on :8002 (`marm-memory console`)
      app.py                   # FastAPI app, auth, and static frontend serving
      endpoints/               # Console REST routes, one file per workspace
      terminal/                # Embedded terminal over WebSocket
      static/                  # Built frontend bundle shipped in the wheel
    resources/                 # Bundled docs and the marm-init skill
    models/                    # Bundled concept extraction model
  marm_graph/                  # Embedded marm-graph wrapper: subprocess JSON-RPC client,
                               #   tool router, and backend verification for the pinned
                               #   codebase-memory-mcp binary
  tests/                       # MCP server test suite
  Dockerfile                   # One image, HTTP default, STDIO override
  pyproject.toml               # Package metadata and console scripts

docs/                          # User-facing docs and project docs
scripts/                       # Local validation, release, and maintenance helpers
marm-console/                  # Console frontend source (React, pnpm); built into console/static
```

### Key Patterns

**HTTP and STDIO are separate transports**

HTTP mode lives in `marm_mcp_server/server.py` and is mounted through FastAPI/FastApiMCP at `/mcp`.

STDIO mode lives in `marm_mcp_server/server_stdio.py` and uses the official MCP Python SDK over standard input/output. It owns the FastMCP app and registers the eight core tools first; `services/stdio_graph_tools.py` supplies the graph/concept tool bodies through explicit registration so `tools/list` order remains stable. STDIO must keep stdout clean for JSON-RPC messages; logs and incidental `print()` output belong on stderr.

If a tool behavior changes, check whether the HTTP endpoint and STDIO tool both need the same update.

Separate transports means separate processes. Both run the same background indexers (concept extraction and code re-indexing) against the same databases, so anything they touch needs mutual exclusion that reaches across processes: a leased row in the memory database, not an `asyncio.Lock` or a module-level `threading.Lock`. `core/lease_lock.py` is that primitive, and a run of the test suite is not enough to catch a mistake here, since one interpreter never exercises the boundary. The two-process tests in `tests/test_concept_two_process.py` and `tests/test_graph_auto_index.py` spawn a real second interpreter for exactly that reason.

**Docker HTTP requires an API key**

Docker HTTP binds inside the container with `SERVER_HOST=0.0.0.0`, and host requests arrive through Docker bridge networking rather than `127.0.0.1`. Always pass `MARM_API_KEY` for Docker HTTP.

```powershell
docker run -d --name marm-mcp-server `
  -p 127.0.0.1:8001:8001 `
  -e SERVER_HOST=0.0.0.0 `
  -e MARM_API_KEY=your-generated-key `
  -v ${HOME}\.marm:/home/marm/.marm `
  lyellr88/marm-mcp-server:latest
```

**Docker STDIO does not use an HTTP key**

Docker STDIO launches a one-client process and does not expose an HTTP listener.

```powershell
docker run -i --rm `
  -v ${HOME}\.marm:/home/marm/.marm `
  lyellr88/marm-mcp-server:latest `
  python -m marm_mcp_server.server_stdio
```

Use Docker HTTP for shared or multi-agent workflows. Use STDIO for private single-client local workflows. Multiple STDIO containers can point at the same mounted SQLite database, but heavy concurrent writes may hit normal SQLite lock contention.

**Local HTTP defaults to loopback**

`SERVER_HOST` defaults to `127.0.0.1`. Local loopback HTTP is intended for same-machine use and does not require a key unless `MARM_API_KEY` is set.

If `SERVER_HOST=0.0.0.0`, MARM requires a key. When no key is provided, the settings layer auto-generates one and stores it in `~/.marm/.env`.

**SQLite schema changes need extra care**

MARM uses a local SQLite database under `~/.marm/` by default. Tool behavior depends on specific tables for sessions, log entries, notebook entries, memories, compaction staging, and analytics.

Memory, log, and notebook rows can carry nullable `project` and `platform` attribution columns. When changing write paths, recall filters, consolidation, or schema migrations, keep these fields aligned across HTTP, STDIO, tests, and docs.

Do not rename fields, move data between tables, or change date/session parsing behavior without updating HTTP tools, STDIO tools, tests, smoke scripts, and docs together.

**Retired features stay retired unless re-scoped**

Current supported connection paths are HTTP and STDIO. Do not reintroduce retired transports or auth shims unless there is a new spec and implementation plan for them.

## Adding or Changing MCP Tools

1. Find the current HTTP behavior in `marm_mcp_server/endpoints/`.
2. Find the matching STDIO behavior in `marm_mcp_server/server_stdio.py`.
3. If the Console exposes the same feature, check the matching route in `marm_mcp_server/console/endpoints/`.
4. Keep request/response field names aligned where possible.
5. Prefer parameterized actions for closely related operations, following existing tools such as `marm_notebook(action=...)`, `marm_delete(type=...)`, `marm_compaction(action=...)`, and `marm_distill(action=...)`.
6. Update or add focused tests in `marm-mcp-server/tests/`.
7. Update docs if the command shape, transport setup, auth behavior, or user-facing workflow changes.
8. Run the local test runner before submitting changes.

## Testing

Run the known-good local test checks from the repo root:

```powershell
python scripts/run-tests.py
```

This runs:

- Python compile check for `marm_mcp_server` and `tests`
- Pytest suite with a controlled temp directory, run in parallel on 4 `pytest-xdist` workers with one test file per worker at a time
- Console route contracts and the Console frontend checks

Use the runner for full runs. It sets up the parallel workers, the temp directories, and the marker filters for you. Install the dev dependencies (`pip install -e ".[dev]"` from `marm-mcp-server`) so `pytest-xdist` is available.

Useful runner options:

```powershell
python scripts/run-tests.py --workers 8      # more workers if your machine has the cores and RAM
python scripts/run-tests.py --workers 1      # serial, for reproducing an order-dependent failure
python scripts/run-tests.py --durations 40   # list the 40 slowest tests
```

Each worker imports the whole server, so RAM use grows with the worker count. Tests must not depend on another test file's state, because files run on separate worker processes in any order.

For targeted ad hoc pytest runs, use `--basetemp C:\tmp\...` or clean repo-local pytest artifacts afterward:

```powershell
python scripts/clean-pytest-artifacts.py --what-if
python scripts/clean-pytest-artifacts.py
```

Current expectations:

- `Failed: 0` required before submitting a PR
- Docker tests may skip automatically when Docker or the smoke image is unavailable
- Warnings should be reviewed, but a known dependency warning may not block a PR

Run release preflight before a push or release:

```powershell
python scripts/release-preflight.py
```

This runs the version scan, stale docs scan, known-good test runner, optional Docker smoke test, and a git status summary.

Run Docker smoke directly when changing Docker, transport setup, auth, or startup behavior:

```powershell
python scripts/test-scripts/docker-smoke.py
```

For changes to Docker bind mounts, container users, `HOME`, cache paths, or data persistence, also run the Linux-only smoke test. It verifies that a host-owned mounted database can be written through HTTP and survives a container restart.

Run it from a native Linux host or WSL2 with Docker Desktop WSL integration enabled. The script creates its temporary mounted data directory under Linux `/tmp`; do not change that location to `/mnt/c`, or the UID/GID assertion is no longer meaningful:

```bash
bash scripts/test-scripts/docker-linux-bind-mount-smoke.sh
```

The script uses the latest official image by default. To test a locally built image instead:

```bash
MARM_DOCKER_SMOKE_IMAGE=marm-mcp-server:smoke bash scripts/test-scripts/docker-linux-bind-mount-smoke.sh
```

## Documentation

Update docs when changing:

- Install commands
- Docker behavior
- Client transport commands
- API key behavior
- Tool request/response fields
- Database behavior
- Version numbers
- Roadmap or support status

Useful maintenance scripts:

```powershell
python scripts/find-versions.py
python scripts/find-dead-code.py
```

`find-versions.py` is interactive and can update active version references. It intentionally avoids changing `CHANGELOG.md` because that file contains historical versions. `find-dead-code.py` looks for unused functions and classes in the MCP server codebase. Review its findings carefully before removing any code, as some utilities may be used in dynamic ways or reserved for future features.

## Submitting Changes

MARM uses a PR-first workflow for normal development. Do not push feature, fix, or release-prep work directly to `MARM-main`.

1. Create a focused branch from `MARM-main`.
2. Keep the change scoped to one feature, fix, or doc cleanup.
3. Follow existing file patterns before adding new abstractions.
4. Run `python scripts/run-tests.py`.
5. Run Docker smoke if the change touches Docker, HTTP/STDIO startup, auth, or transports.
6. Update docs and changelog when user-facing behavior changes.
7. Push the branch and open a PR into `MARM-main`.
8. Wait for CodeRabbit and GitHub checks, then address review findings before merge.

No formal style guide beyond this: keep code readable, preserve current behavior unless the PR is explicitly changing it, and avoid broad refactors mixed into feature work.

### Features Start as an Accepted Issue

New features, new tools, new parameters, and changes to default behavior start as an issue. Open the issue first and describe the problem and the proposed approach, then wait for the maintainer to label it `accepted` before opening the PR, and link that issue from the PR. This settles scope before code is written, so the review is about the implementation rather than whether the feature belongs.

Bug fixes, test fixes, and documentation corrections do not need an accepted issue and can go straight to a PR.

### Open PR Limit

Each contributor can have up to three open PRs at a time. Once three are open, keep further work in a draft PR or a branch until one of the open PRs is merged or closed. Draft PRs do not count toward the limit, but they are not reviewed until they are marked ready.

MARM has one maintainer, and this limit keeps every PR reviewed with proper care instead of queued behind a backlog.

### Branch Naming

Use short, descriptive branch names:

```text
feature/notebook-polish
fix/dependency-range
docs/install-cleanup
release/v2.6.3
```

### Release Flow

Publishing is tag-driven. Merging a PR into `MARM-main` does not publish PyPI, Docker, or the MCP Registry by itself.

Release sequence:

```text
branch → PR → CodeRabbit review → merge to MARM-main → tag vX.Y.Z → publish workflow
```

After the PR is merged and `MARM-main` is clean:

```powershell
git checkout MARM-main
git pull
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

The `v*` tag triggers the publish workflow for:

- PyPI package publish
- MCP server Docker image
- MCP Registry publish

Use normal branch pushes for review. Use tag pushes only for intentional releases.

## Project Documentation

### **Usage Guides**

- **[README.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/README.md)** - Complete MCP server usage guide with commands, workflows, and examples
- **[PROTOCOL.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/PROTOCOL.md)** - Quick start commands and protocol reference
- **[FAQ.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/FAQ.md)** - Answers to common questions about using MARM

### **MCP Server Installation**

- **[INSTALL-DOCKER.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-DOCKER.md)** - Docker deployment (recommended)
- **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md)** - Windows installation guide
- **[INSTALL-MACOS.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-MACOS.md)** - macOS installation guide
- **[INSTALL-LINUX.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-LINUX.md)** - Linux installation guide
- **[INSTALL-PLATFORMS.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-PLATFORMS.md)** - Platform installation guide

### **Project Information**

- **[CONTRIBUTING.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/CONTRIBUTING.md)** - This file - how to contribute to MARM
- **[CHANGELOG.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/CHANGELOG.md)** - Version history and updates
- **[ACKNOWLEDGMENTS.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/ACKNOWLEDGMENTS.md)** - Contributors and acknowledgments
- **[ROADMAP.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/ROADMAP.md)** - Planned features and development roadmap
- **[LICENSE](https://github.com/Lyellr88/marm-memory/blob/MARM-main/LICENSE)** - Apache 2.0 license terms

## Agent Instructions

Instructions for AI coding agents working on this repo. Keep changes surgical: touch only what the task requires, match existing style, preserve behavior in refactors.

### Architecture

MARM is a local-first MCP memory server: Python FastAPI in `marm-mcp-server/`, package `marm_mcp_server/`.

- **16 public MCP tools**: 8 core memory, 6 code graph, 2 concept graph. HTTP and STDIO must stay in exact parity.
- **HTTP transport**: `marm_mcp_server/server.py`; tools are whitelisted in `MCP_TOOL_OPERATIONS`. A tool not in that list does not exist over HTTP.
- **STDIO transport**: `marm_mcp_server/server_stdio.py` owns the `FastMCP` app and eight core `@mcp.tool()` wrappers. Graph/concept bodies live in `services/stdio_graph_tools.py` and are explicitly registered after the core tools so `tools/list` order stays stable. Never fork behavior between transports.
- **Endpoint logic** lives in `marm_mcp_server/endpoints/` split by surface (memory, logging, notebook, session, compaction, distill, graph, code_context, concepts, system). Shared helpers stay in `core/`.
- **Storage**: SQLite WAL at `~/.marm/marm_memory.db` (connection pool, FTS5 external-content index `memories_fts`, `memory_chunks` for long-memory chunking). The concept graph uses its own database `~/.marm/index/marm_index.db` with its own pool. Never share connections between the two.
- **Write path**: all memory writes go through the serialized async write queue (one worker). Do not add write paths that bypass it. `marm_log_entry` dual-writes: a `log_entries` row plus a semantic memory in `memories` (via the queue); a semantic-store failure must never fail the log write.
- **Code graph**: a pinned external binary (codebase-memory-mcp) supervised as a child process over newline-delimited JSON-RPC (`core/graph_supervisor.py`, `core/graph_client.py`). It starts lazily and runs degraded on failure. Graph or concept failures must never break the 8 core memory tools.
- **Both graphs index themselves**, on by default, one background worker each on both transports. Concept extraction is queue-driven: a write enqueues a durable outbox row in the same transaction as the memory (`core/concept_worker.py`). Code indexing is watcher-driven: a filesystem watcher (`core/graph_index_watcher.py`) wakes the worker on a real change, debounced so a burst of edits becomes one re-index, and a periodic git-signature reconciliation pass catches missed events and covers non-git or unwatchable directories (`core/graph_index_worker.py`). Neither may be made to block a write, a recall, or startup.
- **Cross-process serialization is a leased DB row, never an asyncio lock.** `core/lease_lock.py` owns the mechanics; `concept_build_lock` and `graph_index_lock` are its two bindings, deliberately separate rows. HTTP and STDIO are separate processes, so an in-process lock protects nothing. Every code-index call AND `delete_project` take the graph gate. Release is driven by the engine call's completion, not the awaiting task: `asyncio.to_thread` cancellation cancels the await and leaves the thread writing.
- **Runtime switches live in the DB, not just the environment** (`core/runtime_flags.py`). A saved override beats the env var so a Dockerfile cannot silently re-enable what a user turned off, and both workers re-read per cycle so no restart is needed. Any new background worker follows this: read the flag every cycle, and start the loop even when off so it can be turned on from another process.
- **Graph-aware recall**: `marm_smart_recall` keeps primary memory ranking authoritative and may add bounded `graph_context` from the isolated concept database. Graph enrichment is read-only and fail-open; trim graph details before primary results when enforcing response limits.
- **Distill**: `marm_distill` stages proposals and never writes a memory itself. Only an explicit `apply` writes (through the queue); a discarded proposal is never offered again.
- **Local generation** (`services/local_llm.py`): optional OpenAI-compatible backend for Distill proposals and Code Context answers. Off by default, opt-in per request, loopback-only unless an explicit remote override is set, and every failure falls back without breaking memory or code-context workflows.
- **Console**: `marm_mcp_server/console/` is the human-facing app on port 8002 (`marm-memory console`), with its frontend source in `marm-console/`. Its routes call the existing MCP tool paths for mutations instead of writing SQLite directly. Some features have a Console route beside the MCP endpoint (for example `console/endpoints/code_context.py`), so a fix to one usually needs the other.
- **Embeddings**: one fastembed `jinaai/jina-embeddings-v2-small-en` encoder (512 dimensions), lazy-loaded and serialized behind a lock. Writes must succeed even when the encoder is unavailable. Existing data requires `marm-mcp-server --migrate-embeddings` before restart when upgrading from MiniLM.

### Consistency Rules

**When adding or removing an MCP tool, update ALL of the following:**

1. `marm_mcp_server/endpoints/<surface>.py` - the implementation
2. `marm_mcp_server/server.py` - route + `MCP_TOOL_OPERATIONS` whitelist
3. `marm_mcp_server/server_stdio.py` - STDIO bootstrap/registration and matching wrapper or service path
4. `marm-mcp-server/server.json` - tools array
5. `scripts/find-tools.py` - `CANONICAL_TOOLS` list
6. Docs with full tool lists: `README.md`, `docs/PROTOCOL.md`, `docs/PROTOCOL-LITE.md`, and their `marm-mcp-server/marm_mcp_server/resources/marm-docs/` copies, plus tool counts in FAQ
7. Tests covering both transports
8. `marm_mcp_server/config/instructions.py` - the server instructions name a few tools; `tests/test_server_instructions.py` fails if one no longer exists

Then run `python scripts/find-tools.py`; every surface must report OK.

**README variants:**

- Root `README.md` is the single source of truth.
- `marm-mcp-server/README.md` is the PyPI variant (adds the `mcp-name:` header and two image divs) and is maintained separately. Every link in it is an absolute `https://github.com/Lyellr88/marm-memory/blob/MARM-main/...` URL, because neither PyPI nor GitHub resolves this file's relative paths from the repository root. Do not copy link targets into it from the root README.
- `marm-mcp-server/marm_mcp_server/resources/marm-docs/README.md` is the text-only agent-facing subset (badges, demo, and footer sections stripped) and is maintained separately. Everything under `resources/marm-docs/` is the only copy that ships in the wheel, and it is what the server indexes and serves; a copy outside the package is not packaged and resolves to nothing once installed.
- `FAQ.md`, `PROTOCOL.md`, and `PROTOCOL-LITE.md` are **plain copies**, not variants: root `docs/` is the source and the packaged copy should match it. After editing any of the three in `docs/`, resync with:

  ```bash
  cp docs/{FAQ,PROTOCOL,PROTOCOL-LITE}.md marm-mcp-server/marm_mcp_server/resources/marm-docs/
  ```

**When bumping the version, update ALL of the following** (audit with `python scripts/find-versions.py`):

1. `marm-mcp-server/pyproject.toml`
2. `marm-mcp-server/server.json` (three occurrences, including the Docker identifier)
3. `marm-mcp-server/marm_mcp_server/__init__.py` (`__version__` and docstring)
4. `marm-mcp-server/marm_mcp_server/config/settings.py` (`SERVER_VERSION`)
5. `marm-mcp-server/Dockerfile` version label and `docker-compose.yml`
6. The h1 in `README.md`, `marm-mcp-server/README.md`, and `marm-mcp-server/marm_mcp_server/resources/marm-docs/README.md` (each maintained separately), plus the example `server.json` version in `docs/INSTALL-LINUX.md` and `docs/INSTALL-WINDOWS.md`

Semver: MAJOR = breaking (schema renames, parameter removals), MINOR = new tools/parameters/features, PATCH = fixes and doc updates.

### Code Patterns

- New tool flow: implement in `endpoints/`, register the HTTP route, whitelist it, add the STDIO wrapper, then walk the consistency checklist above.
- Prefer the smallest change that solves the problem. No speculative abstractions, no config flags nobody asked for.
- Comments are minimal and only explain non-obvious "why". Never add comments that narrate what the next line does.
- Keep orchestration in the current owner file; extract modules only at real boundaries (see existing `endpoints/` split for the pattern).

### Testing

- Tests live in `marm-mcp-server/tests/`, and Console API tests in `marm-console/tests/`. Run `python scripts/run-tests.py` from the repo root; for ad hoc pytest runs, never pass a `--basetemp` inside the repository.
- Run `python scripts/test-scripts/smoke-commands.py` from the repo root for the local CLI smoke suite. It uses `smoke`, `smoke_lifecycle`, `smoke_docker`, and `smoke_destructive` markers. `--docker` and `--destructive` are explicit opt-ins; destructive mode uses a disposable virtual environment rather than the active package.
- Hit real FastAPI endpoints and real SQLite. Mock only when it meaningfully speeds the test AND matches real behavior with at least 95% fidelity.
- Every new MARM Console API route needs at least one happy-path FastAPI response-contract test with the MCP adapter stubbed. This verifies the actual response model without requiring a live graph backend.
- No existence-check or coded-to-pass tests. Deep tests that exercise real paths beat broad shallow coverage.
- `pytest.mark.skip` only for genuinely unavailable dependencies (for example, an unavailable embedding model), never for effort.

### Workflow

- **Never commit without an explicit user request.** The user reviews all changes first.
- Dev setup: `cd marm-mcp-server && pip install -e ".[dev]" && python scripts/bundle-concept-model.py`
- Benchmarks live in `scripts/benchmarking/`: `performance/bench_hotpath.py` for hot-path performance, `accuracy/locomo/run_eval.py` for LoCoMo retrieval accuracy. Do not publish performance claims neither script can back.

### Current Stats

- 16 MCP tools over HTTP + STDIO
- 3 isolated SQLite databases (memory + concept graph + analytics), no shared pools. The code graph engine owns its own store outside all three
- Hybrid recall: FTS5 BM25 exact lane + bounded semantic rerank
- Bundled concept extraction: spaCy plus the `en_core_web_sm` pipeline, both loaded lazily; Docker image includes the graph engine
- Two background indexers, both on by default: concept extraction from a durable outbox, code re-indexing from a filesystem watcher with periodic reconciliation
