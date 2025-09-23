# MARM Handbook v2.2.5 (mainly for copy & paste users)

## Table of Contents

- [Short Introduction](#short-introduction)
- [What's New](#whats-new)
- [Part I: Core Principles](#part-i-core-principles)
- [Live Chatbot Demo](#live-chatbot-demo)
- [Part II: Quick Start Walkthrough](#part-ii-quick-start-walkthrough)
- [Part III: Command Reference](#part-iii-command-reference)
- [Part IV: Beyond the Basics](#part-iv-beyond-the-basics)
- [Quick Reference Table](#quick-reference-table)
- [Troubleshooting Guide](#troubleshooting-guide)

---

## Short Introduction

MARM is a universal protocol designed to improve memory continuity and response accuracy during AI conversations. This handbook covers beginner guidance, command usage, and recovery strategies for when memory or accuracy begins to drift.

## What's New

<details>
<summary>View MARM version updates</summary>

| Version | Key Features | Major Changes |
|---------|-------------|---------------|
| **v1.2** | Session Relay Tools | `/summary:`, reseeding, schema enforcement |
| **v1.3** | Manual Knowledge Library | `/notebook` commands introduced |
| **v1.4** | Enhanced Commands | Expanded `/log` and `/notebook` functionality |
| **v1.5** | Live Chatbot | Session persistence, voice synthesis, command menu |
| **v2.0** | Major Protocol Overhaul | Updated syntax, enhanced chatbot, Llama 4 Maverick |

### v2.2.5 (Current) - Universal MCP Server

#### MCP Server Architecture

- **19 Complete MCP Tools** - Full Model Context Protocol implementation with semantic search
- **Production FastAPI Backend** - SQLite with WAL mode, connection pooling, rate limiting
- **Cross-Platform Compatibility** - Works with Claude Code, Qwen CLI, Gemini CLI, Grok CLI
- **Docker Deployment** - Containerized with health monitoring and professional diagnostics

#### Memory Intelligence Features

- **Semantic Search** - AI-powered similarity search using sentence-transformers
- **Auto-Classification** - Content intelligently categorized (code, project, book, general)
- **Cross-Session Memory** - Memories persist across different AI agent conversations
- **Smart Recall** - Vector similarity search with context-aware fallbacks

#### Technical Excellence

- **Database Optimization** - Custom connection pooling with configurable limits
- **MCP Compliance** - 1MB response size management with intelligent truncation
- **Security Hardening** - IP-based rate limiting, XSS protection, error isolation
- **Performance Monitoring** - Built-in diagnostic tests and health validation

</details>

## Part I: Core Principles

### What is MARM?

MEMORY ACCURATE RESPONSE MODE (MARM) ensures accurate AI interactions by maintaining context through structured, user-directed controls. It prevents memory drift, improving AI transparency and reliability.

**Powered by Llama 4 Maverick** - 400B parameter multimodal model providing cost-effective AI intelligence.

### Why Manual Steps Matter

Manual logging, knowledge entry, and accuracy checks prevent silent drift. User visibility ensures context and accuracy remain aligned.

**User Controls:**

- **Memory:** `/log session:`, `/log entry:`.
- **Knowledge:** `/notebook` commands.
- **Accuracy:** `/deep dive`, `/show reasoning`.

This approach ensures the AI works with **user-led intent**, reducing drift across sessions and platforms.

## Live Chatbot Demo

### Try MARM Online

Experience MARM instantly at [MARM Chatbot](https://marm-systems-chatbot.onrender.com):

- **No setup required** - Start using MARM immediately
- **Full protocol support** - All commands work as documented
- **Modern interface** - Command menu, voice synthesis, file uploads
- **Session persistence** - Conversations survive browser refreshes

### Quick Demo Steps

1. **Visit the demo** → Type `/start marm` to activate
2. **Use command menu** → Click ⚡ button for quick access to all commands
3. **Try key features** → Upload files, use voice synthesis, save sessions
4. **Experience the difference** → Notice improved memory and context retention

---

## Part II: Quick Start Walkthrough

### Step 1: Start & Label Session

/start marm
/log session: ProjectAlpha

### Step 2: Log Milestones Throughout Work

/log entry: [2025-07-14 | Set project scope | Phase 1 started]
/log entry: [2025-07-14 | Completed wireframes | Ready for review]

### Step 3: Handle Topic Shifts

When switching focus mid-session:
/log entry: [2025-07-14 | Pivoted to API design | Frontend work paused]
/refresh marm

### Step 4: Summarize Progress

/summary: ProjectAlpha

Output example:
[2025-07-14 | Set project scope | Phase 1 started]
[2025-07-14 | Completed wireframes | Ready for review]
[2025-07-14 | Pivoted to API design | Frontend work paused]

### Step 5: Reseed Context (New Session)

After summary, copy reseed block:
/start marm
/log session: ProjectAlpha
[paste reseed block]
/notebook add: project_tone Professional, technical documentation style

## Part III: Command Reference

| Category | Command | Purpose | Usage Notes |
|----------|---------|---------|-------------|
| **Session** | `/start marm` | Activates memory & accuracy layers | Must be first command |
| **Session** | `/refresh marm` | Recenters AI mid-session | Use after 8-10 turns or topic pivots |
| **Logging** | `/log session: [name]` | Labels session (project naming) | Think of it as creating folders |
| **Logging** | `/log entry: [YYYY-MM-DD-topic-summary]` | Logs structured milestones | Schema enforced, corrects invalid formats |
| **Accuracy** | `/deep dive` | Forces accuracy-driven responses | Includes self-checks and validation |
| **Accuracy** | `/show reasoning` | Displays AI's reasoning trail | Use for transparency and verification |
| **Summary** | `/summary: [SessionName]` | Provides condensed log + reseed block | One-line-per-entry format |
| **Notebook** | `/notebook add: [name] [data]` | Add trusted user-defined info | Keep entries concise for token efficiency |
| **Notebook** | `/notebook use: [name]` | Activate entries | Multiple via comma: `name1,name2` |
| **Notebook** | `/notebook show:` | Lists all stored keys | Check token usage and available entries |
| **Notebook** | `/notebook clear:` | Clears active list | Does not delete stored entries |
| **Notebook** | `/notebook status:` | Shows current active list | View what's currently activated |

**Critical Notebook Behaviors:**

- Entries are **session-bound** - they don't persist across chats
- Must be manually reseeded each new session
- Token limits apply - keep entries concise
- Ideal for: project guidelines, tone rules, technical specs, workflow definitions

## Part IV: Beyond the Basics

### Real-World Use Cases

#### Multi-Session Projects

| Day | Actions | Commands |
|-----|---------|----------|
| **Day 1** | Define MVP, identify features | `/log session: AppRedesign` → `/log entry:` → `/notebook add:` → `/summary:` |
| **Day 2** | Continue in new chat | `/start marm` → reseed block → `/notebook add:` → continue work |

#### Enhanced Accuracy Mode

| Use Case | Commands | Benefits |
|----------|----------|----------|
| **Legal docs, specs** | `/deep dive [task]` → `/show reasoning` | Enhanced validation, reasoning transparency |

#### Complex Topic Management

| Scenario | Action | Commands |
|----------|--------|----------|
| **Topic shift** | Log transition, refresh focus | `/log entry:` → `/refresh marm` → `/summary:` |

---

### Session Drift Management
  
#### When to Refresh/Reseed

- Every **8-10 conversation turns**
- After **any major topic pivot**
- When AI responses feel **generic or unfocused**
- Before **critical decisions or outputs**

#### Drift Recovery Process

Detect drift (generic responses, lost context)
/refresh marm
/summary: [Session]
Review last 3-5 entries
/deep dive for next response

#### Preventive Maintenance

Every 10 turns:
/summary: SessionName
/refresh marm
/notebook show:  [verify key data intact]

---

### Manual Knowledge Library Deep Dive
  
#### Token Management Strategy

Bad (token heavy):
/notebook add: project_details This is a comprehensive project involving multiple stakeholders including...
Good (token efficient):
/notebook add: project_type B2B SaaS platform
/notebook add: stakeholders PM:John, Dev:Sarah, Design:Mike
/notebook add: deadline 2025-08-30

#### Multi-Key Strategies

Organize related info:
/notebook add: api_base <https://api.example.com/v2>
/notebook add: api_auth Bearer token in header
/notebook add: api_ratelimit 100 req/min

#### Session-Bound Behavior

Notebook entries **vanish** on new chat. Always reseed critical keys:
Essential reseed template:
/start marm
/log session:[Name]
[paste summary block]
/notebook add: tone [saved tone preference]
/notebook add: context [saved project context]

---

### Platform Compatibility

| Platform | Memory Type | Key Challenges | MARM Strategy | Refresh Frequency |
|----------|-------------|----------------|---------------|-------------------|
| **ChatGPT** | Native memory (drifts) | Conflates sessions, assumptions | Use `/summary:` + `/refresh marm` | Every 5-7 turns |
| **Claude** | Stateless | Zero memory between sessions | Full reseed required, verbose labels | New session start |
| **Replicate** | Stateless | API-based, token limits | Reliable, cost-effective | As needed |
| **Local Models** | Stateless | Variable token limits | Minimal notebook entries | Context dependent |

---

### Power-User Templates

| Template | Setup Commands | Key Benefits |
|----------|----------------|---------------|
| **Project Management** | `/log session: Sprint24` → `/notebook add: sprint_goal` | Track sprint progress, team info |
| **Daily Standups** | `/log session: DailyStandups` → `/log entry:` pattern | Quick daily progress logging |
| **Code Review** | `/log session: PR-[number]` → `/notebook add: blockers` | Systematic review tracking |

#### Advanced Integration

| Pattern | Process | Benefit |
|---------|---------|----------|
| **Multi-LLM Bridge** | Export `/summary:` → Import to new AI | Cross-platform continuity |
| **External Memory** | Hook `/summary` → Notion/Docs | Persistent storage automation |

---

### Advanced Session Patterns

| Pattern | Structure | Use Case |
|---------|-----------|----------|
| **Session Chaining** | Phase1 → `/summary:` → Phase2 | Long-term project progression |
| **Parallel Sessions** | Multiple tabs with related session names | Complex multi-threaded work |

---

## Quick Reference Table

### Expand Quick Reference Table

| Feature                  | Command Example                                | Best Practice |
|--------------------------|------------------------------------------------|---------------|
| Start MARM               | `/start marm`                                  | Always first command |
| Refresh MARM             | `/refresh marm`                                | Every 8-10 turns |
| Log Session              | `/log session: ProjectX`                       | Use descriptive names |
| Log Entry                | `/log entry: [YYYY-MM-DD-topic-summary]`        | Log key decisions only |
| Summary                  | `/summary: ProjectX`                           | Before session end |
| Accuracy Mode            | `/deep dive`                                   | For critical outputs |
| Show Reasoning           | `/show reasoning`                              | Verify logic paths |
| Reseed (Manual)          | Paste summary block into new session           | Include notebook entries |
| Notebook Add             | `/notebook add: style Professional`            | Keep concise |
| Notebook Use             | `/notebook use: style_guide,api_rules`         | Activate multiple with commas |
| Notebook Show All        | `/notebook show:`                              | Check token usage |
| Notebook Clear           | `/notebook clear:`                             | Clear active list only |
| Notebook Status          | `/notebook status:`                            | View current active list |

---

## Troubleshooting Guide

| Problem | Symptoms | Solution |
|---------|----------|----------|
| **Context Loss** | AI forgot previous discussion | `/refresh marm` → `/summary: [session]` → `/notebook show:` |
| **Generic Responses** | Vague, unfocused answers | `/deep dive` → add context to notebook → `/log entry:` |
| **Session Overload** | Too much context, poor performance | `/summary: [session]` → new session → reseed essentials |
| **Platform Conflicts** | Native memory interfering | `/refresh marm` → trust MARM over platform suggestions |

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
