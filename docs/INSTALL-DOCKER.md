# MARM MCP Server - Docker Installation

## Universal Memory Intelligence Platform for AI Agents

**MARM v2.2.3* - Memory Accurate Response Mode  
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

1. **Pull & Run**: Choose Docker Run or Docker Compose below
2. **Connect Claude**: `claude mcp add marm-memory http://localhost:8001/mcp`
3. **Test**: `marm_start` → `marm_system_info`

**That's it!** You now have AI memory that saves across sessions and platforms.

---

## Installation Options

### **Option 1: Docker Run (Recommended for Testing)**

**Best for:** First-time users, quick testing, simple setup

```bash
# Pull the latest image
docker pull lyellr88/marm-mcp-server:latest

# Basic setup (temporary data)
docker run -d --name marm-mcp-server -p 8001:8001 lyellr88/marm-mcp-server:latest

# Recommended setup (persistent data)
docker run -d --name marm-mcp-server -p 8001:8001 -v marm-data:/home/marm/.marm --restart unless-stopped lyellr88/marm-mcp-server:latest
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
      - "8001:8001"
    restart: unless-stopped
    volumes:
      - marm-data:/home/marm/.marm

volumes:
  marm-data:
```

```bash
docker-compose up -d
```

**Why choose this:**

- **Automatic restarts** - if your computer reboots, MARM starts automatically
- **Easier management** - stop/start with simple commands
- **Persistent settings** - your configuration is saved in a file
- **Organized setup** - clean configuration management

---

## Client Connections

### **Claude Code (Recommended)**

```bash
claude mcp add marm-memory http://localhost:8001/mcp
```

### **Grok CLI (Command Method)**

```bash
grok mcp add marm-memory --transport http --url "http://localhost:8001/mcp"
```

### **Qwen, Gemini & Grok CLI (Settings.json Method)**

For CLI clients that use settings.json configuration, add the following.

| Client | `selectedAuthType` |
| :--- | :--- |
| **Qwen CLI** 🤖 | `qwen-oauth` |
| **Gemini CLI** 💎 | `oauth-personal` |
| **Grok CLI** ⚡ | `grok-oauth` |

Then, add the following `mcpServers` configuration:

```json
{
  "mcpServers": {
    "marm-memory": {
      "httpUrl": "http://localhost:8001/mcp",
      "authentication": {
        "type": "oauth",
        "clientId": "local_client_b6f3a01e",
        "clientSecret": "local_secret_ad6703cd2b4243ab",
        "authorizationUrl": "http://localhost:8001/oauth/authorize",
        "tokenUrl": "http://localhost:8001/oauth/token",
        "scopes": ["read", "write"]
      }
    }
  }
}
```

>Note: All clients use the same shared credentials for free tier access.

---

## Management Commands

### **Docker Run Commands**

**Stop and Remove:**

```bash
docker stop marm-mcp-server
docker rm marm-mcp-server
```

**Update to Latest:**

