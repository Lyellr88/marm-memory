# marm-memory - Agent Instructions

Instructions for AI coding agents working on this repo. Keep changes surgical: touch only what the task requires, match existing style, preserve behavior in refactors.

## Architecture

MARM is a local-first MCP memory server: Python FastAPI in `marm-mcp-server/`, package `marm_mcp_server/`.

- **14 public MCP tools**: 7 core memory, 5 code graph, 2 concept graph. HTTP and STDIO must stay in exact parity.
- **HTTP transport**: `marm_mcp_server/server.py`; tools are whitelisted in `MCP_TOOL_OPERATIONS`. A tool not in that list does not exist over HTTP.
- **STDIO transport**: `marm_mcp_server/server_stdio.py` owns the `FastMCP` app and seven core `@mcp.tool()` wrappers. Graph/concept bodies live in `services/stdio_graph_tools.py` and are explicitly registered after the core tools so `tools/list` order stays stable. Never fork behavior between transports.
- **Endpoint logic** lives in `marm_mcp_server/endpoints/` split by surface (memory, logging, notebook, session, compaction, graph, concepts, system). Shared helpers stay in `core/`.
- **Storage**: SQLite WAL at `~/.marm/marm_memory.db` (connection pool, FTS5 external-content index `memories_fts`, `memory_chunks` for long-memory chunking). The concept graph uses its own database `~/.marm/index/marm_index.db` with its own pool. Never share connections between the two.
- **Write path**: all memory writes go through the serialized async write queue (one worker). Do not add write paths that bypass it. `marm_log_entry` dual-writes: a `log_entries` row plus a semantic memory in `memories` (via the queue); a semantic-store failure must never fail the log write.
- **Code graph**: a pinned external binary (codebase-memory-mcp) supervised as a child process over newline-delimited JSON-RPC (`core/graph_supervisor.py`, `core/graph_client.py`). It starts lazily and runs degraded on failure. Graph or concept failures must never break the 7 core memory tools.
- **Both graphs index themselves**, on by default, one background worker each on both transports. Concept extraction is queue-driven: a write enqueues a durable outbox row in the same transaction as the memory (`core/concept_worker.py`). Code indexing is poll-driven: a git signature per indexed repo, re-indexing on a commit and every cycle while the tree is dirty (`core/graph_index_worker.py`). Neither may be made to block a write, a recall, or startup.
- **Cross-process serialization is a leased DB row, never an asyncio lock.** `core/lease_lock.py` owns the mechanics; `concept_build_lock` and `graph_index_lock` are its two bindings, deliberately separate rows. HTTP and STDIO are separate processes, so an in-process lock protects nothing. Every code-index call AND `delete_project` take the graph gate. Release is driven by the engine call's completion, not the awaiting task: `asyncio.to_thread` cancellation cancels the await and leaves the thread writing.
- **Runtime switches live in the DB, not just the environment** (`core/runtime_flags.py`). A saved override beats the env var so a Dockerfile cannot silently re-enable what a user turned off, and both workers re-read per cycle so no restart is needed. Any new background worker follows this: read the flag every cycle, and start the loop even when off so it can be turned on from another process.
- **Graph-aware recall**: `marm_smart_recall` keeps primary memory ranking authoritative and may add bounded `graph_context` from the isolated concept database. Graph enrichment is read-only and fail-open; trim graph details before primary results when enforcing response limits.
- **Embeddings**: one fastembed `jinaai/jina-embeddings-v2-small-en` encoder (512 dimensions), lazy-loaded and serialized behind a lock. Writes must succeed even when the encoder is unavailable. Existing data requires `marm-mcp-server --migrate-embeddings` before restart when upgrading from MiniLM.

## Consistency Rules

**When adding or removing an MCP tool, update ALL of the following:**

1. `marm_mcp_server/endpoints/<surface>.py` - the implementation
2. `marm_mcp_server/server.py` - route + `MCP_TOOL_OPERATIONS` whitelist
3. `marm_mcp_server/server_stdio.py` - STDIO bootstrap/registration and matching wrapper or service path
4. `marm-mcp-server/server.json` - tools array
5. `scripts/find-tools.py` - `CANONICAL_TOOLS` list
6. Docs with full tool lists: `README.md`, `docs/PROTOCOL.md`, `docs/PROTOCOL-LITE.md`, and their `marm-mcp-server/marm_mcp_server/resources/marm-docs/` copies, plus tool counts in FAQ
7. Tests covering both transports

Then run `python scripts/find-tools.py`; every surface must report OK.

**README variants:**

- Root `README.md` is the single source of truth.
- `marm-mcp-server/README.md` is the PyPI variant (adds the `mcp-name:` header and two image divs) and is maintained separately.
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
5. `marm-mcp-server/marm_mcp_server/server.py` docstring
6. `marm-mcp-server/Dockerfile` version label and `docker-compose.yml`
7. The h1 in `README.md`, `marm-mcp-server/README.md`, and `marm-mcp-server/marm_mcp_server/resources/marm-docs/README.md` (each maintained separately), plus the version headers in `docs/INSTALL-*.md`

Semver: MAJOR = breaking (schema renames, parameter removals), MINOR = new tools/parameters/features, PATCH = fixes and doc updates.

## Code Patterns

- New tool flow: implement in `endpoints/`, register the HTTP route, whitelist it, add the STDIO wrapper, then walk the consistency checklist above.
- Prefer the smallest change that solves the problem. No speculative abstractions, no config flags nobody asked for.
- Comments are minimal and only explain non-obvious "why". Never add comments that narrate what the next line does.
- Keep orchestration in the current owner file; extract modules only at real boundaries (see existing `endpoints/` split for the pattern).

## Testing

- Tests live in `marm-mcp-server/tests/`; run with `pytest` from `marm-mcp-server/`.
- Run `python scripts/test-scripts/smoke-commands.py` from the repo root for the local CLI smoke suite. It uses `smoke`, `smoke_lifecycle`, `smoke_docker`, and `smoke_destructive` markers. `--docker` and `--destructive` are explicit opt-ins; destructive mode uses a disposable virtual environment rather than the active package.
- Hit real FastAPI endpoints and real SQLite. Mock only when it meaningfully speeds the test AND matches real behavior with at least 95% fidelity.
- Every new MARM Console API route needs at least one happy-path FastAPI response-contract test with the MCP adapter stubbed. This verifies the actual response model without requiring a live graph backend.
- No existence-check or coded-to-pass tests. Deep tests that exercise real paths beat broad shallow coverage.
- `pytest.mark.skip` only for genuinely unavailable dependencies (for example, an unavailable embedding model), never for effort.

## Workflow

- **Never commit without an explicit user request.** The user reviews all changes first.
- Dev setup: `cd marm-mcp-server && pip install -e ".[dev]" && python scripts/bundle-concept-model.py`
- Benchmarks live in `scripts/benchmarking/`: `preformance/bench_hotpath.py` for hot-path performance, `accuracy/locomo/run_eval.py` for LoCoMo retrieval accuracy. Do not publish performance claims neither script can back.

## Current Stats (v2.39.0)

- 14 MCP tools over HTTP + STDIO
- 3 isolated SQLite databases (memory + concept graph + analytics), no shared pools. The code graph engine owns its own store outside all three
- Hybrid recall: FTS5 BM25 exact lane + bounded semantic rerank
- Bundled concept extraction: spaCy plus the `en_core_web_sm` pipeline, both loaded lazily; Docker image includes the graph engine
- Two background indexers, both on by default: concept extraction from a durable outbox, code re-indexing from a git-signature poll
