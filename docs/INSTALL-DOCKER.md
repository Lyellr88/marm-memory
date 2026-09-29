# MARM MCP Server - Docker Installation

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
4. **Test**: Ask Claude to recall a memory - MARM initializes automatically on the first tool call

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
 
> **Docker always requires an API key.** Docker's bridge network means the server sees requests from a gateway IP (172.x.x.x), not 127.0.0.1 - even when you're on the same machine. Generate a key using the container itself - no pip install needed:

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

# Connect client (replace "agent" with your MCP client's command, e.g., "claude" or "cursor")
"agent" mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"

# PowerShell: set this before starting/restarting Codex
$env:MARM_API_KEY="your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
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
      - MARM_API_KEY=your-generated-key   # Required - see note above
```

```bash
docker-compose up -d
```

```bash
# Connect client
"agent" mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"

# PowerShell: set this before starting/restarting Codex
$env:MARM_API_KEY="your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
```

**Why choose this:**

- **Automatic restarts** - if your computer reboots, MARM starts automatically
- **Easier management** - stop/start with simple commands
- **Persistent settings** - your configuration is saved in a file
- **Organized setup** - clean configuration management

### **Swarm / Multi-Agent Mode**

For shared HTTP servers running multiple AI agents simultaneously, append a preset flag after the image name:

```bash
# --swarm: write queue on, 200 RPM - recommended starting point
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest --swarm

# --swarm-max: write queue on, 600 RPM - heavier load
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest --swarm-max

# --trusted: write queue on, rate limiting disabled - private/trusted only
docker run -d --name marm-mcp-server \
  -p 127.0.0.1:8001:8001 \
  -e SERVER_HOST=0.0.0.0 \
  -e MARM_API_KEY=your-generated-key \
  -v ~/.marm:/home/marm/.marm \
  --restart unless-stopped \
  lyellr88/marm-mcp-server:latest --trusted
```

```bash
# Connect client
"agent" mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer your-generated-key"

# PowerShell: set this before starting/restarting Codex
$env:MARM_API_KEY="your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
```

| Preset | Rate Limit | Write Queue | Use When |
|--------|------------|-------------|----------|
| `--swarm` | 200 RPM | enabled | Normal multi-agent shared server |
| `--swarm-max` | 600 RPM | enabled | Heavier private swarm testing |
| `--trusted` | disabled | enabled | Trusted private deployments only |

Use one MARM HTTP process/container per SQLite database. Multi-process
Uvicorn/Gunicorn workers (`--workers N`) are not supported yet because MARM's
write queue, scheduler, and protocol/session coordination are process-local.

### Docker Graph Indexing

Docker graph tools run inside the container, so they cannot see host paths unless you mount them at `docker run`.

```powershell
# Docker graph indexing: mount the repo
# Replace C:\Users\lyell\Desktop\marm-memory with your actual repository path

$env:MARM_API_KEY="test"

docker run -d --name marm-mcp-server `
  -p 127.0.0.1:8001:8001 `
  -e SERVER_HOST=0.0.0.0 `
  -e MARM_API_KEY=$env:MARM_API_KEY `
  -v ~/.marm:/home/marm/.marm `
  -v "C:\Users\lyell\Desktop\marm-memory:/workspace/marm-memory" `
  lyellr88/marm-mcp-server:latest
```

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

The Cursor CLI (`agent`) reads the same `mcp.json` files, so a server added for the editor is already available there. Run `agent mcp list` to check. A server in the global `~/.cursor/mcp.json` loads without approval. A server in a project's `.cursor/mcp.json` asks you to trust the folder and approve it on first use, and headless runs need `--trust --approve-mcps`. If it lists no servers, look in `mcp.json` for an entry with an unknown `type` such as `streamable-http`: the CLI drops the whole file when one entry fails to parse. Install it with `curl https://cursor.com/install -fsS | bash` on macOS, Linux and WSL, or `irm 'https://cursor.com/install?win32=true' | iex` in Windows PowerShell.

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

### **Docker STDIO**

The MCP client launches Docker as the server command. No port binding or API key needed. Use `-i` (interactive stdin) - never `-d` (detached).

```bash
docker run -i --rm \
  -v ~/.marm:/home/marm/.marm \
  --entrypoint python \
  lyellr88/marm-mcp-server:latest \
  -m marm_mcp_server.server_stdio
```

<details>
<summary>JSON config for Claude Desktop, Claude Code, Cursor, VS Code</summary>

> JSON `args` arrays are not processed by a shell, so `~` is not expanded. Use an absolute path for the volume mount.

**macOS / Linux** - replace `/Users/you` with your actual home directory:

