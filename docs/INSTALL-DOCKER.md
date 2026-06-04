# MARM MCP Server - Docker Installation

## Universal Memory Intelligence Platform for AI Agents

**MARM v2.9.1** - Memory Accurate Response Mode
*Docker deployment guide for Windows, Mac, and Linux*

---

## Table of Contents

- [Quick Start (2 Minutes)](#quick-start-2-minutes)
- [Installation Options](#installation-options)
- [Client Connections](#client-connections)
- [Management Commands](#management-commands)
- [Verification & Testing](#verification--testing)
- [Updating & Reinstalling](#updating--reinstalling)
- [Troubleshooting](#troubleshooting)
- [Configuration](#configuration)
- [System Requirements](#system-requirements)

---

## Quick Start (2 Minutes)

**🚀 Fastest Path to MARM Memory:**

1. **Generate a key**: `docker run --rm lyellr88/marm-mcp-server:latest --generate-key`
2. **Pull & Run**: Choose Docker Run or Docker Compose below (include your key as `MARM_API_KEY`)
3. **Connect Claude**: `claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"`
4. **Test**: Ask Claude to recall a memory — MARM initializes automatically on the first tool call

**That's it!** You now have AI memory that saves across sessions and platforms.

---

## Installation Options

### Host Mode Quick Reference

| Mode | Who Can Connect | Key Required | Best For |
|---|---|---|---|
| HTTP `127.0.0.1` | Same computer only | No | Simple local pip use |
| HTTP `0.0.0.0` | Network, proxy, tunnel, shared clients | Yes | Shared server or multi-agent use |
| STDIO | Launching MCP client process only | No | Private local agent use |
| Docker HTTP | Host/clients through mapped port | Yes | Always-on server or multi-agent use |
| Docker STDIO | Launching MCP client process only | No | Private containerized local use |

**Choosing a Docker mode:** use **Docker HTTP** for shared or multi-agent workflows because one long-running MARM server coordinates database access. Use **Docker STDIO** for private single-agent or light local use; running many STDIO containers against the same mounted SQLite database can hit normal SQLite write-lock contention.

### **Option 1: Docker Run (Recommended for Testing)**

**Best for:** First-time users, quick testing, simple setup

> **Docker always requires an API key.** Docker's bridge network means the server sees requests from a gateway IP (172.x.x.x), not 127.0.0.1 — even when you're on the same machine. Generate a key using the container itself — no pip install needed:
> ```bash
> docker run --rm lyellr88/marm-mcp-server:latest --generate-key
> ```

```bash
# Pull the latest image
docker pull lyellr88/marm-mcp-server:latest

# Local use (host-only access)
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest

# Remote/network access
docker run -d --name marm-mcp-server \
  -p 8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest
```

**Why choose this:**

- **One command and done** - no extra files to create
- **Easy to understand** - you can see exactly what's happening
- **Simple troubleshooting** - fewer moving parts
- **Perfect for trying MARM** - get up and running in 30 seconds

### **Option 2: Docker Compose (Recommended for Regular Use)**

**Best for:** Regular users, developers, permanent setups

Create a `docker-compose.yml` file:

```yaml
version: '3.8'
services:
  marm-mcp-server:
    image: lyellr88/marm-mcp-server:latest
    ports:
      - "127.0.0.1:8001:8001"   # Change to "8001:8001" for remote access
    restart: unless-stopped
    volumes:
      - ~/.marm:/home/marm/.marm
    environment:
      - SERVER_HOST=0.0.0.0
      - MARM_API_KEY=your-generated-key   # Required — see note above
```

```bash
docker-compose up -d
```

**Why choose this:**

- **Automatic restarts** - if your computer reboots, MARM starts automatically
- **Easier management** - stop/start with simple commands
- **Persistent settings** - your configuration is saved in a file
- **Organized setup** - clean configuration management

### **Swarm / Multi-Agent Mode**

For shared HTTP servers running multiple AI agents simultaneously, append a preset flag after the image name:

```bash
# --swarm: write queue on, 200 RPM — recommended starting point
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest --swarm

# --swarm-max: write queue on, 600 RPM — heavier load
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest --swarm-max

# --trusted: write queue on, rate limiting disabled — private/trusted only
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest --trusted
```

| Preset | Rate Limit | Write Queue | Use When |
|--------|------------|-------------|----------|
| `--swarm` | 200 RPM | enabled | Normal multi-agent shared server |
| `--swarm-max` | 600 RPM | enabled | Heavier private swarm testing |
| `--trusted` | disabled | enabled | Trusted private deployments only |

---

## Client Connections

### **Available Endpoints**

- **HTTP MCP**: `http://localhost:8001/mcp` (Standard)
- **Health Check**: `http://localhost:8001/health`
- **Readiness Check**: `http://localhost:8001/ready`
- **API Documentation**: `http://localhost:8001/docs`

### **Claude Code**

**HTTP Connection with API key (Docker installs):**

```bash
claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
```

**Or via Claude Code JSON config** (`~/.claude.json` for user scope, `.mcp.json` for project scope):

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

**Note**: Claude Code currently supports HTTP, SSE, and STDIO through `claude mcp add`; use HTTP for MARM.

### **VS Code MCP / GitHub Copilot Agent**

Verified with VS Code's native MCP support. Add this to `.vscode/mcp.json` in your workspace, then start `marm-memory-docker` from the inline **Start** action.

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "marm-api-key",
      "description": "MARM API Key for Docker or exposed server mode",
      "password": true
    }
  ],
  "servers": {
    "marm-memory-docker": {
      "type": "http",
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer ${input:marm-api-key}"
      }
    }
  }
}
```

VS Code will prompt for the key on first start and store it securely. MARM tools are available to Copilot Agent and VS Code extensions that consume VS Code's native MCP registry.

### **Cursor**

Verified with Cursor MCP. Add this to `.cursor/mcp.json` in your workspace. Cursor reads `MARM_API_KEY` from the environment for Docker/key mode.

```json
{
  "mcpServers": {
    "marm-memory-docker": {
      "type": "http",
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer ${env:MARM_API_KEY}"
      }
    }
  }
}
```

Set the key before launching Cursor:

```powershell
$env:MARM_API_KEY="your-generated-key"
cursor .
```

### **Codex CLI**

Codex uses `codex mcp add` or TOML config at `~/.codex/config.toml`, not `settings.json`.

```powershell
$env:MARM_API_KEY="your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
```

Equivalent TOML:

```toml
[mcp_servers."marm-memory"]
url = "http://localhost:8001/mcp"
enabled = true
bearer_token_env_var = "MARM_API_KEY"
```

### **xAI / Grok Remote MCP**

xAI's official Grok MCP integration uses Remote MCP Tools through the xAI API. Only Streaming HTTP and SSE transports are supported.

Because xAI connects to the MCP server from its own infrastructure, `localhost` will not work for Grok Remote MCP. Expose MARM behind HTTPS and set `MARM_API_KEY`.

```json
{
  "type": "mcp",
  "server_url": "https://your-marm-domain.example.com/mcp",
  "server_label": "marm-memory",
  "authorization": "Bearer your-generated-key"
}
```

### **Gemini CLI**

Gemini CLI supports STDIO, SSE, and streamable HTTP MCP transports. Use HTTP for MARM.

```bash
gemini mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
```

Equivalent `~/.gemini/settings.json` or project `.gemini/settings.json`:

```json
{
  "mcpServers": {
    "marm-memory": {
      "httpUrl": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer your-generated-key"
      }
    }
  }
}
```

### **Qwen Code**

Qwen Code supports STDIO, SSE, and streamable HTTP MCP transports. Use HTTP for MARM. Project scope writes to `.qwen/settings.json`; user scope writes to `~/.qwen/settings.json`.

```bash
# Direct Python install — no key needed
qwen mcp add --transport http marm-memory http://localhost:8001/mcp

# Docker or SERVER_HOST=0.0.0.0 — key required
qwen mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
```

Equivalent `.qwen/settings.json` or `~/.qwen/settings.json`:

```json
{
  "mcpServers": {
    "marm-memory": {
      "httpUrl": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer your-generated-key"
      }
    }
  }
}
```

---

## Management Commands

### **Docker Run Commands**

**Rotate / Remove API Key:**

Removing an MCP client entry, such as `claude mcp remove marm-memory`, removes the client-side connection config only. It does not change the key used by the running Docker HTTP server.

To rotate the Docker HTTP key:

```bash
# 1. Generate a new key
docker run --rm lyellr88/marm-mcp-server:latest --generate-key

# 2. Recreate the HTTP container with the new key
docker stop marm-mcp-server
docker rm marm-mcp-server
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-new-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest

# 3. Re-add or update your MCP client with the same new key
claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-new-generated-key"
```

Docker STDIO has no server API key because it does not expose HTTP. To reset a STDIO client, remove the MCP client entry and add it again with the desired Docker command.

**Stop and Remove:**

```bash
docker stop marm-mcp-server
docker rm marm-mcp-server
```

**View Logs:**

```bash
docker logs marm-mcp-server
docker logs -f marm-mcp-server  # Follow logs live
```

### **Docker Compose Commands**

**Stop:**

```bash
docker-compose down
```

**Update to Latest:**

```bash
docker-compose pull
docker-compose up -d
```

**View Logs:**

```bash
docker-compose logs marm-mcp-server
docker-compose logs -f marm-mcp-server  # Follow logs live
```

**Complete Removal:**

```bash
docker-compose down -v  # Removes volumes (⚠️ deletes all memory data)
docker rmi lyellr88/marm-mcp-server:latest  # Removes image
```

---

## Verification & Testing

### **Health Check**

```bash
docker logs marm-mcp-server | head -20
```

**Look for these success indicators:**

```txt
Semantic search model loaded successfully
MARM documentation database ready!
MARM MCP Server initialization complete
Uvicorn running on http://0.0.0.0:8001  (inside container — normal)
```

For a live endpoint check:

```bash
curl http://localhost:8001/health
```

---

## Updating & Reinstalling

**Docker Update:**

```bash
docker pull lyellr88/marm-mcp-server:latest
docker stop marm-mcp-server
docker rm marm-mcp-server
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest
```

---

### **Migration Notes**

- Database schema is compatible - no migration needed
- New tools automatically available after restart
- Docker images are backward compatible with persistent volumes

**Data Preservation:**

- All memories stored in `~/.marm/marm_memory.db`
- Notebooks stored in same database
- Analytics data stored in `/app/data/marm_usage_analytics.db` (inside container)

---

## Troubleshooting

### **Container Won't Start**

```bash
# Check what went wrong
docker logs marm-mcp-server

# Check if port is in use
docker ps | grep 8001
```

### **Common Docker Issues**

- **Port 8001 busy**: Change to `-p 8002:8001` in run command
- **Permission denied**: Use `sudo` (Linux) or run as Administrator (Windows)
- **Out of disk space**: Run `docker system prune`

### **Common Docker Auth Pitfalls**

- **401 Unauthorized with key set**: Verify the key exactly matches container `MARM_API_KEY` and that you did not include angle brackets (`< >`) around it.
- **Tools not discovered / mixed behavior**: Remove duplicate MCP entries pointing to the same URL, especially a non-auth entry alongside bearer-token entry.
- **Key seems ignored**: Export/set `MARM_API_KEY` before launching your MCP client process; restart VS Code/Codex/CLI after setting it.
- **OAuth popup appears**: For this Docker HTTP setup, use bearer header auth (`Authorization: Bearer ...`) and cancel OAuth registration prompts.
- **Container is healthy but MCP still fails**: Health checks do not validate auth; a healthy container can still return `401` until header and key match.

### **Still Having Issues?**

Check container logs for detailed error output:

```bash
docker logs marm-mcp-server
```

---

## Configuration

### **Environment Variables (Advanced)**

For custom configuration, add environment variables to your Docker commands:

**Docker Run:**

```bash
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e SERVER_PORT=8001 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest
```

**Docker Compose:**

```yaml
version: '3.8'
services:
  marm-mcp-server:
    image: lyellr88/marm-mcp-server:latest
    ports:
      - "8002:8002"  # Custom port
    restart: unless-stopped
    volumes:
      - ~/.marm:/home/marm/.marm
    environment:
      - SERVER_PORT=8002
```

### **Available Environment Variables**

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_HOST` | `127.0.0.1` | Bind address. Must be `0.0.0.0` inside Docker for port mapping to work. |
| `SERVER_PORT` | `8001` | Server port. |
| `MARM_API_KEY` | _(unset)_ | Required for all Docker deployments (local and remote). Docker bridge networking means the server never sees 127.0.0.1 from the host — set this or all MCP calls will 401. Generate with `docker run --rm lyellr88/marm-mcp-server:latest --generate-key`. |
| `MARM_RATE_LIMIT_RPM` | `80` | HTTP rate limit (requests per minute per client IP). Set to `0` to disable. Overridden by `--swarm`, `--swarm-max`, `--trusted` presets. |
| `MAX_QUEUE_SIZE` | `100` | Write queue size when `WRITE_QUEUE_ENABLED=1`. |
| `WRITE_QUEUE_ENABLED` | `1` | Serialized memory write queue. Set to `0` only for debugging/direct-write comparisons. |
| `MARM_ANALYTICS_DB_PATH` | `/app/data/marm_usage_analytics.db` | Override analytics database path. |
| `MARM_DB_PATH` | `/home/marm/.marm/marm_memory.db` | Override primary memory database path. |
| `MARM_STDIO_LOG_LEVEL` | `INFO` | STDIO log verbosity (useful when running STDIO mode). |
| `MARM_STDIO_LOG_DIR` | `/home/marm/.marm/logs` | Override STDIO log directory. |

---

## System Requirements

### **Docker Requirements**

- **Docker Engine**: 20.10+ (or Docker Desktop)
- **Memory**: 1GB RAM available for container
- **Storage**: ~2GB for image + data
- **Network**: Internet connection for initial image pull

### **Platform Support**

- **Windows 10/11** (Docker Desktop)
- **macOS** (Docker Desktop - Intel & Apple Silicon)
- **Linux** (Docker Engine or Docker Desktop)
- **WSL2** (Windows Subsystem for Linux)*

---

## Related Docs

- [MCP-HANDBOOK.md](../MCP-HANDBOOK.md) - MCP tool usage and workflows
- [INSTALL-WINDOWS.md](INSTALL-WINDOWS.md) - Native Windows installation
- [INSTALL-LINUX.md](INSTALL-LINUX.md) - Native Linux installation
- [INSTALL-PLATFORMS.md](INSTALL-PLATFORMS.md) - Platform and API integration
