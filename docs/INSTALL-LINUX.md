# MARM MCP Server - Linux Installation

## Universal Memory Intelligence Platform for AI Agents

**MARM v2.2.4* - Memory Accurate Response Mode
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
2. **Connect Claude**: `claude mcp add marm-memory http://localhost:8001/mcp`
3. **Test**: `marm_start` → `marm_system_info`

**That's it!** You now have AI memory that saves across sessions and platforms.

---

## System Requirements

### **Linux Requirements**

- **OS**: Ubuntu 18.04+, Debian 10+, CentOS 8+, Fedora 30+, or any modern Linux distribution
- **Python**: 3.8 or higher
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

### **Option 1: Automated Installation** ⭐ **(Recommended)**

```bash
pip install marm-mcp-server==2.2.3
cd MARM/marm-mcp-server
chmod +x install.sh
./install.sh
```

### **Option 2: Quick Test** ⚡ **(Beginner-Friendly)**

```bash
pip install marm-mcp-server==2.2.3
cd MARM/marm-mcp-server
python3 server.py
```

>Dependencies auto-install if missing

### **Option 3: Manual Installation** 🔧 **(Advanced)**

```bash
pip install marm-mcp-server==2.2.3
cd MARM/marm-mcp-server

# Create virtual environment (recommended)
python3 -m venv marm-env
source marm-env/bin/activate

# Install dependencies
pip install marm-mcp-server==2.2.3

# Start server
python3 server.py
```

### **After Installation:**

**Server starts on**: `http://localhost:8001`
**MCP Endpoint**: `http://localhost:8001/mcp`
**API Documentation**: `http://localhost:8001/docs`

---

## Distribution-Specific Setup

### **Ubuntu/Debian**

```bash
# Install prerequisites
sudo apt update
sudo apt install python3 python3-pip python3-venv git

# Clone and install MARM
pip install marm-mcp-server==2.2.3
cd MARM/marm-mcp-server
./install.sh
```

### **CentOS/RHEL/Fedora**

```bash
# Install prerequisites
sudo dnf install python3 python3-pip git  # Fedora
# sudo yum install python3 python3-pip git  # CentOS/RHEL

# Clone and install MARM
pip install marm-mcp-server==2.2.3
cd MARM/marm-mcp-server
./install.sh
```

### **Arch Linux**

```bash
# Install prerequisites
sudo pacman -S python python-pip git

# Clone and install MARM
pip install marm-mcp-server==2.2.3
cd MARM/marm-mcp-server
./install.sh
```

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

## Verification & Testing

### **Built-in Container Tests (Recommended)**

**MARM includes professional diagnostic tests that validate your local deployment:**

| Test Type | Command | What It Validates | Run Time |
|-----------|---------|-------------------|----------|
| **Security Validation** | `python3 tests/test_security.py` | XSS protection, input validation, error handling | ~15 seconds |
| **Performance Test** | `python3 tests/test_performance.py` | Response times, concurrent handling, server stability | ~30 seconds |
| **Integration Test** | `python3 tests/test_integration.py` | End-to-end MCP tool functionality, API responses | ~25 seconds |
| **Memory Usage** | `python3 tests/test_memory_usage.py` | Local process memory efficiency, resource usage | ~20 seconds |
| **MCP Size Limits** | `python3 tests/test_mcp_size_limits.py` | MCP protocol 1MB response compliance | ~30 seconds |

### **When and Why to Use Each Test**

**Security Test** - Run first to ensure your MARM installation is secure from XSS attacks and handles malicious input properly. Essential for any deployment.

**Performance Test** - Validates response times and concurrent request handling. Use this to ensure MARM meets professional speed standards on your hardware.

**Integration Test** - Tests all MCP tools end-to-end to make sure everything works together. Best for verifying a complete installation.

**Memory Usage Test** - Measures local Python process memory consumption. Unlike Docker testing, this shows how MARM performs on your specific system with your available resources.

**MCP Size Limits Test** - Ensures responses stay under the 1MB MCP protocol limit. Important for compatibility with MCP clients and preventing oversized responses that could cause issues.

