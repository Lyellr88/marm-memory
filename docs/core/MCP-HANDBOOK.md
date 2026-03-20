# MARM MCP Server Handbook

## Complete Usage Guide for Memory-Augmented AI

**MARM v2.2.7 - Universal MCP Server for AI Memory Intelligence

---

## Table of Contents

- [Installation & Transport Options](#installation--transport-options)
- [Getting Started](#getting-started)
- [Example Workflow](#example-workflow-cross-ai-research-project)
- [Understanding MARM Memory](#understanding-marm-memory)
- [Complete Tool Reference (18 Tools)](#complete-tool-reference-18-tools)
- [Cross-App Memory Strategies](#cross-app-memory-strategies)
- [Pro Tips & Best Practices](#pro-tips--best-practices)
- [Advanced Workflows](#advanced-workflows)
- [FAQ](#faq)
- [Troubleshooting Guide](#troubleshooting-guide)

---

## Installation & Transport Options

### HTTP vs STDIO

MARM MCP Server supports two transport modes for different deployment scenarios:

**HTTP Transport** (Default)
- Traditional server-client architecture
- Best for: Multiple concurrent AI clients, cloud/remote deployment, shared memory server
- Setup: Run `marm-mcp-server` and connect via `http://localhost:8001/mcp`

**STDIO Transport** (Process-based)
- Direct stdin/stdout communication
- Best for: CLI tools, orchestration platforms, Cursor IDE, single AI client per process
- Setup: Run `python server_stdio.py` via MCP client configuration
- Advantage: No port management, process isolation per connection

### Quick Start Guide

**Docker (HTTP - Fastest):**

```bash
docker pull lyellr88/marm-mcp-server:latest
docker run -d --name marm-mcp-server -p 8001:8001 -v ~/.marm:/home/marm/.marm lyellr88/marm-mcp-server:latest
claude mcp add --transport http marm-memory http://localhost:8001/mcp
```

**Local HTTP:**

```bash
pip install marm-mcp-server==2.2.7
pip install -r marm-mcp-server/requirements.txt
python marm-mcp-server
claude mcp add --transport http marm-memory http://localhost:8001/mcp
```

**STDIO:**

```bash
pip install marm-mcp-server==2.2.7
pip install -r marm-mcp-server/requirements_stdio.txt
<platform> mcp add --transport stdio marm-memory-stdio python "your/file/path/to/marm-mcp-server/server_stdio.py"
python marm-mcp-server/server_stdio.py
```

Replace `<platform>` with: `qwen`, `claude`, or `gemini` depending on your AI CLI tool.

**For complete installation instructions, platform-specific configurations, JSON setup, troubleshooting, and detailed transport comparison, see the [README.md Quick Start section](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/README.md#-quick-start-for-mcp).**

### System Requirements

- **Python**: 3.10 or higher
- **SQLite3**: Included with Python (no separate install needed)
- **Storage**: ~100MB minimum for initial setup, scales with memory database size
- **RAM**: 512MB minimum (varies by concurrent clients and database size)
- **OS**: Windows, macOS, Linux

### Data Location & Backup

All MARM data is stored locally in your home directory:

- **Location**: `~/.marm/` (Linux/macOS) or `%USERPROFILE%\.marm\` (Windows)
- **Contents**: SQLite database with all memories, sessions, and notebooks
- **Backup**: Copy the entire `~/.marm/` directory to preserve all data
- **Privacy**: Everything stays on your machine — no cloud sync or external storage

### Verify Installation

After installation, verify MARM is working correctly:

```bash
# HTTP - Check server is running
curl http://localhost:8001/mcp/health

# Or use the MARM system info tool (once connected to your AI client)
# Ask your AI: "Check MARM system status" - it will call marm_system_info
```

Expected output includes:
- Server version (2.2.7)
- Database size in MB
- Total memories and sessions count
- Feature availability (semantic search status)

---

## Getting Started

### 💡 **Key Point: Natural Language Interface**

**You don't need to manually call MARM tools!** Just talk to your AI agent naturally:

- *"Claude, log this session as 'Project Alpha'"*
- *"Remember this code snippet for later"*
- *"Search for what we discussed about authentication"*
- *"Add this debugging approach to my notebook"*

Your AI agent will automatically use the appropriate MARM tools. Manual tool access is available for power users, but most users should just **talk naturally** and let the AI handle the tool usage.

### What is MARM?

MARM is a **Universal MCP Server** providing intelligent memory that saves across sessions for AI conversations with:

- **Semantic Search** - Find memories by meaning, not keywords
- **Cross-App Memory** - Share memories between AI clients (Claude, Qwen, Gemini)
- **Auto-Classification** - Content automatically categorized for intelligent recall
- **Session Management** - Organize conversations with structured logging

### Core Concepts

**Sessions**: Named containers for organizing memories
**Memories**: Stored content with semantic embeddings for intelligent search
**Notebooks**: Reusable instructions and knowledge snippets
**Logging**: Structured conversation history with timestamps

### Example Workflow: Cross-AI Research Project

Here's a realistic workflow showing MARM in action:

**Scenario:** You're researching authentication patterns for a new project using multiple AI clients.

**Phase 1: Start Session (Claude)**
```
You: "Claude, activate MARM and create a session called 'auth-research-2025-01'"
Claude calls: marm_start("auth-research-2025-01")
Claude calls: marm_log_session("auth-research-2025-01")
Result: Session created, MARM active for this conversation
```

**Phase 2: Capture Research (Claude)**
```
You: "Summarize OAuth2 vs JWT for API authentication and save it"
Claude calls: marm_contextual_log("OAuth2 is token-based with refresh cycles, better for delegated access. JWT is stateless, good for microservices...")
Result: Memory stored with auto-classification as "code" content
```

**Phase 3: Add Reusable Reference (Claude)**
```
You: "Save a JWT validation code snippet to my notebooks as 'jwt-validation-pattern'"
Claude calls: marm_notebook_add("jwt-validation-pattern", "def verify_jwt(token):\n  # validation logic...")
Result: Reusable snippet stored for future projects
```

**Phase 4: Recall Context (Gemini)**
```
You: "Gemini, what authentication approaches did we research? Activate the JWT pattern."
Gemini calls: marm_smart_recall("authentication patterns", search_all=true)
Gemini calls: marm_notebook_use("jwt-validation-pattern")
Result: Gemini sees previous research + has JWT code available as context
```

**Phase 5: Synthesis & Summary (Qwen)**
```
You: "Qwen, pull everything from the auth research and create a summary"
Qwen calls: marm_smart_recall("authentication", session="auth-research-2025-01", limit=20)
Qwen calls: marm_summary("auth-research-2025-01")
Result: Qwen generates implementation guide from all captured research
```

**Phase 6: End Session (Claude)**
```
You: "Log final decision - we're using JWT for APIs and OAuth2 for user auth"
Claude calls: marm_log_entry("DECISION: JWT for API auth, OAuth2 for user flows. Rationale: stateless APIs + delegated user access", session="auth-research-2025-01")
Result: Decision logged and searchable by all future AI clients
```

**Result**: Three different AI clients collaboratively researched a topic, shared insights, and documented decisions—all without re-explaining the project to each new AI.

---

## Understanding MARM Memory

### How Memory Works

MARM uses **semantic embeddings** to understand content meaning, not exact word matches:

```txt
User: "I discussed machine learning algorithms yesterday"
MARM Search: Finds related memories about "ML models", "neural networks", "AI training"
```

### Memory Types

1. **Contextual Logs** - Auto-classified conversation memories
2. **Manual Entries** - Explicitly saved important information  
3. **Notebook Entries** - Reusable instructions and knowledge
4. **Session Summaries** - Compressed conversation history

### Content Classification

MARM automatically categorizes content:

- **Code** - Programming snippets and technical discussions
- **Project** - Work-related conversations and planning
- **Book** - Literature, learning materials, research
- **General** - Casual conversations and miscellaneous topics

### Revolutionary Multi-AI Memory System

- **Beyond Single-AI Memory:** Unified memory layer that saves data, accessible by *any* connected LLM that supports MCP
- **Cross-Platform Intelligence:** Different AIs learn from each other's interactions and contribute to a shared knowledge base
- **User-Controlled Hybrid Memory:** Granular control over memory sharing and ability to import existing chat logs

---

## Adding Content to MARM Memory

MARM provides three primary ways to store information:

**`marm_contextual_log`** - General-Purpose "Smart" Memory

- Auto-classifying memory storage with embeddings
- Best for: Key decisions, solutions, important insights

**`marm_log_entry`** - Structured Chronological Milestones

- Auto-formatted with timestamps (no manual date needed)
- Best for: Daily logs, progress tracking, milestones, decisions

**`marm_notebook_add`** - Reusable Instructions

- Store reusable instructions and knowledge
- Best for: Code snippets, style guides, procedures

---

## Complete Tool Reference (18 Tools)

| Category | Tool | Description | Usage Notes |
|----------|------|-------------|-------------|
| **🚀 Session** | `marm_start` | Activate MARM memory and accuracy layers | Call at beginning of important conversations |
| | `marm_refresh` | Refresh session state and reaffirm protocol adherence | Reset MARM behavior if responses become inconsistent |
| **🧠 Memory** | `marm_smart_recall` | Semantic similarity search across all memories | `query` (required), `limit` (default: 5), `session_name` (optional). Use natural language queries |
| | `marm_contextual_log` | Auto-classifying memory storage with embeddings | Store important information that should be remembered |
| **📚 Logging** | `marm_log_session` | Create or switch to named session container | Include LLM name, dates, be descriptive |
| | `marm_log_entry` | Add structured log entry with auto-date formatting | No need to add dates manually - automatically handled by background tools |
| | `marm_log_show` | Display all entries and sessions with filtering | `session_name` (optional) |
| | `marm_log_delete` | Delete specified session or individual entries | Permanent deletion - use carefully |
| **📔 Notebook** | `marm_notebook_add` | Add new notebook entry with semantic embeddings | Store reusable instructions, code snippets, procedures |
| | `marm_notebook_use` | Activate entries as instructions (comma-separated) | Example: `marm_notebook_use("coding-standards,git-workflow")` |
| | `marm_notebook_show` | Display all saved keys and summaries | Browse available notebook entries |
| | `marm_notebook_delete` | Delete specific notebook entry | Permanent deletion - use carefully |
| | `marm_notebook_clear` | Clear the active instruction list | Deactivate all notebook instructions |
| | `marm_notebook_status` | Show current active instruction list | Check which instructions are currently active |
| **🔄 Workflow** | `marm_summary` | Generate paste-ready context blocks with intelligent truncation | Create summaries for new conversations or context bridging |
| | `marm_context_bridge` | Intelligent context bridging for workflow transitions | Smoothly transition between different topics or projects |
| **⚙️ System** | `marm_current_context` | **Background Tool** - Automatically provides current date/time for log entries | AI agents use this automatically - you don't need to call it manually |
| | `marm_system_info` | Comprehensive system information, health status, and loaded docs | Server version, database statistics, documentation, capabilities |
| | `marm_reload_docs` | Reload documentation into memory system | Refresh MARM's knowledge after system updates |

---

## Cross-App Memory Strategies

### Multi-LLM Session Organization

**Strategy**: Use LLM-specific session names to track contributions:

```txt
Sessions:
- claude-code-review-2025-01
- qwen-research-analysis-2025-01  
- gemini-creative-writing-2025-01
- cross-ai-project-planning-2025-01
```

### Memory Sharing Workflow

1. **Individual Sessions**: Each AI works in named sessions
2. **Cross-Pollination**: Use `marm_smart_recall` to find relevant insights
3. **Synthesis Sessions**: Create shared sessions where AIs build on each other's work

---

## Pro Tips & Best Practices

### Memory Management Tips

**Log Compaction**: Use `marm_summary`, delete entries, replace with summary
**Session Naming**: Include LLM name for cross-referencing
**Strategic Logging**: Focus on key decisions, solutions, discoveries, configurations

### Search Strategies

**Global Search**: Use `search_all=True` to search across all sessions
**Natural Language Search**: "authentication problems with JWT tokens" vs "auth error"
**Temporal Search**: Include timeframes in queries

### Workflow Optimization

**Notebook Stacking**: Combine multiple entries for complex workflows
**Session Lifecycle**: Start → Work → Reference → End with compaction

---

## Advanced Workflows

### Project Memory Architecture

```txt
Project Structure:
├── project-name-planning/          # Initial design and requirements
├── project-name-development/       # Implementation details
├── project-name-testing/          # QA and debugging notes  
├── project-name-deployment/       # Production deployment
└── project-name-retrospective/    # Lessons learned
```

### Knowledge Base Development

1. **Capture**: Use `marm_contextual_log` for new learnings
2. **Organize**: Create themed sessions for knowledge areas
3. **Synthesize**: Regular `marm_summary` for knowledge consolidation
4. **Apply**: Convert summaries to `marm_notebook_add` entries

### Multi-AI Collaboration Pattern

```txt
Phase 1: Individual Research
- Each AI works in dedicated sessions
- Focus on their strengths (Claude=code, Qwen=analysis, Gemini=creativity)

Phase 2: Cross-Pollination  
- Use marm_smart_recall to find relevant insights
- Build upon previous work

Phase 3: Synthesis
- Create collaborative sessions  
- Combine insights for comprehensive solutions
```

## Migration from MARM Commands

### Transitioning from Text-Based MARM

If you're familiar with the original text-based MARM protocol, the MCP server provides enhanced capabilities while maintaining familiar workflows:

**Command Mapping**:

| Chatbot Command      | MCP Equivalent      | How It Works                                  |
| -------------------- | ------------------- | --------------------------------------------- |
| `/start marm`        | `marm_start`        | Claude calls automatically when needed        |
| `/refresh marm`      | `marm_refresh`      | Claude calls to maintain protocol adherence   |
| `/log session: name` | `marm_log_session`  | Claude organizes work into sessions           |
| `/log entry: details`| `marm_log_entry`    | Claude logs milestones and decisions          |
| `/summary: session`  | `marm_summary`      | Claude generates summaries on request         |
| `/notebook add: item`| `marm_notebook_add` | Claude stores reference information           |
| Manual memory search | `marm_smart_recall` | Claude searches semantically                  |

### Key Improvements in MCP Version

**Enhanced Memory System**:

- Semantic search replaces keyword matching
- Cross-app memory sharing between AI clients
- Automatic content classification
- Data storage with SQLite

**Advanced Features**:

- Multi-AI collaboration workflows
- Global search with `search_all=True`
- Context bridging between topics
- System health monitoring

### Migration Tips

1. **Session Organization**: Use descriptive session names instead of manual date tracking
2. **Memory Management**: Leverage auto-classification instead of manual categorization
3. **Notebook System**: Convert text-based instructions to structured notebook entries
4. **Search Strategy**: Use natural language queries instead of exact keywords

### Backward Compatibility

The MCP server maintains full compatibility with existing MARM concepts:

- Same core commands with enhanced capabilities
- Familiar logging and notebook workflows
- Consistent memory management principles
- Enhanced performance and reliability

---

## FAQ

### Tools

**Q: What MCP tools does MARM provide?**

| Category | Tools |
|----------|-------|
| **Memory Intelligence** | `marm_smart_recall`, `marm_contextual_log` |
| **Session Management** | `marm_start`, `marm_refresh` |
| **Logging System** | `marm_log_session`, `marm_log_entry`, `marm_log_show`, `marm_log_delete` |
| **Notebook Management** | `marm_notebook_add`, `marm_notebook_use`, `marm_notebook_show`, `marm_notebook_clear`, `marm_notebook_status`, `marm_notebook_delete` |
| **Workflow Tools** | `marm_summary`, `marm_context_bridge` |
| **System Utilities** | `marm_system_info`, `marm_reload_docs` |

### General Usage

**Q: How is MARM different from basic AI memory?**
A: Uses semantic understanding, not keyword matching. Works across multiple AI applications.

**Q: Can I use MARM with multiple AI clients simultaneously?**
A: Yes! Designed for cross-app memory sharing. Multiple AIs can access same memory store.

**Q: How much memory can MARM store?**
A: No hard limits - uses efficient SQLite storage with semantic embeddings.

### Memory Management

**Q: When should I create a new session vs. continuing an existing one?**
A: New sessions for distinct topics/projects. Continue existing for related work.

**Q: How does auto-classification work?**
A: Analyzes content to determine if it's code, project work, book/research, or general.

**Q: Can I search across all sessions or just one?**
A: Both! `marm_smart_recall` can search globally or within specific sessions.

### Technical Questions

**Q: What happens if MARM server is offline?**
A: AI client works normally but without memory features. Memory resumes when MARM reconnects.

**Q: How does semantic search work?**
A: Converts text to vector embeddings, finds similar content using vector similarity.

**Q: Can I backup my MARM memory?**
A: Yes - backup the `~/.marm/` directory to preserve all memories.

### Best Practices

**Q: How often should I use log compaction?**
A: At end of significant sessions or weekly for ongoing projects.

**Q: Should I log everything or be selective?**
A: Be selective - log decisions, solutions, insights, key information.

**Q: How do I organize memories for team collaboration?**
A: Use consistent session naming, leverage cross-session search.

### Integration & Setup

**Q: Which AI clients work with MARM?**
A: Any MCP-compatible client: Claude Code, Qwen CLI, Gemini CLI.

**Q: Do I need to restart MARM when switching between AI clients?**
A: No - runs as a background service. Multiple clients can connect simultaneously.

**Q: How do I know if MARM is working correctly?**
A: Use `marm_system_info` to check server status and database statistics.

---

<details>
<summary><b>🔧 Troubleshooting Guide (Click to expand)</b></summary>

## Troubleshooting Guide

### Server Issues

**Server won't start**
- Check Python version: `python --version` (must be 3.10+)
- Verify port 8001 isn't in use: `lsof -i :8001` (macOS/Linux) or `netstat -ano | findstr :8001` (Windows)
- Check for permission errors in home directory (`~/.marm/` must be readable/writable)
- See platform-specific troubleshooting: [INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md), [INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md), [INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)

**STDIO connection fails**
- Ensure `cwd` parameter points to the marm-mcp-server directory
- Verify `server_stdio.py` file exists and is executable
- Check AI client documentation for STDIO transport requirements
- Try direct execution: `python server_stdio.py` to see error messages

### Connection & Integration

**AI client can't connect to MARM**
- Verify server is running: `curl http://localhost:8001/mcp/health`
- Check firewall isn't blocking port 8001
- For STDIO: ensure path to `server_stdio.py` is absolute (not relative)
- Restart both server and AI client

**Tools not appearing in AI client**
- Run `marm_system_info` to verify server loaded correctly
- Check server logs for initialization errors
- Disconnect and reconnect AI client to refresh tool list

### Memory & Data Issues

**Memories not saving**
- Verify `~/.marm/` directory exists and has write permissions
- Check available disk space
- Test with simple memory: ask AI to save a single line and check with `marm_log_show`
- Run `marm_system_info` to check database status

**Search returns no results**
- Verify memories exist: use `marm_log_show` to list entries
- Use `search_all=true` to search across all sessions
- Try simpler, more general search queries
- Wait a few seconds—first semantic search loads the ML model

**Memories appear then disappear**
- Check if MARM was restarted or crashed (data persists in `~/.marm/`)
- Verify disk space didn't fill up
- Check system logs for database errors

### Performance

**Slow search results**
- First search is slower (model loads from disk)—subsequent searches are faster
- Large databases (1000+ memories) may take a few seconds
- Limit searches: use `limit=10` instead of unlimited results
- Use `marm_summary` to compress old sessions

**Server using too much memory**
- Notebooks with many entries can accumulate—use `marm_notebook_clear` to prune
- Close unused AI client connections
- Use log compaction: `marm_summary` + delete old entries

### Data Recovery

**Lost or corrupted data**
- Stop the server immediately
- Check `~/.marm/` directory for backup copies (if you created them)
- Restore from backup: copy your backup `~/.marm/` back to home directory
- Restart server

**Database locked error**
- Close all AI client connections
- Stop the server: `Ctrl+C`
- Remove lock file if present: `rm ~/.marm/marm_usage_analytics.db-wal` (Linux/macOS)
- Restart server

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `address already in use` | Port 8001 occupied | Kill process on 8001 or use different port |
| `permission denied: ~/.marm/` | Database directory not writable | `chmod 755 ~/.marm/` or check ownership |
| `module not found: core.memory` | Missing dependencies | Reinstall: `pip install -r requirements.txt` or `requirements_stdio.txt` |
| `database is locked` | Multiple processes accessing DB | Close other connections, restart server |
| `embedding model not found` | Semantic search model didn't download | First run takes time—be patient, check internet connection |

### When to Check Install Docs

For detailed troubleshooting specific to your platform:
- **Docker issues**: [INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)
- **Windows issues**: [INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)
- **Linux issues**: [INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)
- **Deployment/Platform questions**: [INSTALL-PLATFORMS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORMS.md)

</details>

---

## 📁 Project Documentation

### **Usage Guides**

- **[MARM-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MARM-HANDBOOK.md)** - Original MARM protocol handbook for chatbot usage
- **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)** - Complete MCP server usage guide with commands, workflows, and examples
- **[PROTOCOL.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/PROTOCOL.md)** - Quick start commands and protocol reference

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
- **[CHANGELOG.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHANGELOG.md)** - Version history and updates
- **[ROADMAP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ROADMAP.md)** - Planned features and development roadmap
- **[LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/LICENSE)** - MIT license terms

---

>Built with ❤️ by MARM Systems - Universal MCP memory intelligence
