# MARM Handbook v2.0

## Short Introduction

MARM is a universal protocol designed to improve memory continuity and response accuracy during AI conversations. This handbook covers beginner guidance, command usage, and recovery strategies for when memory or accuracy begins to drift.

## What's New

<details>
<summary>View MARM version updates</summary>

### Previous Versions (v1.2 - v1.5)

**Major milestones:**

- **v1.2**: Session Relay Tools (`/summary:`, reseeding, schema enforcement) integrated
- **v1.3**: Manual Knowledge Library (`/notebook`) introduced
- **v1.4**: Removed ambiguous automation, expanded `/log` and `/notebook` commands
- **v1.5**: First chatbot release with session persistence, voice synthesis, command menu

### v2.0 (Current) - Major Overhaul

#### Protocol Enhancements

- **Updated command syntax**: `/deep dive` replaces `/contextual reply`
- **Enhanced `/notebook`**: New verbs (`add:`, `use:`, `show:`, `clear:`, `status:`)
- **Improved protocol**: Identity-based approach for more consistent AI behavior
- **Better validation**: Enhanced reasoning transparency with `/show reasoning`

#### Live Chatbot Improvements

- **Powered by Llama 4 Maverick** - 400B parameter multimodal model via Replicate
- **96% cost reduction** - $0.25 input + $0.95 output per million tokens vs premium alternatives
- **Universal model support** - Switch between 1000+ models with one line change
- **Adaptive dark/light mode** - Automatic theme detection
- **File upload system** - Text/code file analysis with syntax highlighting
- **Enhanced voice synthesis** - Response-only TTS (MVP)
- **Improved session management** - Better persistence and state restoration
- **Modern UI/UX** - Refined interface with floating action button menu

#### Technical Upgrades

- **Replicate API migration** - From Gemini to Meta's Llama 4 Maverick
- **Performance optimization** - 3-4 second response times with enhanced reliability
- **Security enhancements** - XSS protection with selective allowlisting
- **Cache management** - Improved browser cache handling
- **Modular architecture** - Clean ES6 module separation

</details>

## Part I: Core Principles

### What is MARM?

MEMORY ACCURATE RESPONSE MODE (MARM) ensures accurate AI interactions by maintaining context through structured, user-directed controls. It prevents memory drift, improving AI transparency and reliability.

**Powered by Llama 4 Maverick** - MARM runs on Meta's flagship 400B parameter multimodal model via Replicate, providing industry-leading intelligence at 96% lower cost than premium alternatives.

### Why Manual Steps Matter

Manual logging, knowledge entry, and accuracy checks prevent silent drift. User visibility ensures context and accuracy remain aligned.

**User Controls:**

- **Memory:** `/log session:`, `/log entry:`.
- **Knowledge:** `/notebook` commands.
- **Accuracy:** `/deep dive`, `/show reasoning`.

This approach ensures the AI works with **user-led intent**, reducing drift across sessions and platforms.

## Live Chatbot Demo

### Try MARM Online

