# MARM Console

MARM Console is the standalone local web app for [marm-memory](https://github.com/Lyellr88/marm-memory). It gives you a browser-based view of the memory system your agents use: memory health, sessions, scoped memory records, extracted knowledge, and indexed code projects.

Console runs locally. It does not send your memory database to a hosted service and does not add MCP tools to `marm-mcp-server`.

> Status: active development. The backend now provides live Overview, filters, memory browsing, safe memory create/edit/delete, knowledge graph reads, and project intelligence routes. Packaging and final Console parity work are still in progress.

## What It Is

MARM Console is a separate localhost application that reads the same local MARM data stores as the MCP server.

- `marm-mcp-server` remains the agent-facing MCP server, normally on port `8001`.
- MARM Console owns the human-facing REST API on port `8002`.
- The browser frontend runs separately during development and calls the Console API.
- The legacy `marm-dashboard` source is archived under `docs/archived/` for reference.

## Requirements

- Python 3.10+
- Node.js 20+ and pnpm 10+
- A local marm-memory installation that has initialized `~/.marm/marm_memory.db`

## Quick Start

For development, run one command from this directory:

```powershell
.\run-dev.ps1
```

The launcher creates the local Python environment, installs missing frontend dependencies, starts the Console API on `127.0.0.1:8002`, and starts the frontend dev server. It stops the API when you stop the frontend.

## Release Install

The user-facing release flow is intended to be one install and one command:

```powershell
pip install marm-console
marm-console
```

That packaged command is not available yet. The current commands below are implementation details for contributors while Console is under development.

## Manual Development Setup

```powershell
cd marm-console
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r server\requirements.txt
python -m server
```

The API starts at `http://127.0.0.1:8002`.

Set `MARM_DB_PATH` before starting when your memory database is not at the default location:

```powershell
$env:MARM_DB_PATH = "D:\data\marm_memory.db"
python -m server
```

The Console checks the MARM MCP server at `http://127.0.0.1:8001` by default. Set
`MARM_MCP_URL` when it runs elsewhere. When the MCP server requires bearer auth,
start the Console with the same `MARM_API_KEY`.

In a second terminal, start the frontend:

```powershell
cd marm-console
pnpm install
pnpm --filter @workspace/marm-console dev
```

Open the Vite URL shown in the terminal. The frontend defaults to the Console API at `http://127.0.0.1:8002`.

## Current API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Console process health |
| `GET /api/overview` | Bounded memory health summary |
| `GET /api/filters` | Sessions, projects, platforms, and context types |
| `GET /api/memories` | Scoped, paginated memory list |
| `GET /api/memories/{id}` | One memory record |
| `POST /api/memories` | Create a memory through the MARM write queue |
| `PUT /api/memories/{id}` | Replace editable memory fields through the MARM write queue |
| `DELETE /api/memories/{id}` | Delete one memory with typed confirmation |
| `POST /api/memories/bulk-delete` | Delete an explicit bounded memory ID list |
| `GET /api/sessions` | Session activity and counts |
| `GET /api/logs` | Recent log records |
| `GET /api/notebook` | Notebook records |
| `GET /api/summaries/{session}` | Cached session summary |
| `GET /api/compaction` | Compaction pipeline history |
| `GET /api/concepts/*` | Read-only concept graph summary, search, and neighborhood data |
| `GET /api/projects` | Indexed project list placeholder |

`GET /api/memories` supports `q`, `session`, `project`, `platform`, `context_type`, `compaction_role`, `limit`, and `offset` query parameters. Results are capped at 200 records per request.

## Development Notes

- Keep all new Console code inside this directory.
- Treat the archived dashboard source as read-only reference material.
- The Console must degrade cleanly when MARM data has not been initialized or optional knowledge/code graph data is unavailable.

## Roadmap

The implementation path is:

1. Adapt concept builds and duplicate review through the existing MARM runtime.
2. Adapt project indexing, status, architecture, code search, trace, impact, and guarded deletion through marm-graph.
3. Package the production frontend behind the standalone Console host.

MARM Console is designed to become the local control plane for marm-memory, while leaving the MCP server focused on agent workflows.