### **Why Built-in Tests Beat Traditional Commands**

**Traditional approach:**

```bash
curl http://localhost:8001/health  # Only tests basic connectivity
tail -20 server.log                # Shows logs but no validation
```

**MARM's integrated testing:**

- **Comprehensive validation** - Tests all major systems, not just connectivity
- **Performance benchmarking** - Measures actual response times and throughput
- **Professional scoring** - Get objective performance metrics (0-100 scores)
- **Troubleshooting data** - Detailed diagnostics when things go wrong

### **Quick Health Check**

```bash
# Traditional health check (still useful for quick validation)
curl -s http://localhost:8001/health
```

**Expected Health Response:**

```json
{
  "status": "healthy",
  "version": "2.2.3",
  "memory_mb": 510.8,
  "uptime_seconds": 45
}
```

### **Found Issues? We Want to Hear!**

If any tests fail or you encounter problems:

- **🐛 Open an [Issue]((<https://github.com/Lyellr88/MARM-Systems/issues>)**: Report problems on GitHub
- **🔧 Submit a [Pull Request](https://github.com/Lyellr88/MARM-Systems/pulls)**: Fixed it yourself? We welcome contributions!
- **💬 Join Discussions**: Share feedback and get help from the community

Your testing helps make MARM better for everyone.

---

## Updating & Reinstalling

### **Updating MARM to Latest Version** 🔄 **(Easy)**

**Standard Update Process:**

1. **Stop MARM Server**: `Ctrl+C` or stop Docker container
2. **Backup Your Data** (Recommended):

   ```bash
   cp -r ~/.marm ~/.marm_backup_$(date +%Y%m%d)
   ```

3. **Pull Latest Code**:

   ```bash
   cd MARM/marm-mcp-server
   git pull origin main
   ```

4. **Update Dependencies**:

   ```bash
   pip install marm-mcp-server==2.2.3 --upgrade
   ```

5. **Restart Server**: `marm-mcp-server`

---

### **Clean Reinstall (Reset Everything)** ⚠️ **(Advanced)**

**Warning**: This will delete all your memories, sessions, and notebooks.

```bash
# Stop server
# Delete data directory
rm -rf ~/.marm  # Unix/Mac
# rmdir /s %USERPROFILE%\.marm  # Windows

# Fresh installation
pip install marm-mcp-server==2.2.3
cd MARM/marm-mcp-server
./install.sh  # or python setup.py on Windows
```

### **Migration Notes**

**v2.0 → v2.2.4 Migration:**

- Database schema is compatible - no migration needed
- New tools automatically available after restart
- Docker images are backward compatible with persistent volumes

**Data Preservation:**

- All memories stored in `~/.marm/marm_memory.db`
- Notebooks stored in same database
- Analytics data stored in `~/.marm/analytics.db`

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
- **Python not found**: Install Python 3.8+: `sudo apt install python3 python3-pip`
- **Module import errors**: Install missing packages: `pip3 install -r requirements.txt`

### **Still Having Issues?**

Run the diagnostic tests - they provide detailed error information:

```bash
python3 tests/test_security.py
```

---

## Configuration

### **Environment Variables**

Set environment variables in your shell:

```bash
export SERVER_PORT=8002
export ANALYTICS_ENABLED=false
python3 server.py
```

**Or permanently in ~/.bashrc:**

```bash
echo 'export SERVER_PORT=8002' >> ~/.bashrc
echo 'export ANALYTICS_ENABLED=false' >> ~/.bashrc
source ~/.bashrc
```

### **Available Environment Variables**

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_PORT` | `8001` | Server port |
| `MAX_DB_CONNECTIONS` | `5` | Database connection pool size |
| `ANALYTICS_ENABLED` | `true` | Usage analytics (privacy-conscious) |
| `DEFAULT_SEMANTIC_MODEL` | `all-MiniLM-L6-v2` | AI model for semantic search |

---

**MARM v2.2.4 Linux Guide** - *Universal memory intelligence for AI agents*

*For usage instructions, see **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)***

*For Docker deployment, see **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)***

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