```bash
docker pull lyellr88/marm-mcp-server:latest
docker stop marm-mcp-server
docker rm marm-mcp-server
docker run -d --name marm-mcp-server -p 8001:8001 -v marm-data:/home/marm/.marm --restart unless-stopped lyellr88/marm-mcp-server:latest
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

### **Built-in Container Tests (Recommended)**

**MARM includes professional diagnostic tests that validate your container deployment built into the docker image:**

| Test Type | Command | What It Validates | Run Time |
|-----------|---------|-------------------|----------|
| **Health & Performance** | `docker exec marm-mcp-server python tests/test_docker_performance.py` | Response times, concurrent handling, server stability | ~30 seconds |
| **MCP Compliance** | `docker exec marm-mcp-server python tests/test_docker_mcp_size_limits.py` | MCP protocol compliance, rate limiting, response sizes | ~45 seconds |
| **Memory Usage** | `docker exec marm-mcp-server python tests/test_docker_memory_usage.py` | Container memory efficiency, resource optimization | ~20 seconds |
| **Security Validation** | `docker exec marm-mcp-server python tests/test_security.py` | XSS protection, input validation, error handling | ~15 seconds |

### **Why Built-in Tests Beat Traditional Commands**

**Traditional approach:**

```bash
curl http://localhost:8001/health  # Only tests basic connectivity
docker logs marm-mcp-server        # Shows logs but no validation
```

**MARM's integrated testing:**

- **Comprehensive validation** - Tests all major systems, not just connectivity
- **Performance benchmarking** - Measures actual response times and throughput
- **Professional scoring** - Get objective performance metrics (0-100 scores)
- **Reliable validation** - Validates your deployment meets quality standards
- **Troubleshooting data** - Detailed diagnostics when things go wrong

### **Quick Health Check**

```bash
# Traditional health check (still useful for quick validation)
docker logs marm-mcp-server | head -20
```

**Look for these success indicators:**

```txt
Semantic search model loaded successfully
MARM documentation database ready!
MARM MCP Server initialization complete
Uvicorn running on http://0.0.0.0:8001
```

### **Found Issues? We Want to Hear!**

If any tests fail or you encounter problems:

- **🐛 Open an [Issue]((https://github.com/Lyellr88/MARM-Systems/issues)**: Report problems on GitHub
- **🔧 Submit a [Pull Request](https://github.com/Lyellr88/MARM-Systems/pulls)**: Fixed it yourself? We welcome contributions!
- **💬 Join Discussions**: Share feedback and get help from the community

Your testing helps make MARM better for everyone.

---

## Updating & Reinstalling

**🐳 Docker Update:**

```bash
docker pull lyellr88/marm-mcp-server:latest
docker stop marm-mcp-server
docker rm marm-mcp-server
docker run -d --name marm-mcp-server -p 8001:8001 -v marm-data:/home/marm/.marm --restart unless-stopped lyellr88/marm-mcp-server:latest
```

---

### **Migration Notes**

**v2.0 → v2.2.3 Migration:**

- Database schema is compatible - no migration needed
- New tools automatically available after restart
- Docker images are backward compatible with persistent volumes

**Data Preservation:**

- All memories stored in `~/.marm/marm_memory.db`
- Notebooks stored in same database
- Analytics data stored in `~/.marm/analytics.db`

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

### **Still Having Issues?**

Run the diagnostic tests - they provide detailed error information:

```bash
docker exec marm-mcp-server python tests/test_docker_performance.py
```

---

## Configuration

### **Environment Variables (Advanced)**

For custom configuration, add environment variables to your Docker commands:

**Docker Run:**

```bash
docker run -d --name marm-mcp-server -p 8001:8001 -v marm-data:/home/marm/.marm -e SERVER_PORT=8002 -e ANALYTICS_ENABLED=false --restart unless-stopped lyellr88/marm-mcp-server:latest
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
      - marm-data:/home/marm/.marm
    environment:
      - SERVER_PORT=8002
      - ANALYTICS_ENABLED=false

volumes:
  marm-data:
```

### **Available Environment Variables**

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_PORT` | `8001` | Server port |
| `MAX_DB_CONNECTIONS` | `5` | Database connection pool size |
| `ANALYTICS_ENABLED` | `true` | Usage analytics (privacy-conscious) |
| `DEFAULT_SEMANTIC_MODEL` | `all-MiniLM-L6-v2` | AI model for semantic search |

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
- **WSL2** (Windows Subsystem for Linux)

---

**MARM v2.2.3 Docker Guide** - *Universal memory intelligence for AI agents*

*For usage instructions, see **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)***  
*For native installation, see **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)**  or **[INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)***

---

## 📁 Project Documentation

### **Usage Guides**

- **[MARM-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MARM-HANDBOOK.md)** - Original MARM protocol handbook for chatbot usage
- **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)** - Complete MCP server usage guide with commands, workflows, and examples
- **[PROTOCOL.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/PROTOCOL.md)** - Quick start commands and protocol reference
- **[FAQ.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/FAQ.md)** - Answers to common questions about using MARM

### **MCP Server Installation** 

- **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)** - Docker deployment (recommended)
- **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)** - Windows installation guide
- **[INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)** - Linux installation guide
- **[INSTALL-PLATFORMS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORMS.md)** - Platfrom installtion guide

### **Chatbot Installation**

- **[CHATBOT-SETUP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHATBOT-SETUP.md)** - Web chatbot setup guide

### **Project Information**

- **[README.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/README.md)** - This file - ecosystem overview and MCP server guide
- **[CONTRIBUTING.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CONTRIBUTING.md)** - How to contribute to MARM
- **[DESCRIPTION.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/DESCRIPTION.md)** - Protocol purpose and vision overview
- **[CHANGELOG.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHANGELOG.md)** - Version history and updates
- **[ROADMAP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ROADMAP.md)** - Planned features and development roadmap
- **[LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/LICENSE)** - MIT license terms

---

>Built with ❤️ by MARM Systems - Universal MCP memory intelligence