Experience MARM instantly at [marm-systems-chatbot.onrender.com](https://marm-systems-chatbot.onrender.com):

- **No setup required** - Start using MARM immediately
- **Llama 4 Maverick backend** - 400B parameter multimodal AI
- **Full protocol support** - All commands work exactly as documented
- **Modern interface** - Command menu (⚡), voice synthesis, file uploads
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

### Session Management

- **`/start marm`**: Activates memory & accuracy layers. Must be first command.
- **`/refresh marm`**: Recenters AI mid-session if drift occurs. Use after 8-10 turns or topic pivots.

### Logging

- **`/log session: [name]`**: Labels session ("folders"). Think of it as project naming.
- **`/log entry: [YYYY-MM-DD-topic-summary]`**: Logs structured milestones. Schema is enforced.

### Accuracy & Reasoning

- **`/deep dive`**: Forces accuracy-driven responses with self-checks.
- **`/show reasoning`**: Displays AI's reasoning trail for validation.

### Summarizing & Reseeding

- **`/summary: [SessionName]`**: Provides condensed one-line-per-entry log summary and a paste-ready reseed block.
- **Schema Enforcement**: Invalid logs trigger correction prompts.

### Manual Knowledge Library (`/notebook`)

- **`/notebook add: [name] [data]`**: Add trusted user-defined info.
- **`/notebook use: [name]`**: Activate an entry (multiple via comma: `name1,name2`).
- **`/notebook show:`** Lists all stored keys.
- **`/notebook clear:`** Clears the active list (does not delete stored entries).
- **`/notebook status:`** Shows the current active list.

**Critical Notebook Behaviors:**

- Entries are **session-bound** - they don't persist across chats
- Must be manually reseeded each new session
- Token limits apply - keep entries concise
- Ideal for: project guidelines, tone rules, technical specs, workflow definitions

## Part IV: Beyond the Basics

### Real-World Use Cases

#### Multi-Session Projects

Track complex projects across days/weeks:
Day 1:
/log session: AppRedesign
/log entry: [2025-07-14 | Defined MVP features | 5 core features identified]
/notebook add: mvp_features Login, Dashboard, Settings, API, Reports
/summary: AppRedesign
Day 2 (new chat):
/start marm
/log session: AppRedesign
[paste Day 1 reseed block]
/notebook add: mvp_features Login, Dashboard, Settings, API, Reports
/log entry: [2025-07-15 | Started login flow | OAuth2 selected]

#### Enhanced Accuracy Mode

For critical accuracy (legal docs, technical specs):

```text
/deep dive Draft a privacy policy section on data retention
/show reasoning
```

Review reasoning trail before accepting output. Llama 4 Maverick's 400B parameters provide exceptional reasoning capabilities for complex analysis.

#### Complex Topic Management

Handle multi-threaded conversations:
/log session: ClientProject
/log entry: [2025-07-14 | Discussed frontend requirements | React chosen]
/notebook add: tech_stack React, Node.js, PostgreSQL
[20 messages later, topic shifts]
/log entry: [2025-07-14 | Switched to budget planning | Need cost estimates]
/refresh marm
/summary: ClientProject

### Session Drift Management

<details>
  
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

</details>

### Manual Knowledge Library Deep Dive

<details>
  
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

</details>

### Platform Compatibility Strategies

<details>

#### ChatGPT (Memory-Enabled)

- Native memory often **drifts** or **conflates sessions**
- MARM overrides with explicit structure
- Use `/summary:` even with memory on
- `/refresh marm` counters GPT's assumption tendencies

#### Claude (Stateless)

- **Zero memory** between sessions
- Requires disciplined reseed workflow
- Benefits most from `/notebook` entries
- Use verbose session names for clarity

#### Replicate/Local Models

- **Replicate (default)**: Llama 4 Maverick via API - stateless but cost-effective
- **Local models**: Treat as fully stateless
- Implement reseed blocks in system prompts
- Can automate compile/reseed via middleware
- Token limits vary - adjust notebook usage
- **Replicate advantage**: Access to 1000+ models with same MARM protocol

#### Platform-Specific Tips

**ChatGPT**: /refresh marm every 5-7 turns (fights assumption drift)
**Claude**: Full reseed required, use detailed session labels  
**Replicate (MARM default)**: Stateless but reliable, 3-4 sec responses, cost-effective
**Local models**: Keep notebook entries minimal (smaller context)
**API integration**: Can inject MARM protocol into system message

</details>

### Power-User Templates & Customization

<details>
  
#### Project Management Template

/start marm
/log session: Sprint24
/notebook add: sprint_goal Implement user authentication
/notebook add: team Frontend:2, Backend:3, QA:1
/log entry: [Date | Sprint planning complete | 21 story points]

#### Daily Standup Logger

/log session: DailyStandups
/log entry: [2025-07-14 | Yesterday: API design | Today: Implementation]
/summary: DailyStandups

#### Code Review Workflow

/log session: PR-4521-Review
/notebook add: pr_link <https://github.com/org/repo/pull/4521>
/log entry: [2025-07-14 | Initial review | 3 blockers found]
/notebook add: blockers SQL injection risk, Missing tests, No error handling

#### Multi-LLM Integration Pattern

Use MARM logs as context bridges:
GPT-4 Session:
/summary: ProjectX > export.txt
Claude Session:
/start marm
[paste export.txt]
Continue seamlessly...

#### Automation Hooks (n8n/Zapier)

Trigger: /summary command
Action: Auto-save to Notion/Google Docs
Result: Persistent external memory

</details>

### Advanced Session Patterns

<details>
  
#### Session Chaining

Link related sessions:
/log session:Research-Phase1
[work]
/summary: Research-Phase1
New session:
/log session:Research-Phase2
/log entry: [2025-07-15 | Continued from Phase1 | See previous summary]

#### Parallel Sessions

Track multiple threads:
Tab 1: /log session:ClientA-Frontend
Tab 2: /log session:ClientA-Backend
Tab 3: /log session:ClientA-Integration
Merge later:
/summary: ClientA-Frontend
/summary: ClientA-Backend
[manually merge relevant entries]

</details>

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

## Troubleshooting Guide

#$# Common Issues & Solutions

- Run `/refresh marm`
- Check last summary with `/summary: [session]`
- Verify notebook keys with `/notebook show:`

### "Responses are too generic"

- Use `/deep dive` for next response
- Add specific context to notebook
- Log recent decision with `/log entry:`

- `/summary: [session]`
- Start fresh with `/log session:[Name]-Part2`
- Reseed only essential notebook keys

### "Platform memory conflicting with MARM"

- Explicitly use `/refresh marm`
- Ignore platform suggestions
- Trust MARM structure over native memory


