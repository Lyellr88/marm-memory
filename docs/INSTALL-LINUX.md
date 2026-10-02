# MARM MCP Server - Linux Installation

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
3. **Test**: Ask Claude to recall a memory, MARM initializes automatically on the first tool call

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
marm-memory start
```

### **Option 2: pip install in virtualenv** ⚡ **(Clean environment)**

```bash
python3 -m venv marm-env
source marm-env/bin/activate
pip install marm-mcp-server
marm-memory start
```

### **Multi-Agent / Swarm Mode**

For shared HTTP servers running multiple AI agents, use a preset flag:

```bash
marm-memory start --profile swarm        # 200 RPM, write queue on
marm-memory start --profile swarm-max    # 600 RPM, write queue on
marm-memory start --profile trusted      # rate limiting off, write queue on
marm-memory start --rate-limit-rpm 150   # custom RPM
```

Use one MARM HTTP process per SQLite database. Multi-process Uvicorn/Gunicorn
workers (`--workers N`) are not supported yet because MARM's write queue,
scheduler, and protocol/session coordination are process-local.

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

The Cursor CLI (`agent`) reads the same `mcp.json` files, so a server added for the editor is already available there. Run `agent mcp list` to check. A server in the global `~/.cursor/mcp.json` loads without approval. A server in a project's `.cursor/mcp.json` asks you to trust the folder and approve it on first use, and headless runs need `--trust --approve-mcps`. If it lists no servers, look in `mcp.json` for an entry with an unknown `type` such as `streamable-http`: the CLI drops the whole file when one entry fails to parse. Install it with `curl https://cursor.com/install -fsS | bash` on macOS, Linux and WSL, or `irm 'https://cursor.com/install?win32=true' | iex` in Windows PowerShell.

### **Grok app and API**

The Grok app (grok.com, iOS, Android) supports custom MCP servers: open grok.com/connectors, click **New Connector**, choose **Custom**, and enter your MARM URL. The xAI API supports Remote MCP Tools over Streamable HTTP or SSE only.

Both run on xAI's infrastructure, so `localhost` will not work. Expose MARM behind HTTPS (a tunnel or your own domain) and set `MARM_API_KEY`. MARM has not been tested through the app's connector form. For the API, send this tool payload:

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
# Direct Python install - no key needed
codex mcp add marm-memory --url http://localhost:8001/mcp

# Docker or SERVER_HOST=0.0.0.0 - key required
export MARM_API_KEY="your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
```

```toml
[mcp_servers."marm-memory"]
url = "http://localhost:8001/mcp"
enabled = true
bearer_token_env_var = "MARM_API_KEY"
```

### **Grok Build**

Grok Build (`grok`), xAI's terminal coding agent, supports STDIO and HTTP MCP servers and reads `~/.grok/config.toml`. MARM sets `bearer_token_env_var`, so the key stays in your environment and never lands in the file.

```bash
# Direct Python install - no key needed
grok mcp add --transport http marm-memory http://localhost:8001/mcp
```

Docker or `SERVER_HOST=0.0.0.0` (key required): set `MARM_API_KEY`, then add this to `~/.grok/config.toml` (or `.grok/config.toml` for one project):

```toml
[mcp_servers.marm-memory]
url = "http://localhost:8001/mcp"
bearer_token_env_var = "MARM_API_KEY"
```

Grok Build also reads MCP servers from `~/.claude.json`, `.cursor/mcp.json`, and project `.mcp.json`, so MARM may already load if Claude Code or Cursor has it. Run `grok mcp list` to see what it loaded.

### **Hermes Agent**

Hermes Agent (`hermes`) by Nous Research reads MCP servers from `mcp_servers` in `config.yaml`: `~/.hermes/config.yaml` on macOS and Linux, `%LOCALAPPDATA%\hermes\config.yaml` on native Windows, or `$HERMES_HOME/config.yaml` if you set it. It supports STDIO and HTTP and expands `${VAR}` in headers, so the key stays in your environment or `~/.hermes/.env` and never lands in the file.

```bash
# STDIO - no key needed
hermes mcp add marm-memory --command marm-mcp-stdio

# HTTP, direct Python install - no key needed
hermes mcp add marm-memory --url http://localhost:8001/mcp
```

Docker or `SERVER_HOST=0.0.0.0` (key required): set `MARM_API_KEY`, then add this under `mcp_servers` in `config.yaml`:

```yaml
mcp_servers:
  marm-memory:
    url: "http://localhost:8001/mcp"
    headers:
      Authorization: "Bearer ${MARM_API_KEY}"
