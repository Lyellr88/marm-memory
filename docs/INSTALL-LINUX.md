# MARM MCP Server - Linux Installation

## Universal Memory Intelligence Platform for AI Agents

**MARM v2.9.1** - Memory Accurate Response Mode
*Complete Linux installation guide*

---

## Table of Contents

- [Quick Start (5 Minutes)](#quick-start-5-minutes)
- [System Requirements](#system-requirements)
- [Installation Options](#installation-options)
- [Distribution-Specific Setup](#distribution-specific-setup)
- [Client Connections](#client-connections)
- [Verification & Testing](#verification--testing)
- [Updating & Reinstalling](#updating--reinstalling)
- [Troubleshooting](#troubleshooting)
- [Configuration](#configuration)

---

## Quick Start (5 Minutes)

**🚀 Fastest Path to MARM Memory on Linux:**

1. **Install MARM**: Choose ⚡ **Quick Test** (Beginner) or ⭐ **Automated** (Easy) from options below
2. **Connect Claude**: `claude mcp add --transport http marm-memory http://localhost:8001/mcp`
3. **Test**: Ask Claude to recall a memory — MARM initializes automatically on the first tool call

**That's it!** You now have AI memory that saves across sessions and platforms.

---

## System Requirements

### **Linux Requirements**

- **OS**: Ubuntu 18.04+, Debian 10+, CentOS 8+, Fedora 30+, or any modern Linux distribution
- **Python**: 3.10 or higher
- **Memory**: 1GB RAM available
- **Storage**: ~500MB disk space
- **Network**: Internet connection for initial setup

### **Package Dependencies**

Most distributions include these by default:

- `git` - Version control
- `python3` - Python runtime
- `python3-pip` - Package manager
- `python3-venv` - Virtual environments

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

### **Option 1: pip install** ⭐ **(Recommended - Fastest)**

```bash
pip install marm-mcp-server
python3 -m marm_mcp_server
```

### **Option 2: pip install in virtualenv** ⚡ **(Clean environment)**

```bash
python3 -m venv marm-env
source marm-env/bin/activate
pip install marm-mcp-server
python3 -m marm_mcp_server
```

### **Option 3: From source with install.sh** 🔧 **(Advanced)**

```bash
git clone https://github.com/Lyellr88/MARM-Systems.git
cd MARM-Systems/marm-mcp-server
chmod +x install.sh
./install.sh
source marm-env/bin/activate
python3 -m marm_mcp_server
```

### **Multi-Agent / Swarm Mode**

For shared HTTP servers running multiple AI agents, use a preset flag:

```bash
python3 -m marm_mcp_server --swarm        # 200 RPM, write queue on
python3 -m marm_mcp_server --swarm-max    # 600 RPM, write queue on
python3 -m marm_mcp_server --trusted      # rate limiting off, write queue on
python3 -m marm_mcp_server --rate-limit-rpm 150  # custom RPM
```

### **After Installation:**

**Server starts on**: `http://localhost:8001`
**MCP Endpoint**: `http://localhost:8001/mcp`
**API Documentation**: `http://localhost:8001/docs`

---

## Distribution-Specific Setup

### **Ubuntu/Debian**

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv git
pip install marm-mcp-server
python3 -m marm_mcp_server
```

### **CentOS/RHEL/Fedora**

```bash
sudo dnf install python3 python3-pip git        # Fedora
# sudo yum install python3 python3-pip git      # CentOS/RHEL
pip install marm-mcp-server
python3 -m marm_mcp_server
```

### **Arch Linux**

```bash
sudo pacman -S python python-pip git
pip install marm-mcp-server
python3 -m marm_mcp_server
```

---

## Client Connections

### **Claude Code (Recommended)**

**HTTP Connection (Standard):**

```bash
claude mcp add --transport http marm-memory http://localhost:8001/mcp
```

**Note**: Claude Code currently supports HTTP, SSE, and STDIO through `claude mcp add`; use HTTP for MARM.

### **VS Code MCP / GitHub Copilot Agent**

Verified with VS Code's native MCP support. Add this to `.vscode/mcp.json` in your workspace. Use `marm-memory-local` for direct Python installs; use `marm-memory-docker` when running Docker or exposed/key mode.

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
    "marm-memory-local": {
      "type": "http",
      "url": "http://localhost:8001/mcp"
    },
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

Open `.vscode/mcp.json`, click **Start** above the server you want, then use Copilot Agent or any VS Code extension that consumes VS Code's native MCP registry. Third-party extensions that do not use VS Code's MCP registry may require their own setup.

### **Cursor**

Verified with Cursor MCP. Add this to `.cursor/mcp.json` in your workspace. Use `marm-memory-local` for direct Python installs; use `marm-memory-docker` when running Docker or exposed/key mode.

```json
{
  "mcpServers": {
    "marm-memory-local": {
      "type": "http",
      "url": "http://localhost:8001/mcp"
    },
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

Cursor uses `mcpServers`, not VS Code's `servers` root. For Docker/key mode, launch Cursor with `MARM_API_KEY` set in the environment.

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

### **Codex CLI**

Codex uses `codex mcp add` or TOML config at `~/.codex/config.toml`, not `settings.json`.

```bash
# Direct Python install — no key needed
codex mcp add marm-memory --url http://localhost:8001/mcp

# Docker or SERVER_HOST=0.0.0.0 — key required
export MARM_API_KEY="your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
```

```toml
[mcp_servers."marm-memory"]
url = "http://localhost:8001/mcp"
enabled = true
bearer_token_env_var = "MARM_API_KEY"
```

### **Gemini CLI**

Gemini CLI supports STDIO, SSE, and streamable HTTP MCP transports. Use HTTP for MARM.

```bash
# Direct Python install — no key needed
gemini mcp add --transport http marm-memory http://localhost:8001/mcp

# Docker or SERVER_HOST=0.0.0.0 — key required
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

## Verification & Testing

### **Quick Health Check**

```bash
# Traditional health check (still useful for quick validation)
curl -s http://localhost:8001/health
```

**Expected Health Response:**

```json
{
  "status": "healthy",
  "service": "MARM MCP Server",
  "version": "2.9.1",
  "timestamp": "2026-01-01T00:00:00+00:00",
  "database": "connected",
  "semantic_search": "available"
}
```

---

## Updating & Reinstalling

### **Updating MARM to Latest Version** 🔄 **(Easy)**

**Standard Update Process:**

1. **Stop MARM Server**: `Ctrl+C` or stop Docker container
2. **Backup Your Data** (Recommended):

   ```bash
   cp -r ~/.marm ~/.marm_backup_$(date +%Y%m%d)
   ```

3. **Update package**:

   ```bash
   pip install marm-mcp-server --upgrade
   ```

4. **Restart Server**: `python3 -m marm_mcp_server`

---

### **Clean Reinstall (Reset Everything)** ⚠️ **(Advanced)**

**Warning**: This will delete all your memories, sessions, and notebooks.

```bash
# Stop server
rm -rf ~/.marm

# Fresh installation
pip install marm-mcp-server
python3 -m marm_mcp_server
```

### **Migration Notes**

- Database schema is compatible - no migration needed
- New tools automatically available after restart
- Docker images are backward compatible with persistent volumes

**Data Preservation:**

- All memories stored in `~/.marm/marm_memory.db`
- Notebooks stored in same database
- Analytics data stored in `~/.marm/marm_usage_analytics.db` (override with `MARM_ANALYTICS_DB_PATH`)

---

## Troubleshooting

### **Server Won't Start**

```bash
# Check what went wrong
tail -20 server.log

# Check if port is in use
sudo lsof -i :8001
```

### **Common Linux Issues**

- **Port 8001 busy**: Kill process: `sudo lsof -ti:8001 | xargs kill -9`
- **Permission denied**: Use `sudo` or check file permissions: `chmod +x install.sh`
- **Python not found**: Install Python 3.10+: `sudo apt install python3 python3-pip`
- **Module import errors**: Reinstall the package: `pip install marm-mcp-server`

---

## STDIO Diagnostics

STDIO logs write to `~/.marm/logs/marm-stdio.log` automatically when using local pip STDIO mode. Docker STDIO does not expose this file on the host.

```bash
# View full log
cat ~/.marm/logs/marm-stdio.log

# Live tail (watch tool calls as they happen)
tail -f ~/.marm/logs/marm-stdio.log

# Last 20 lines
tail -20 ~/.marm/logs/marm-stdio.log
```

Set `MARM_STDIO_LOG_LEVEL=DEBUG` for additional detail (session names, query lengths, result counts). Memory content is never written to the log.

---

## Configuration

### **Environment Variables**

Set environment variables in your shell:

```bash
export SERVER_PORT=8002
python3 -m marm_mcp_server
```

**Or permanently in ~/.bashrc:**

```bash
echo 'export SERVER_PORT=8002' >> ~/.bashrc
source ~/.bashrc
```

### **Available Environment Variables**

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_HOST` | `127.0.0.1` | Bind address. Default is localhost-only. Set `0.0.0.0` for network/Docker access — key auto-generated on first start. |
| `SERVER_PORT` | `8001` | Server port |
| `MARM_API_KEY` | *(unset)* | Bearer token for all capability endpoints. Auto-generated when `SERVER_HOST=0.0.0.0` and not set. Required for Docker. Generate manually: `python -m marm_mcp_server --generate-key` |
| `MAX_DB_CONNECTIONS` | `5` | Database connection pool size |
| `MARM_ANALYTICS_DB_PATH` | `marm_usage_analytics.db` | Override analytics database path |
| `DEFAULT_SEMANTIC_MODEL` | `all-MiniLM-L6-v2` | AI model for semantic search |
| `MARM_RATE_LIMIT_RPM` | `80` | HTTP rate limit (requests per minute per client IP). Set to `0` to disable. Overridden by `--swarm`, `--swarm-max`, `--trusted` presets. |
| `WRITE_QUEUE_ENABLED` | `1` | Serialized memory write queue. Set to `0` only for debugging/direct-write comparisons. |
| `MAX_QUEUE_SIZE` | `100` | Write queue capacity when `WRITE_QUEUE_ENABLED=1`. |
| `MARM_STDIO_LOG_LEVEL` | `INFO` | STDIO log verbosity. Set to `DEBUG` for session names, query lengths, result counts. |
| `MARM_STDIO_LOG_DIR` | `~/.marm/logs` | Override STDIO log directory. |

---

**MARM Linux Guide** - *Universal memory intelligence for AI agents*

*For usage instructions, see **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)***

*For Docker deployment, see **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)***
