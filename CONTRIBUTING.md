# Contributing to MARM Systems

Thanks for wanting to contribute. MARM is currently focused on the MCP server, local memory workflows, Docker/STDIO transports, IDE and client integrations, and the dashboard for inspecting local memory data.

This guide covers practical development workflow. For project history and community recognition, see [ACKNOWLEDGMENTS.md](docs/ACKNOWLEDGMENTS.md).

## Getting Started

```powershell
git clone https://github.com/Lyellr88/MARM-Systems.git
cd MARM-Systems
```

Install the MCP server in editable mode:

```powershell
cd marm-mcp-server
pip install -e ".[dev]"
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

## Development

### Project Structure

```text
marm-mcp-server/
  marm_mcp_server/
    server.py                  # FastAPI HTTP MCP server
    server_stdio.py            # FastMCP STDIO transport
    config/settings.py         # Paths, host/port, auth, feature flags
    core/
      memory.py                # SQLite memory and semantic search layer
      write_queue.py           # Serialized write queue for SQLite writer stability
      consolidation.py         # Content-hash and semantic write-time consolidation
      compaction.py            # Background compaction candidate detection and nudges
      events.py                # Internal event hooks
      rate_limiter.py          # Rate limiting primitives
      response_limiter.py      # MCP response size controls
      shutdown_manager.py      # Graceful shutdown handling
    endpoints/
      session.py               # Session tools
      logging.py               # Log tools
      reasoning.py             # Reasoning/deep-dive tools
      notebook.py              # Notebook tools
      memory.py                # Recall/search tools
      compaction.py            # Unified compaction tool and hidden helper routes
      system.py                # Health/system tools
    middleware/
      auth.py                  # Bearer auth for HTTP mode
      rate_limiting.py         # HTTP rate limiting middleware
    services/
      documentation.py         # Startup documentation loading
      automation.py            # Event handler registration
    utils/
      helpers.py               # Shared helpers
      security.py              # API key generation
  tests/                       # MCP server test suite
  Dockerfile                   # One image, HTTP default, STDIO override
  pyproject.toml               # Package metadata and console scripts

marm-dashboard/                # Local dashboard for inspecting MARM memory data
docs/                          # User-facing docs and project docs
scripts/                       # Local validation, release, and maintenance helpers
```

### Key Patterns

**HTTP and STDIO are separate transports**

HTTP mode lives in `marm_mcp_server/server.py` and is mounted through FastAPI/FastApiMCP at `/mcp`.

STDIO mode lives in `marm_mcp_server/server_stdio.py` and uses FastMCP over standard input/output. STDIO must keep stdout clean for JSON-RPC messages; logs and incidental `print()` output belong on stderr.

If a tool behavior changes, check whether the HTTP endpoint and STDIO tool both need the same update.

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

Do not rename fields, move data between tables, or change date/session parsing behavior without updating HTTP tools, STDIO tools, tests, smoke scripts, and docs together.

**Retired features stay retired unless re-scoped**

Current supported connection paths are HTTP and STDIO. Do not reintroduce retired transports or auth shims unless there is a new spec and implementation plan for them.

## Adding or Changing MCP Tools

1. Find the current HTTP behavior in `marm_mcp_server/endpoints/`.
2. Find the matching STDIO behavior in `marm_mcp_server/server_stdio.py`.
3. Keep request/response field names aligned where possible.
4. Prefer parameterized actions for closely related operations, following existing tools such as `marm_notebook(action=...)`, `marm_delete(type=...)`, and `marm_compaction(action=...)`.
5. Update or add focused tests in `marm-mcp-server/tests/`.
6. Update docs if the command shape, transport setup, auth behavior, or user-facing workflow changes.
7. Run the local test runner before submitting changes.

## Testing

Run the known-good local test checks from the repo root:

```powershell
python scripts\run-tests.py
```

This runs:

- Python compile check for `marm_mcp_server` and `tests`
- Pytest suite with a controlled temp directory

For targeted ad hoc pytest runs, use `--basetemp C:\tmp\...` or clean repo-local pytest artifacts afterward:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\clean-pytest-artifacts.ps1
```

Current expectations:

- `Failed: 0` required before submitting a PR
- Docker tests may skip automatically when Docker or the smoke image is unavailable
- Warnings should be reviewed, but a known dependency warning may not block a PR

Run release preflight before a push or release:

```powershell
python scripts\release-preflight.py
```

This runs the version scan, stale docs scan, known-good test runner, optional Docker smoke test, and a git status summary.

Run Docker smoke directly when changing Docker, transport setup, auth, or startup behavior:

```powershell
python scripts\test-scripts\docker-smoke.py
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
python scripts\find-versions.py
python scripts\find-dead-code.py
```

`find-versions.py` is interactive and can update active version references. It intentionally avoids changing `CHANGELOG.md` because that file contains historical versions. `find-dead-code.py` looks for unused functions and classes in the MCP server codebase. Review its findings carefully before removing any code, as some utilities may be used in dynamic ways or reserved for future features.

## Submitting Changes

MARM uses a PR-first workflow for normal development. Do not push feature, fix, or release-prep work directly to `MARM-main`.

1. Create a focused branch from `MARM-main`.
2. Keep the change scoped to one feature, fix, or doc cleanup.
3. Follow existing file patterns before adding new abstractions.
4. Run `python scripts\run-tests.py`.
5. Run Docker smoke if the change touches Docker, HTTP/STDIO startup, auth, or transports.
6. Update docs and changelog when user-facing behavior changes.
7. Push the branch and open a PR into `MARM-main`.
8. Wait for CodeRabbit and GitHub checks, then address review findings before merge.

No formal style guide beyond this: keep code readable, preserve current behavior unless the PR is explicitly changing it, and avoid broad refactors mixed into feature work.

### Branch Naming

Use short, descriptive branch names:

```text
feature/notebook-polish
fix/fastmcp-range
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
- Dashboard Docker image
- MCP Registry publish

Use normal branch pushes for review. Use tag pushes only for intentional releases.

## Project Documentation

### **Usage Guides**

- **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)** - Complete MCP server usage guide with commands, workflows, and examples
- **[PROTOCOL.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/PROTOCOL.md)** - Quick start commands and protocol reference
- **[FAQ.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/FAQ.md)** - Answers to common questions about using MARM

### **MCP Server Installation**

- **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)** - Docker deployment (recommended)
- **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)** - Windows installation guide
- **[INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)** - Linux installation guide
- **[INSTALL-PLATFORMS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORMS.md)** - Platform installation guide

### **Project Information**

- **[README.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/README.md)** - This file - ecosystem overview and MCP server guide
- **[CONTRIBUTING.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/CONTRIBUTING.md)** - How to contribute to MARM
- **[CHANGELOG.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/CHANGELOG.md)** - Version history and updates
- **[ACKNOWLEDGMENTS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ACKNOWLEDGMENTS.md)** - Contributors and acknowledgments
- **[ROADMAP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ROADMAP.md)** - Planned features and development roadmap
- **[LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/LICENSE)** - MIT license terms