```

Run `/reload-mcp` in Hermes, or start a new session, to load it.

### **OpenCode**

OpenCode (`opencode`, installed with `npm install -g opencode-ai`) reads MCP servers from `mcp` in `opencode.json` or `opencode.jsonc`: `~/.config/opencode/` on every platform including Windows (`%USERPROFILE%\.config\opencode`), or `$XDG_CONFIG_HOME/opencode/` if you set it, and `opencode.json` in a project root for one project. It supports STDIO (`type: local`) and HTTP (`type: remote`) and expands `{env:VAR}` in headers, so the key stays in your environment and never lands in the file. Remote servers try OAuth by default, so MARM writes `oauth: false`. OpenCode 2 nests servers under `mcp.servers` and still reads the layout below, and MARM writes into whichever layout the file already uses. Connecting from the Console rewrites the file as plain JSON, so comments in a `.jsonc` file are not kept, and the original is saved beside it as `.marm-backup`. Start a new OpenCode session to load it, and run `opencode mcp list` to check.

STDIO, no key needed:

```json
{
  "mcp": {
    "marm-memory": {
      "type": "local",
      "command": ["marm-mcp-stdio"]
    }
  }
}
```

HTTP, direct Python install (no key needed):

```json
{
  "mcp": {
    "marm-memory": {
      "type": "remote",
      "url": "http://localhost:8001/mcp",
      "oauth": false
    }
  }
}
```

Docker or `SERVER_HOST=0.0.0.0` (key required): set `MARM_API_KEY`, then add the same HTTP entry with a header:

```json
{
  "mcp": {
    "marm-memory": {
      "type": "remote",
      "url": "http://localhost:8001/mcp",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:MARM_API_KEY}"
      }
    }
  }
}
```

### **Devin**

Devin CLI (`devin`) and the Devin Local agent in Devin Desktop, the IDE formerly called Windsurf, read MCP servers from the same `mcp_config.json`: `~/.config/devin/mcp_config.json` on macOS and Linux (or `$XDG_CONFIG_HOME/devin/mcp_config.json` if you set it), `%APPDATA%\devin\mcp_config.json` on Windows. Connecting once covers both. The older Cascade agent in Devin Desktop keeps its MCP servers in its own file under `~/.codeium`, which MARM does not write. Devin CLI v3000.3 or later reads this dedicated file, and older builds keep `mcpServers` in `config.json` and migrate it on startup. `devin mcp add` saves to a gitignored project file unless you pass `-s user`.

```bash
# STDIO - no key needed
devin mcp add -s user marm-memory -- marm-mcp-stdio

# HTTP, direct Python install - no key needed
devin mcp add -s user marm-memory http://localhost:8001/mcp
```

Docker or `SERVER_HOST=0.0.0.0` (key required): MARM has not confirmed that Devin expands environment variables in headers, so use STDIO, or add the key by hand under `mcpServers` in that file:

```json
{
  "mcpServers": {
    "marm-memory": {
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer your-generated-key"
      }
    }
  }
}
```

### **Zed**

Zed reads MCP servers from `context_servers` in its user `settings.json`: `~/.config/zed/settings.json` on macOS and Linux (or `$XDG_CONFIG_HOME/zed/settings.json` on Linux), `%APPDATA%\Zed\settings.json` on Windows. Run `zed: open settings file` from the command palette to open it. Zed has no add command, and MARM has not confirmed that Zed expands environment variables in headers, so keyed setups use STDIO. Connecting from the Console edits only the `marm-memory` entry as text, so comments and the rest of your settings stay as they were, and it restores the file if anything else changed. Zed lists the server under Settings, AI, MCP Servers, with a green dot when it is running. Zed's own agent reads the MARM skill from `~/.agents/skills` once you install it from the Console.

STDIO, no key needed:

```json
{
  "context_servers": {
    "marm-memory": {
      "command": "marm-mcp-stdio",
      "args": []
    }
  }
}
```

HTTP, direct Python install (no key needed):

```json
{
  "context_servers": {
    "marm-memory": {
      "url": "http://localhost:8001/mcp"
    }
  }
}
```

Docker or `SERVER_HOST=0.0.0.0` (key required): use STDIO, or paste the key into the entry by hand. Zed keeps it as plain text in `settings.json`:

```json
{
  "context_servers": {
    "marm-memory": {
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer your-generated-key"
      }
    }
  }
}
```

### **Cline CLI**

Cline CLI (`cline`, installed with `npm install -g cline`) reads MCP servers from `~/.cline/data/settings/cline_mcp_settings.json`, the same file the Cline extensions in VS Code and JetBrains use (`%USERPROFILE%\.cline` on Windows, or `$CLINE_DATA_DIR/settings` if you set it). Cline's own MCP page still says `~/.cline/mcp.json`, but the CLI never reads that file. HTTP entries need `"type": "streamableHttp"`: leaving `type` out selects the legacy SSE transport. The extensions in VS Code and JetBrains show the server in their MCP Servers panel. Cline 4.x or later shares this file and moves an older file from VS Code's extension storage into it on first launch. Older builds keep reading their own file, so upgrade Cline first.

```bash
# STDIO - no key needed
cline mcp install marm-memory --yes -- marm-mcp-stdio