```json
{
  "mcpServers": {
    "marm-memory": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/Users/you/.marm:/home/marm/.marm",
        "--entrypoint", "python",
        "lyellr88/marm-mcp-server:latest",
        "-m", "marm_mcp_server.server_stdio"
      ]
    }
  }
}
```

**Windows** - replace `C:\Users\you` with your actual home directory:

```json
{
  "mcpServers": {
    "marm-memory": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "C:\\Users\\you\\.marm:/home/marm/.marm",
        "--entrypoint", "python",
        "lyellr88/marm-mcp-server:latest",
        "-m", "marm_mcp_server.server_stdio"
      ]
    }
  }
}
```

STDIO mode has no HTTP healthcheck. The image healthcheck applies to HTTP mode only and is irrelevant for client-launched STDIO containers.

</details>

---

### **Grok Build**

Grok Build (`grok`), xAI's terminal coding agent, supports STDIO and HTTP MCP servers and reads `~/.grok/config.toml`. MARM sets `bearer_token_env_var`, so the key stays in your environment and never lands in the file.

Set `MARM_API_KEY`, then add this to `~/.grok/config.toml` (or `.grok/config.toml` for one project):

```toml
[mcp_servers.marm-memory]
url = "http://localhost:8001/mcp"
bearer_token_env_var = "MARM_API_KEY"
```

Grok Build also reads MCP servers from `~/.claude.json`, `.cursor/mcp.json`, and project `.mcp.json`, so MARM may already load if Claude Code or Cursor has it. Run `grok mcp list` to see what it loaded.

### **Hermes Agent**

Hermes Agent (`hermes`) by Nous Research reads MCP servers from `mcp_servers` in `config.yaml`: `~/.hermes/config.yaml` on macOS and Linux, `%LOCALAPPDATA%\hermes\config.yaml` on native Windows, or `$HERMES_HOME/config.yaml` if you set it. It supports STDIO and HTTP and expands `${VAR}` in headers, so the key stays in your environment or `~/.hermes/.env` and never lands in the file.

Set `MARM_API_KEY`, then add this under `mcp_servers` in `config.yaml`:

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
Uvicorn running on http://0.0.0.0:8001  (inside container - normal)
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
```

**Migrate existing embeddings** when upgrading to the Jina v2 Small release. With every HTTP and STDIO MARM process stopped, run this against the persistent data volume before starting the updated container:

```bash
docker run --rm \
  -v ~/.marm:/home/marm/.marm \
  lyellr88/marm-mcp-server:latest --migrate-embeddings
```

The migration command refuses when it detects a live HTTP server, but cannot reliably detect STDIO processes. It re-embeds memory, chunk, notebook, and any existing concept-graph embeddings, and can be rerun safely after interruption.

**Start the updated container:**

```bash
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

- The Jina v2 Small upgrade changes stored embeddings from MiniLM's 384 dimensions to 512 dimensions. Migrate the persistent volume with `--migrate-embeddings` before starting the updated container.

```bash
docker run --rm \
  -v ~/.marm:/home/marm/.marm \
  lyellr88/marm-mcp-server:latest --migrate-embeddings
```

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

### Automatic code indexing

The image includes both the graph engine and Git. After you index a repository once with `marm_graph_index`, the background worker detects changes to that repository using its container-visible path. Mount the repository, including its `.git` directory, into the container for change detection.

The worker uses the same launcher selection as manual graph tools: `CBM_BINARY_PATH`, then `CBM_COMMAND`, then the pip-managed engine. A missing configured path is reported as `graph_auto_index.dormant` with reason `configured_binary_missing`; a non-executable path uses `configured_binary_not_executable`. Check the path and permissions inside the container. Graph startup failures leave core memory tools available. Outside Docker, an absent pip-managed engine remains dormant until a manual graph call downloads it.


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
| `MARM_API_KEY` | _(unset)_ | Required for all Docker deployments (local and remote). Docker bridge networking means the server never sees 127.0.0.1 from the host, set this or all MCP calls will 401. Generate with `docker run --rm lyellr88/marm-mcp-server:latest --generate-key`. |
| `MARM_RATE_LIMIT_RPM` | `80` | HTTP rate limit (requests per minute per client IP). Set to `0` to disable. Overridden by `--swarm`, `--swarm-max`, `--trusted` presets. |
| `RECALL_SCAN_LIMIT` | `10000` | Maximum embedded memories semantic recall scans per query before surfacing `recall_scan_truncated=true`. |
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

- [README.md](../README.md) - MCP tool usage and workflows
- [INSTALL-WINDOWS.md](INSTALL-WINDOWS.md) - Native Windows installation
- [INSTALL-LINUX.md](INSTALL-LINUX.md) - Native Linux installation
- [INSTALL-PLATFORMS.md](INSTALL-PLATFORMS.md) - Platform and API integration
