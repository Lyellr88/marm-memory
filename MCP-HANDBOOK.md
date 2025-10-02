# MARM MCP Server Handbook

**MARM v2.2.5 - Universal MCP Server for AI Memory Intelligence

---

## Table of Contents

- [Getting Started](#getting-started)
- [Understanding MARM Memory](#understanding-marm-memory)
- [Complete Tool Reference (18 Tools)](#complete-tool-reference-18-tools)
- [Cross-App Memory Strategies](#cross-app-memory-strategies)
- [Pro Tips & Best Practices](#pro-tips--best-practices)
- [Advanced Workflows](#advanced-workflows)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## Getting Started

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

- Strict `YYYY-MM-DD-topic-summary` format
- Best for: Daily logs, progress tracking, audit trails

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

## Troubleshooting

### Memory Not Finding Expected Results

**Solution**: Check content classification, use `marm_log_show` to browse manually

### Session Confusion

**Solution**: Use `marm_system_info` to check current session status (current_context works automatically in background)

### Performance Issues

**Solution**: Use log compaction, `marm_system_info` to check statistics

### Lost Context

**Solution**: `marm_refresh` to reset, `marm_smart_recall` to recover

---

## FAQ

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
