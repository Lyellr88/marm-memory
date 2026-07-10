# MARM Systems - Agent Instructions

Instructions for AI coding agents working on this repo. Keep changes surgical: touch only what the task requires, match existing style, preserve behavior in refactors.

## Architecture

MARM is a local-first MCP memory server: Python FastAPI in `marm-mcp-server/`, package `marm_mcp_server/`.

- **14 public MCP tools**: 7 core memory, 5 code graph, 2 concept graph. HTTP and STDIO must stay in exact parity.
- **HTTP transport**: `marm_mcp_server/server.py`; tools are whitelisted in `MCP_TOOL_OPERATIONS`. A tool not in that list does not exist over HTTP.
- **STDIO transport**: `marm_mcp_server/server_stdio.py`; thin `@mcp.tool()` wrappers that call the same core logic as HTTP. Never fork behavior between transports.
- **Endpoint logic** lives in `marm_mcp_server/endpoints/` split by surface (memory, logging, notebook, session, compaction, graph, concepts, system). Shared helpers stay in `core/`.
- **Storage**: SQLite WAL at `~/.marm/marm_memory.db` (connection pool, FTS5 external-content index `memories_fts`, `memory_chunks` for long-memory chunking). The concept graph uses its own database `~/.marm/index/marm_index.db` with its own pool. Never share connections between the two.
- **Write path**: all memory writes go through the serialized async write queue (one worker). Do not add write paths that bypass it.
- **Code graph**: a pinned external binary (codebase-memory-mcp) supervised as a child process over newline-delimited JSON-RPC (`core/graph_supervisor.py`, `core/graph_client.py`). It starts lazily and runs degraded on failure. Graph or concept failures must never break the 7 core memory tools.
- **Embeddings**: one fastembed `all-MiniLM-L6-v2` encoder, lazy-loaded, serialized behind a lock. Writes must succeed even when the encoder is unavailable.

## Consistency Rules

**When adding or removing an MCP tool, update ALL of the following:**

1. `marm_mcp_server/endpoints/<surface>.py` - the implementation
2. `marm_mcp_server/server.py` - route + `MCP_TOOL_OPERATIONS` whitelist
3. `marm_mcp_server/server_stdio.py` - STDIO wrapper
4. `marm-mcp-server/server.json` - tools array
5. `scripts/find-tools.py` - `CANONICAL_TOOLS` list
6. Docs with full tool lists: `README.md`, `docs/PROTOCOL.md`, `docs/PROTOCOL-LITE.md`, and their `marm-mcp-server/marm-docs/` copies, plus tool counts in FAQ
7. Tests covering both transports

Then run `python scripts/find-tools.py`; every surface must report OK.

**README mirrors are generated, never hand-edited:**

- Root `README.md` is the single source of truth.
- `marm-mcp-server/README.md` is the PyPI variant (adds the `mcp-name:` header and two image divs).
- `marm-mcp-server/marm-docs/README.md` is the text-only agent-facing subset (badges, demo, and footer sections stripped).
- After any root README change, regenerate both mirrors: `python scripts/make-readme-mirrors.py`. `marm-mcp-server/marm-docs/FAQ.md` is likewise a copy of `docs/FAQ.md`; edit the docs copy and sync.

**When bumping the version, update ALL of the following** (audit with `python scripts/find-versions.py`):

1. `marm-mcp-server/pyproject.toml`
2. `marm-mcp-server/server.json` (three occurrences, including the Docker identifier)
3. `marm_mcp_server/__init__.py` (`__version__` and docstring)
4. `marm_mcp_server/config/settings.py` (`SERVER_VERSION`)
5. `marm_mcp_server/server.py` docstring
6. `marm-mcp-server/Dockerfile` version label and `docker-compose.yml`
7. Root `README.md` h1 (then regenerate mirrors) and the version headers in `docs/INSTALL-*.md`

Semver: MAJOR = breaking (schema renames, parameter removals), MINOR = new tools/parameters/features, PATCH = fixes and doc updates.

## Code Patterns

- New tool flow: implement in `endpoints/`, register the HTTP route, whitelist it, add the STDIO wrapper, then walk the consistency checklist above.
- Prefer the smallest change that solves the problem. No speculative abstractions, no config flags nobody asked for.
- Comments are minimal and only explain non-obvious "why". Never add comments that narrate what the next line does.
- Keep orchestration in the current owner file; extract modules only at real boundaries (see existing `endpoints/` split for the pattern).

## Testing

- Tests live in `marm-mcp-server/tests/`; run with `pytest` from `marm-mcp-server/`.
- Hit real FastAPI endpoints and real SQLite. Mock only when it meaningfully speeds the test AND matches real behavior with at least 95% fidelity.
- No existence-check or coded-to-pass tests. Deep tests that exercise real paths beat broad shallow coverage.
- `pytest.mark.skip` only for genuinely unavailable dependencies (no embedding model, no spaCy `[concepts]` extra), never for effort.

## Workflow

- **Never commit without an explicit user request.** The user reviews all changes first.
- Dev setup: `cd marm-mcp-server && pip install -e ".[dev,concepts]" && python -m spacy download en_core_web_sm`
- Benchmarks are reproducible via `marm-mcp-server/scripts/bench_hotpath.py`; do not publish performance claims that script cannot back.

## Current Stats (v2.19.0)

- 14 MCP tools over HTTP + STDIO
- 2 isolated SQLite databases (memory + concept graph)
- Hybrid recall: FTS5 BM25 exact lane + bounded semantic rerank, ~20ms median at N=10,000
- Optional extras: `[concepts]` (spaCy extraction), Docker image with the graph engine baked in
