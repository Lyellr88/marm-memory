# marm-graph

Code-structure graph tools for MARM / MARMIS. A thin wrapper around a **pinned**
[`codebase-memory-mcp`](https://github.com/DeusData/codebase-memory-mcp) binary
(MIT) — marm-graph owns no parser, indexer, or graph storage of its own. It spawns
the binary once as a child process, speaks its native JSON-RPC over stdio, and
re-exposes a small, marm-branded surface.

- **Full design**: `docs/current/graph-index/graph/marm-graph-spec.md`
- **Verified protocol**: `docs/current/graph-index/graph/protocol-proof.md`

> **Note:** `marm-mcp-server` now embeds marm-graph by default (`pip install
> marm-mcp-server` alone gets you both), calling these same 5 tools directly —
> no second port, no second install. This standalone package, its own HTTP/STDIO
> servers, and its Docker image are unchanged and still fully supported for
> advanced/independent use.

## What it exposes

**5 AI tools** (MCP — HTTP `/tools/*` and stdio):

| Tool | Purpose |
|---|---|
| `marm_graph_index` | Index a repo (returns its project name), or list/status |
| `marm_code_lookup` | Find symbols, grep code, or read a symbol's source (one super-tool) |
| `marm_graph_trace` | Trace call paths / data flow from a function |
| `marm_graph_architecture` | Architecture overview + graph schema |
| `marm_graph_impact` | Blast radius of code changes (git diff → affected symbols) |

**UI-only REST** (MARMIS, never in the AI's `tools/list`): `/ui/projects`,
`/ui/index_status`, `/ui/graph_schema`, `/ui/query_graph` (read-only Cypher),
`/ui/delete_project` (needs `confirm=true`), `/ui/manage_adr`, `/ui/ingest_traces`.

The MCP surface is a **whitelist** of exactly those 5 operation IDs — UI endpoints
are architecturally absent from MCP, not merely filtered.

## Run

```bash
# HTTP server (default 127.0.0.1:8003)
python -m marm_graph            # or: marm-graph

# STDIO (local MCP client)
python -m marm_graph.server_stdio
```

## Config

| Env | Default | Notes |
|---|---|---|
| `SERVER_HOST` | `127.0.0.1` | Non-loopback bind **requires** an API key or the server refuses to start |
| `SERVER_PORT` | `8003` | |
| `MARM_GRAPH_API_KEY` | _(unset)_ | Unset → loopback-only. Set → `Authorization: Bearer <key>` required |
| `CBM_BINARY_PATH` | _(unset)_ | Path to the baked binary (set in Docker); otherwise the PyPI shim is used |
| `CBM_CALL_TIMEOUT` | `300` | Per-call timeout (s) |

## Docker

```bash
docker build -t marm-graph .
docker run --rm -p 8003:8003 -e SERVER_HOST=0.0.0.0 -e MARM_GRAPH_API_KEY=yourkey marm-graph
```

The image **bakes the pinned binary at build time** — no network fetch at runtime.

## Pinning & trust boundary

The wrapped binary is the trust boundary. `codebase-memory-mcp` is pinned to an
**exact** version (`0.8.1`); its tool schemas are a fixed contract that
`tool_router` maps by hand. The binary self-reports a different version than the
pip package (`0.10.0` vs `0.8.1`) — the schema contract is the binary's, captured
live at startup. Every version bump is a reviewed change, never an auto-update.

The binary itself makes an unconditional outbound call to GitHub on every
startup (an update-availability check) via `curl`. In the shipped Docker
image this specific check cannot run: `curl` is installed only inside the
build layer (to independently verify the binary's checksum) and purged
before the layer is committed, so the binary has no `curl` to shell out to at
runtime. This does not make the container network-dead in general — the
app/runtime still has normal networking; it only closes this one upstream
call. Outside Docker (dev machines with `curl` on `PATH`), this is real
outbound traffic — expect it in egress logs.

## Tests

```bash
pip install -e ".[dev]"
pytest tests -q
```

Integration tests use the real binary and skip cleanly when it isn't available.

## Roadmap

- **Auto-indexing (v0.2, planned)** — opt-in git-based auto-reindexing. Design +
  upstream source analysis: `docs/current/graph-index/graph/auto-index-spec.md`.
