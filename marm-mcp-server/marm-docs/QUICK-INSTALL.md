# Full Installation & Configuration

## Docker (Fastest - 30 seconds)

> **Docker always requires `MARM_API_KEY`** — even for local use. Docker's bridge network means the server sees a gateway IP, not localhost. Generate a key using the container itself — no pip install needed.

```bash
# Step 1: generate your key (run once)
docker run --rm lyellr88/marm-mcp-server:latest python -m marm_mcp_server --generate-key

# Step 2: start the container
docker pull lyellr88/marm-mcp-server:latest
docker run -d --name marm-mcp-server -p 127.0.0.1:8001:8001 -e SERVER_HOST=0.0.0.0 -e MARM_API_KEY=your-generated-key -v ~/.marm:/home/marm/.marm lyellr88/marm-mcp-server:latest

# Step 3: connect your client
claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
```

---

**Quick Local http Install:**

Default pip/local startup is zero-config: MARM binds to localhost and does not require a key unless you expose it with `SERVER_HOST=0.0.0.0`.

```bash
pip install marm-mcp-server
pip install -r marm-mcp-server/requirements.txt
python -m marm_mcp_server
claude mcp add --transport http marm-memory http://localhost:8001/mcp
```

**Http Manual JSON Configuration** (Docker — key required):

```json
{
  "mcpServers": {
    "marm-memory": {
      "type": "http",
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer your-generated-key"
      }
    }
  }
}
```

**Http Manual JSON Configuration** (direct Python install — no key needed):

```json
{
  "mcpServers": {
    "marm-memory": {
      "type": "http",
      "url": "http://localhost:8001/mcp"
    }
  }
}
```

**Codex CLI Configuration** (`~/.codex/config.toml`):

```bash
# Direct Python install — no key needed
codex mcp add marm-memory --url http://localhost:8001/mcp

# Docker or exposed server — key required
$env:MARM_API_KEY="your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
```

```toml
[mcp_servers."marm-memory"]
url = "http://localhost:8001/mcp"
enabled = true
bearer_token_env_var = "MARM_API_KEY"
```

For Gemini CLI, use `gemini mcp add --transport http marm-memory http://localhost:8001/mcp` for local pip installs, or add `--header "Authorization: Bearer your-generated-key"` for Docker/key mode.

For VS Code, add MARM to `.vscode/mcp.json` using `"type": "http"` and `"url": "http://localhost:8001/mcp"`, then click **Start** in the MCP config editor. VS Code MCP is verified with Copilot Agent and extensions that use VS Code's native MCP registry.

For Cursor, add MARM to `.cursor/mcp.json` using `"mcpServers"`, `"type": "http"`, and `"url": "http://localhost:8001/mcp"`. Cursor MCP is verified with MARM over HTTP.

For Qwen Code:

```bash
# Direct Python install — no key needed
qwen mcp add --transport http marm-memory http://localhost:8001/mcp

# Docker or exposed/server mode — key required
qwen mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
```

For xAI/Grok Remote MCP guidance, see `INSTALL-DOCKER.md`.

---

## Authentication

### Host Mode Quick Reference

| Mode | Who Can Connect | Key Required | Best For |
|---|---|---|---|
| HTTP `127.0.0.1` | Same computer only | No | Simple local pip use |
| HTTP `0.0.0.0` | Network, proxy, tunnel, shared clients | Yes | Shared server or multi-agent use |
| STDIO | Launching MCP client process only | No | Private local agent use |
| Docker HTTP | Host/clients through mapped port | Yes | Always-on server or multi-agent use |
| Docker STDIO | Launching MCP client process only | No | Private containerized local use |

**Direct Python install** (`python -m marm_mcp_server`) defaults to localhost-only — no key needed. If you expose it with `SERVER_HOST=0.0.0.0`, set `MARM_API_KEY` and pass `Authorization: Bearer your-key` from your client.

**Docker deployments always require `MARM_API_KEY`**, even for local use. Docker's bridge network means requests from your machine arrive at the container with a gateway IP (172.x.x.x), not 127.0.0.1. Generate a key using the container itself (see Docker section above), then set it with `-e MARM_API_KEY=your-key` on the server and `Authorization: Bearer your-key` in your client config.

