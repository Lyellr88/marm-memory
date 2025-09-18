# MARM MCP Server - Windows Installation

## Universal Memory Intelligence Platform for AI Agents

**MARM v2.1** - Memory Accurate Response Mode
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

1. **Install MARM**: Choose ⚡ **Quick Test** (Beginner) or ⭐ **Automated** (Easy) from options below
2. **Connect Claude**: `claude mcp add marm-memory http://localhost:8001/mcp`
3. **Test**: `marm_start` → `marm_system_info`

**That's it!** You now have AI memory that saves across sessions and platforms.

---

## System Requirements

### **Windows Requirements**

- **OS**: Windows 10/11 (64-bit)
- **Python**: 3.8 or higher ([Download Python](https://python.org/downloads))
- **Memory**: 1GB RAM available
- **Storage**: ~500MB disk space
- **Network**: Internet connection for initial setup

### **PowerShell vs Command Prompt**

- **PowerShell** (Recommended) - Better Unicode support, modern features
- **Command Prompt** - Works but may have encoding issues with emojis

---

## Installation Options

### **Option 1: Automated Installation** ⭐ **(Recommended)**

**PowerShell (as Administrator):**

```powershell
git clone https://github.com/MARM-Systems/MARM.git
cd MARM\marm-mcp-server
python setup.py
```

### **Option 2: Quick Test** ⚡ **(Beginner-Friendly)**

```powershell
git clone https://github.com/Lyellr88/MARM-Systems.git
cd MARM\marm-mcp-server
python server.py
```

>Dependencies auto-install if missing

### **Option 3: Manual Installation** 🔧 **(Advanced)**

```powershell
git clone https://github.com/Lyellr88/MARM-Systems.git
cd MARM\marm-mcp-server

# Create virtual environment (recommended)
python -m venv marm-env
marm-env\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start server
python server.py
```

### **After Installation:**

**Server starts on**: `http://localhost:8001`
**MCP Endpoint**: `http://localhost:8001/mcp`
**API Documentation**: `http://localhost:8001/docs`

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
| **Qwen CLI** | `qwen-oauth` |
| **Gemini CLI** | `oauth-personal` |
| **Grok CLI** | `grok-oauth` |

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
| **Security Validation** | `python tests\test_security.py` | XSS protection, input validation, error handling | ~15 seconds |
| **Performance Test** | `python tests\test_performance.py` | Response times, concurrent handling, server stability | ~30 seconds |
| **Integration Test** | `python tests\test_integration.py` | End-to-end MCP tool functionality, API responses | ~25 seconds |
| **Memory Usage** | `python tests\test_memory_usage.py` | Local process memory efficiency, resource usage | ~20 seconds |
| **MCP Size Limits** | `python tests\test_mcp_size_limits.py` | MCP protocol 1MB response compliance | ~30 seconds |

### **When and Why to Use Each Test**

**Security Test** - Run first to ensure your MARM installation is secure from XSS attacks and handles malicious input properly. Essential for any deployment.

**Performance Test** - Validates response times and concurrent request handling. Use this to ensure MARM meets professional speed standards on your hardware.

**Integration Test** - Tests all MCP tools end-to-end to make sure everything works together. Best for verifying a complete installation.

**Memory Usage Test** - Measures local Python process memory consumption. Unlike Docker testing, this shows how MARM performs on your specific system with your available resources.

**MCP Size Limits Test** - Ensures responses stay under the 1MB MCP protocol limit. Important for compatibility with MCP clients and preventing oversized responses that could cause issues.

### **Why Built-in Tests Beat Traditional Commands**

**Traditional approach:**

```powershell
Invoke-WebRequest http://localhost:8001/health  # Only tests basic connectivity
Get-Content server.log                          # Shows logs but no validation
```

**MARM's integrated testing:**

- **Comprehensive validation** - Tests all major systems, not just connectivity
- **Performance benchmarking** - Measures actual response times and throughput
- **Professional scoring** - Get objective performance metrics (0-100 scores)
- **Troubleshooting data** - Detailed diagnostics when things go wrong

### **Quick Health Check**

```powershell
# Traditional health check (still useful for quick validation)
Invoke-WebRequest -Uri http://localhost:8001/health
```

**Expected Health Response:**

```json
{
  "status": "healthy",
  "version": "2.1.0",
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
   pip install -r requirements.txt --upgrade
   ```

5. **Restart Server**: `python server.py`

**🐳 Docker Update:**

```bash
docker pull lyellr88/marm-mcp-server:latest
docker stop marm-mcp-server
docker rm marm-mcp-server
docker run -d --name marm-mcp-server -p 8001:8001 -v marm-data:/home/marm/.marm --restart unless-stopped lyellr88/marm-mcp-server:latest
```

### **Clean Reinstall (Reset Everything)** ⚠️ **(Advanced)**

**Warning**: This will delete all your memories, sessions, and notebooks.

```bash
# Stop server
# Delete data directory
rm -rf ~/.marm  # Unix/Mac
# rmdir /s %USERPROFILE%\.marm  # Windows

# Fresh installation
git clone https://github.com/Lyellr88/MARM-Systems.git
cd MARM/marm-mcp-server
./install.sh  # or python setup.py on Windows
```

### **Migration Notes**

**v2.0 → v2.1 Migration:**

- Database schema is compatible - no migration needed
- New tools automatically available after restart
- Docker images are backward compatible with persistent volumes

**Data Preservation:**

- All memories stored in `~/.marm/marm_memory.db`
- Notebooks stored in same database
- Analytics data stored in `~/.marm/analytics.db`

--

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

### **Still Having Issues?**

Run the diagnostic tests - they provide detailed error information:

```powershell
python tests\test_security.py
```

---

## Configuration

### **Environment Variables**

Set environment variables in PowerShell:

```powershell
$env:SERVER_PORT="8002"
$env:ANALYTICS_ENABLED="false"
python server.py
```

**Or permanently via System Properties:**

1. Search "Environment Variables" in Start Menu
2. Click "Environment Variables..." button
3. Add under "User variables"

### **Available Environment Variables**

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_PORT` | `8001` | Server port |
| `MAX_DB_CONNECTIONS` | `5` | Database connection pool size |
| `ANALYTICS_ENABLED` | `true` | Usage analytics (privacy-conscious) |
| `DEFAULT_SEMANTIC_MODEL` | `all-MiniLM-L6-v2` | AI model for semantic search |

---

## Windows-Specific Features

### **Windows Service (Advanced)**

To run MARM as a Windows service:

```powershell
# Install as service (requires admin)
python server.py --install-service

# Start/stop service
net start MARMService
net stop MARMService
```

### **Startup Scripts**

Create `start_marm.bat` for easy startup:

```batch
@echo off
cd /d "C:\path\to\MARM\marm-mcp-server"
python server.py
pause
```

### **WSL Integration**

MARM works perfectly in Windows Subsystem for Linux:

```bash
# In WSL terminal
git clone https://github.com/Lyellr88/MARM-Systems.git
cd MARM/marm-mcp-server
python server.py
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

- `C:\Users\{username}\MARM\`
- `C:\Users\{username}\.marm\`

---

**MARM v2.1 Windows Guide** - *Universal memory intelligence for AI agents*

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
