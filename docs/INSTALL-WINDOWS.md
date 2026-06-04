# MARM MCP Server - Windows Installation

## Universal Memory Intelligence Platform for AI Agents

**MARM v2.9.1** - Memory Accurate Response Mode
*Complete Windows installation guide*

---

## Table of Contents

- [Quick Start (5 Minutes)](#quick-start-5-minutes)
- [System Requirements](#system-requirements)
- [Installation Options](#installation-options)
- [Client Connections](#client-connections)
- [Verification & Testing](#verification--testing)
- [Updating & Reinstalling](#updating--reinstalling)
- [Troubleshooting](#troubleshooting)
- [Configuration](#configuration)
- [Windows-Specific Features](#windows-specific-features)
- [Windows Performance Tips](#windows-performance-tips)

---

## Quick Start (5 Minutes)

**🚀 Fastest Path to MARM Memory on Windows:**

1. **Install MARM**: Choose ⭐ **pip install** (Recommended) or ⚡ **virtualenv** (Clean) from options below
2. **Connect Claude**: `claude mcp add --transport http marm-memory http://localhost:8001/mcp`
3. **Test**: Ask Claude to recall a memory — MARM initializes automatically on the first tool call

**That's it!** You now have AI memory that saves across sessions and platforms.

---

## System Requirements

### **Windows Requirements**

- **OS**: Windows 10/11 (64-bit)
- **Python**: 3.10 or higher ([Download Python](https://python.org/downloads))
- **Memory**: 1GB RAM available
- **Storage**: ~500MB disk space
- **Network**: Internet connection for initial setup

### **PowerShell vs Command Prompt**

- **PowerShell** (Recommended) - Better Unicode support, modern features
- **Command Prompt** - Works but may have encoding issues with emojis

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

```powershell
pip install marm-mcp-server
python -m marm_mcp_server
```

### **Option 2: pip install in virtualenv** ⚡ **(Clean environment)**

```powershell
python -m venv marm-env
marm-env\Scripts\activate
pip install marm-mcp-server
python -m marm_mcp_server
```

**If you prefer the `marm-mcp-stdio` CLI script**, add the Python Scripts folder to your PATH first:

```powershell
# Run once to add permanently (replace (username) with your Windows username and Python3XX with your Python version, e.g. Python312)
[System.Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";C:\Users\(username)\AppData\Roaming\Python\Python3XX\Scripts", "User")
```

Then restart your terminal.

### **Option 3: From source** 🔧 **(Advanced)**

```powershell
git clone https://github.com/Lyellr88/MARM-Systems.git
cd MARM-Systems\marm-mcp-server
pip install -e ".[dev]"
python -m marm_mcp_server
```

### **Multi-Agent / Swarm Mode**

For shared HTTP servers running multiple AI agents, use a preset flag:

```powershell
python -m marm_mcp_server --swarm        # 200 RPM, write queue on
python -m marm_mcp_server --swarm-max    # 600 RPM, write queue on
python -m marm_mcp_server --trusted      # rate limiting off, write queue on
python -m marm_mcp_server --rate-limit-rpm 150  # custom RPM
```

### **After Installation:**

**Server starts on**: `http://localhost:8001`
**MCP Endpoint**: `http://localhost:8001/mcp`
**API Documentation**: `http://localhost:8001/docs`

---

## Client Connections

### **Claude Code (Recommended)**

**HTTP Connection (Standard):**

```bash
claude mcp add --transport http marm-memory http://localhost:8001/mcp
```

**Note**: Claude Code currently supports HTTP, SSE, and STDIO through `claude mcp add`; use HTTP for MARM.

### **VS Code MCP / GitHub Copilot Agent**

Verified with VS Code's native MCP support. Add this to `.vscode\mcp.json` in your workspace. Use `marm-memory-local` for direct Python installs; use `marm-memory-docker` when running Docker or exposed/key mode.

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

Open `.vscode\mcp.json`, click **Start** above the server you want, then use Copilot Agent or any VS Code extension that consumes VS Code's native MCP registry. Third-party extensions that do not use VS Code's MCP registry may require their own setup.

### **Cursor**

Verified with Cursor MCP. Add this to `.cursor\mcp.json` in your workspace. Use `marm-memory-local` for direct Python installs; use `marm-memory-docker` when running Docker or exposed/key mode.

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

Codex uses `codex mcp add` or TOML config at `%USERPROFILE%\.codex\config.toml`, not `settings.json`.

```powershell
# Direct Python install — no key needed
codex mcp add marm-memory --url http://localhost:8001/mcp

# Docker or SERVER_HOST=0.0.0.0 — key required
$env:MARM_API_KEY="your-generated-key"
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

```powershell
# Direct Python install — no key needed
gemini mcp add --transport http marm-memory http://localhost:8001/mcp

# Docker or SERVER_HOST=0.0.0.0 — key required
gemini mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
```

Equivalent `%USERPROFILE%\.gemini\settings.json` or project `.gemini\settings.json`:

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

Qwen Code supports STDIO, SSE, and streamable HTTP MCP transports. Use HTTP for MARM. Project scope writes to `.qwen\settings.json`; user scope writes to `%USERPROFILE%\.qwen\settings.json`.

```powershell
# Direct Python install — no key needed
qwen mcp add --transport http marm-memory http://localhost:8001/mcp

# Docker or SERVER_HOST=0.0.0.0 — key required
qwen mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
```

Equivalent `.qwen\settings.json` or `%USERPROFILE%\.qwen\settings.json`:

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

```powershell
Invoke-WebRequest -Uri http://localhost:8001/health
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

   ```powershell
   Copy-Item -Recurse "$env:USERPROFILE\.marm" "$env:USERPROFILE\.marm_backup_$(Get-Date -Format yyyyMMdd)"
   ```

3. **Update package**:

   ```powershell
   pip install marm-mcp-server --upgrade
   ```

4. **Restart Server**: `python -m marm_mcp_server`

**🐳 Docker Update:**

```powershell
docker pull lyellr88/marm-mcp-server:latest
docker stop marm-mcp-server
docker rm marm-mcp-server
docker run -d --name marm-mcp-server -p 127.0.0.1:8001:8001 -e SERVER_HOST=0.0.0.0 -e MARM_API_KEY=your-generated-key -v ${HOME}\.marm:/home/marm/.marm --restart unless-stopped lyellr88/marm-mcp-server:latest
```

---

### **Clean Reinstall (Reset Everything)** ⚠️ **(Advanced)**

**Warning**: This will delete all your memories, sessions, and notebooks.

```powershell
# Stop server, then delete data directory
Remove-Item -Recurse -Force "$env:USERPROFILE\.marm"

# Fresh installation
pip install marm-mcp-server
python -m marm_mcp_server
```

### **Migration Notes**

- Database schema is compatible - no migration needed
- New tools automatically available after restart
- Docker images are backward compatible with persistent volumes

**Data Preservation:**

- All memories stored in `%USERPROFILE%\.marm\marm_memory.db`
- Notebooks stored in same database
- Analytics data stored in `%USERPROFILE%\.marm\marm_usage_analytics.db` (override with `MARM_ANALYTICS_DB_PATH`)

---

## Troubleshooting

### **Server Won't Start**

```powershell
# Check what went wrong
Get-Content server.log | Select-Object -Last 20

# Check if port is in use
netstat -ano | findstr :8001
```

### **Common Windows Issues**

- **Port 8001 busy**: Find and kill process: `netstat -ano | findstr :8001` → `taskkill /PID <id> /F`
- **Permission denied**: Run PowerShell as Administrator
- **Unicode/emoji errors**: Set encoding: `$env:PYTHONIOENCODING="utf-8"`
- **Python not found**: Reinstall Python and check "Add to PATH" option

---

## Configuration

### **Environment Variables**

Set environment variables in PowerShell:

```powershell
$env:SERVER_PORT="8002"
python -m marm_mcp_server
```

**Or permanently via System Properties:**

1. Search "Environment Variables" in Start Menu
2. Click "Environment Variables..." button
3. Add under "User variables"

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
| `MARM_STDIO_LOG_DIR` | `%USERPROFILE%\.marm\logs` | Override STDIO log directory. |

---

## Windows-Specific Features

### **Startup Script**

Create `start_marm.bat` for easy startup:

```batch
@echo off
python -m marm_mcp_server
pause
```

### **STDIO Diagnostics**

STDIO logs write to `%USERPROFILE%\.marm\logs\marm-stdio.log` automatically when using local pip STDIO mode. Docker STDIO does not expose this file on the host.

```powershell
# View full log
Get-Content "$env:USERPROFILE\.marm\logs\marm-stdio.log"

# Live tail (watch tool calls as they happen)
Get-Content "$env:USERPROFILE\.marm\logs\marm-stdio.log" -Wait -Tail 20
```

Set `MARM_STDIO_LOG_LEVEL=DEBUG` for additional detail (session names, query lengths, result counts). Memory content is never written to the log.

### **WSL Integration**

MARM works in Windows Subsystem for Linux:

```bash
# In WSL terminal
pip install marm-mcp-server
python3 -m marm_mcp_server
```

Access from Windows: `http://localhost:8001`

---

## Windows Performance Tips

### **Memory Optimization**

- **Close unnecessary programs** before starting MARM
- **Use Task Manager** to monitor memory usage
- **Consider WSL2** for better performance on older systems

### **Antivirus Configuration**

Add MARM folder to antivirus exclusions to prevent:

- Slow startup times
- File access issues
- False positive detections

**Common paths to exclude:**

- `C:\Users\{username}\.marm\`

---

**MARM Windows Guide** - *Universal memory intelligence for AI agents*

*For usage instructions, see **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)***  
*For Docker deployment, see **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)***