# HTTP, direct Python install - no key needed
cline mcp install marm-memory --yes --transport http http://localhost:8001/mcp
```

Docker or `SERVER_HOST=0.0.0.0` (key required): MARM has not confirmed that Cline CLI expands environment variables in headers, so use STDIO, or add the key by hand under `mcpServers` in that file:

```json
{
  "mcpServers": {
    "marm-memory": {
      "type": "streamableHttp",
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer your-generated-key"
      }
    }
  }
}
```

### **Antigravity CLI**

Antigravity CLI (`agy`) replaced Gemini CLI in June 2026. It supports STDIO and HTTP MCP servers. Use HTTP for MARM. The Antigravity IDE and 2.0 app read this same file (in the IDE, open "..." then MCP Servers, then Manage MCP Servers). Antigravity 2.x or later reads it. Older IDE builds used `~/.gemini/antigravity/mcp_config.json`, and MARM writes that file only when it is the only one present.

```bash
# Direct Python install - no key needed
agy mcp add marm-memory --type http http://localhost:8001/mcp

# Docker or SERVER_HOST=0.0.0.0 - key required
agy mcp add marm-memory --type http http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"
```

Equivalent `~/.gemini/config/mcp_config.json` (user scope) or project `.agents/mcp_config.json`. Antigravity reads `serverUrl`, not `url` or `httpUrl`, and does not expand `${VAR}` in this file, so paste the real key:

```json
{
  "mcpServers": {
    "marm-memory": {
      "serverUrl": "http://localhost:8001/mcp",
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
# Direct Python install - no key needed
qwen mcp add --transport http marm-memory http://localhost:8001/mcp

# Docker or SERVER_HOST=0.0.0.0 - key required
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
  "version": "2.57.0",
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

4. **Migrate existing embeddings** when upgrading to the Jina v2 Small release:

   ```bash
   marm-mcp-server --migrate-embeddings
   ```

   Keep every MARM HTTP and STDIO process stopped while this runs. The command refuses when it detects an HTTP server, but cannot reliably detect STDIO processes. It is resumable after interruption.

5. **Restart Server**: `python3 -m marm_mcp_server`

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

- The Jina v2 Small upgrade changes stored embeddings from MiniLM's 384 dimensions to 512 dimensions. After upgrading, stop every MARM process and run `marm-mcp-server --migrate-embeddings` before restarting; it migrates memory, chunk, notebook, and any existing concept-graph embeddings.
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
| `SERVER_HOST` | `127.0.0.1` | Bind address. Default is localhost-only. Set `0.0.0.0` for network/Docker access, key auto-generated on first start. |
| `SERVER_PORT` | `8001` | Server port |
| `MARM_API_KEY` | *(unset)* | Bearer token for all capability endpoints. Auto-generated when `SERVER_HOST=0.0.0.0` and not set. Required for Docker. Generate manually: `python -m marm_mcp_server --generate-key` |
| `MAX_DB_CONNECTIONS` | `5` | Database connection pool size |
| `MARM_ANALYTICS_DB_PATH` | `~/.marm/marm_usage_analytics.db` | Override analytics database path |
| `DEFAULT_SEMANTIC_MODEL` | `jinaai/jina-embeddings-v2-small-en` | Default semantic-search model: 512 dimensions, 8,192-token context, 33M parameters, Apache-2.0 licensed; no query/document text prefixes required. |
| `RECALL_SCAN_LIMIT` | `10000` | Maximum embedded memories semantic recall scans per query before surfacing `recall_scan_truncated=true`. |
| `MARM_RATE_LIMIT_RPM` | `80` | HTTP rate limit (requests per minute per client IP). Set to `0` to disable. Overridden by `--swarm`, `--swarm-max`, `--trusted` presets. |
| `WRITE_QUEUE_ENABLED` | `1` | Serialized memory write queue. Set to `0` only for debugging/direct-write comparisons. |
| `MAX_QUEUE_SIZE` | `100` | Write queue capacity when `WRITE_QUEUE_ENABLED=1`. |
| `MARM_STDIO_LOG_LEVEL` | `INFO` | STDIO log verbosity. Set to `DEBUG` for session names, query lengths, result counts. |
| `MARM_STDIO_LOG_DIR` | `~/.marm/logs` | Override STDIO log directory. |

---

**MARM Linux Guide** - *Universal memory intelligence for AI agents*

*For usage instructions, see **[README.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/README.md)***

*For Docker deployment, see **[INSTALL-DOCKER.md](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-DOCKER.md)***
