# MARM MCP Server - macOS Installation

This is the recommended native macOS path. It uses `uv` to manage MARM's Python environment, so it does not depend on the Python versions already installed on your Mac.

## Quick Start

Install [Homebrew](https://brew.sh/) if needed, then run:

```bash
brew install uv
uv tool install --python 3.12 marm-mcp-server
marm-memory init --g-claude --g-codex --g-gemini
```

If `uv` says that `marm-memory` is not on your `PATH`, run this once and open a new terminal:

```bash
uv tool update-shell
```

Then tell your connected agent: **"Use the marm-init skill to set up MARM."** It will guide the remaining HTTP or STDIO connection setup.

## Start MARM Yourself

To start the local HTTP server and Console:

```bash
marm-memory fast-start-http
```

Then connect a client:

```bash
claude mcp add --transport http marm-memory http://localhost:8001/mcp
codex mcp add marm-memory --url http://localhost:8001/mcp
```

For a private local STDIO connection instead:

```bash
claude mcp add --transport stdio marm-memory-stdio marm-mcp-stdio
codex mcp add marm-memory-stdio -- marm-mcp-stdio
```

## Update or Troubleshoot

```bash
uv tool upgrade marm-mcp-server
marm-memory doctor
```

If a native dependency does not install cleanly, use the [Docker installation guide](INSTALL-DOCKER.md) and open an issue with your macOS version, whether the Mac is Apple silicon or Intel, `uv --version`, and the full install error.
