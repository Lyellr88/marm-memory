# MARM Console

MARM Console is the standalone local web app for [marm-memory](https://github.com/Lyellr88/marm-memory). It gives you a browser-based control plane for the memory system your agents use: operational health, memories and sessions, extracted knowledge, and indexed code projects.

Console runs locally. It does not send your memory database to a hosted service and does not add MCP tools to `marm-mcp-server`.

> Status: active development. The backend provides live memory, knowledge, project-intelligence, and runtime-settings routes. The production UI is bundled with `marm-mcp-server`; contributor development remains in this directory.

## What It Is

MARM Console is a separate localhost application that reads the same local MARM data stores as the MCP server.

- `marm-mcp-server` remains the agent-facing MCP server, normally on port `8001`.
- MARM Console owns the human-facing REST API on port `8002`.
- The browser frontend runs separately during development and calls the Console API.

## Workspaces

- **Overview** shows local runtime reachability, memory and concept health, indexed-project context, and compaction activity.
- **Memories** manages stored memories, notebook entries, logs, sessions, and compaction candidates. Destructive bulk actions require an explicit in-app confirmation.
- **Knowledge Graph** provides separate Memory and Code Explorers: inspect extracted entities and relationships by project or session, review potential duplicates with provenance, manage concept builds, and explore a bounded file-import topology for an indexed repository. The Code Explorer remains independent of memory-derived concepts.
- **Indexed Projects** indexes an existing local repository and shows graph size and health.
- **Project Explorer** provides per-project code intelligence: Architecture (with rows that expand inline into a file's direct imports/importers), Impact, Coverage, Decisions (an editable architecture decision record), and Runtime traces. Code search and symbol tracing are combined into one `Ctrl+K` command palette.
- **System** covers Health, Controls, Maintenance, and Diagnostics: runtime status, automatic-indexing controls, backups, doctor diagnostics, runtime logs, compaction dry-runs, and upgrade checks.
- **Settings** (dialog) manages the Console connection and reports runtime, write-queue, automatic-indexing, storage/model, and project-watch health. Its automatic-indexing controls use MARM's existing durable runtime flags.

Console currently indexes existing local directories. GitHub URL cloning, private-repository credentials, and remote polling are planned separately and are not accepted as repository paths.

## Terminal

A real shell, backed by a native PTY (ConPTY on Windows, `pty`/`termios` on Linux and macOS), runs in a dock at the bottom of the Console and is reachable from any page, not just one tab — toggle it with the terminal button in the top-right corner or `Ctrl+\``. It is off by default; set `MARM_CONSOLE_TERMINAL=1` to enable it, and it refuses to run unless the Console is bound to loopback.

- Multiple sessions per dock, up to 10, each an independent PTY.
- Resizable (drag the top edge) and can be minimized without losing the session.
- A session survives closing the dock or refreshing the page: the backend detaches rather than kills the shell on disconnect, buffers its output, and replays it on reattach. A session is only killed after 10 minutes with nothing reattached, or when its tab is explicitly closed.
- Settings (font, cursor, clipboard, scrollback, bell), keyboard shortcuts, and search (`Ctrl+F` in the terminal) are available from the dock header.
- A first-run guide walks through picking an OS and installing/launching Claude Code, Codex, or Antigravity CLI, with per-OS install commands and a dependency check for Node.js/npm and Git. It reappears on every launch unless "Don't launch on startup" is checked.

## Run Console

- Python 3.10+

```powershell
pip install -U marm-mcp-server
marm-memory console
```

This starts or reuses the managed MARM runtime, serves Console at `http://127.0.0.1:8002`, and opens it in your browser. The packaged path does not require Node or pnpm.

## Build From Source

Contributors need Python 3.10+, Node.js 20+ or newer, and pnpm 10+.

For development, run one command from this directory:

```powershell
.\run-dev.ps1
```

The launcher creates the local Python environment, installs missing frontend dependencies, starts the Console API on `127.0.0.1:8002`, and starts the frontend dev server. It stops the API when you stop the frontend.

## Development Configuration

`run-dev.ps1` creates `.venv` when needed, installs MARM from the sibling `marm-mcp-server` checkout, installs frontend dependencies, starts the Console API with `marm_mcp_server.console.cli --serve`, and stops that API when the Vite development server exits.

The Console adapter reaches MARM MCP at `http://127.0.0.1:8001` by default. Set `MARM_MCP_URL` when the runtime is elsewhere. When the MCP server requires bearer authentication, start the Console with the same `MARM_API_KEY`.

To run the frontend by itself after dependencies are installed:

```powershell
cd marm-console
pnpm --filter @workspace/marm-console dev
```

The frontend defaults to the Console API at `http://127.0.0.1:8002`.

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
| `GET`, `POST`, `DELETE /api/sessions` | Session activity, creation, and deletion; selected-session bulk deletion is also available |
| `GET`, `DELETE /api/logs` | Recent log records and confirmed deletion; selected-log bulk deletion is also available |
| `GET`, `POST`, `DELETE /api/notebook` | Notebook records and confirmed write/delete actions; selected-entry bulk deletion is also available |
| `GET /api/summaries/{session}`; `POST /api/summaries/{session}/generate` | Cached session summary and summary generation |
| `GET /api/compaction` | Compaction pipeline history and per-candidate actions |
| `/api/concepts/*` | Concept summary, graph, search, neighborhood, duplicate review, build lifecycle, and graph reset routes |
| `/api/projects/*` | Local-repository indexing, job status, project health, delete, architecture, bounded graph snapshots and file neighborhoods, code search, trace, impact, coverage, decisions, and runtime trace routes |
| `GET /api/settings/runtime` | Runtime, queue, graph, storage, embedding, automation, and watch-health diagnostics |
| `PUT /api/settings/automation` | Enable or pause durable automatic code or concept indexing |
| `GET /api/terminal/status` | Whether the terminal is enabled and available, and its backend/shell |
| `WS /api/terminal/ws` | Interactive PTY session: spawn, attach (reattach after disconnect), input, resize, kill |
| `POST /api/terminal/check` | Run a command outside the interactive stream (dependency checks) |

`GET /api/memories` supports `q`, `session`, `project`, `platform`, `context_type`, `compaction_role`, `limit`, and `offset` query parameters. Results are capped at 200 records per request.

## Development Notes

- Keep frontend source and contributor tooling inside this directory. The packaged Python host lives under `marm_mcp_server.console`.
- Treat the archived dashboard source as read-only reference material.
- The Console must degrade cleanly when MARM data has not been initialized or optional knowledge/code graph data is unavailable.

## Near-Term Direction

- Keep the packaged, Node-free release path aligned with the production Console frontend.
- Add durable index-run history only when the backend can restore real run state across reloads and restarts.
- Design GitHub repository indexing as a managed public checkout workflow before adding remote access or credentials.
- Expand MCP controls only where the server has a real, safe operation to expose.

MARM Console is designed to become the local control plane for marm-memory, while leaving the MCP server focused on agent workflows.