**Roadmap:** Full OAuth 2.1 authentication is planned for a future release to support team deployments and cloud environments.

---

## STDIO Transport Support

The MARM MCP Server supports STDIO transport for MCP clients that require stdin/stdout communication (orchestration platforms, CLI tools, and integrated development environments).

### Step 1: Install

```bash
pip install marm-mcp-server
```

This installs the `marm-mcp-stdio` console script automatically — no separate dependency step needed.

### Step 2: Configuration

***Choose one of the two setup methods below:***

- Option 1: CLI Configuration (Recommended)

```bash
# Claude Code
claude mcp add --transport stdio marm-memory-stdio marm-mcp-stdio

# Qwen Code
qwen mcp add --transport stdio marm-memory-stdio marm-mcp-stdio

# Gemini CLI
gemini mcp add --transport stdio marm-memory-stdio marm-mcp-stdio
```

- Option 2: JSON Configuration

For IDEs and clients that require manual configuration, add this to your MCP settings file:

```json
{
  "mcpServers": {
    "marm-memory": {
      "command": "marm-mcp-stdio"
    }
  }
}
```

If `marm-mcp-stdio` isn't on your PATH (e.g. virtualenv), use the module form instead:

```json
{
  "mcpServers": {
    "marm-memory": {
      "command": "python",
      "args": ["-m", "marm_mcp_server.server_stdio"]
    }
  }
}
```

### Step 3 (Optional): Run Manually

```bash
marm-mcp-stdio
# or
python -m marm_mcp_server.server_stdio
```

The server listens on stdin/stdout for JSON-RPC 2.0 messages. No port, no API key required.

---

## Tested Supported Platforms

### HTTP

- ✅ Claude Code (Windows, macOS, Linux)
- ✅ Qwen Code (Windows, macOS, Linux)
- ✅ Gemini CLI (Windows, macOS, Linux)
- ✅ VS Code MCP / Copilot Agent (Windows)
- ✅ Cursor MCP (Windows)

### STDIO

- ✅ Claude Code (Windows, macOS, Linux)
- ✅ Qwen Code (Windows, macOS, Linux)
- ✅ Gemini CLI (Windows, macOS, Linux)
- ✅ VS Code MCP / Copilot Agent (Windows)
- ✅ Cursor MCP (Windows)

## For Other Platforms

If your platform isn't listed above:

1. **Try the JSON configuration** — most MCP clients support the standard configuration format
2. **Use AI assistance** — provide your platform name and MCP documentation to an AI assistant, which can help adapt the command pattern shown above
3. **Check platform documentation** — refer to your MCP client's documentation for STDIO transport setup

## Transport Comparison

| Feature | HTTP | STDIO |
|---------|------|-------|
| **Deployment** | Requires HTTP server | Process-based |
| **Resource Isolation** | Shared server | Per-process |
| **Platform Support** | Web-based and CLI clients | CLI/orchestration tools |
| **Setup Complexity** | Medium | Low |
| **Use Case** | Shared server, remote/network access | Local tools, automation |
| **Status** | Stable | Stable |

**Key Information:**

- **Server Endpoint**: `http://localhost:8001/mcp`
- **API Documentation**: `http://localhost:8001/docs`
- **Supported Clients**: Claude Code, Qwen Code, Gemini CLI, VS Code MCP, Cursor MCP, and any MCP-compatible LLM client or LLM platform

**All Installation Options:**

- **Docker** (Fastest): One command, works everywhere
- **Automated Setup**: One command with dependency validation  
- **Manual Installation**: Step-by-step with virtual environment
- **Quick Test**: Zero-configuration trial run

**Choose your installation method:**

| Installation Type | Guide | Best For |
|-------------------|-------|----------|
| **Docker** | **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)** | Cross-platform, production deployment |
| **Windows** | **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)** | Native Windows development |
| **Linux** | **[INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)** | Native Linux development |
| **Platforms** | **[INSTALL-PLATFORMS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORMS.md)** | App & API integration |