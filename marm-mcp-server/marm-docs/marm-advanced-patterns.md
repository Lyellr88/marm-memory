# MARM Protocol - Advanced Patterns & Quick Reference

## Beyond the Basics, Power-User Templates, and Troubleshooting

**MARM v2.2.6** - Universal Protocol for AI Memory Intelligence

---

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

## Session Drift Management

### When to Refresh/Reseed

- Every **8-10 conversation turns**
- After **any major topic pivot**
- When AI responses feel **generic or unfocused**
- Before **critical decisions or outputs**

### Drift Recovery Process

Detect drift (generic responses, lost context)
`/refresh marm`
`/summary: [Session]`
Review last 3-5 entries
`/deep dive` for next response

### Preventive Maintenance

Every 10 turns:
`/summary: SessionName`
`/refresh marm`
`/notebook show:`  [verify key data intact]

---

## Manual Knowledge Library Deep Dive

### Token Management Strategy

**Bad (token heavy):**

```txt
/notebook add: project_details This is a comprehensive project involving multiple stakeholders including...
```

**Good (token efficient):**

```txt
/notebook add: project_type B2B SaaS platform
/notebook add: stakeholders PM:John, Dev:Sarah, Design:Mike
/notebook add: deadline 2025-08-30
```

### Multi-Key Strategies

Organize related info:

```txt
/notebook add: api_base <https://api.example.com/v2>
/notebook add: api_auth Bearer token in header
/notebook add: api_ratelimit 100 req/min
```

### Session-Bound Behavior

Notebook entries **vanish** on new chat. Always reseed critical keys:
Essential reseed template:

```txt
/start marm
/log session:[Name]
[paste summary block]
/notebook add: tone [saved tone preference]
/notebook add: context [saved project context]
```

---

## Platform Compatibility

| Platform | Memory Type | Key Challenges | MARM Strategy | Refresh Frequency |
|----------|-------------|----------------|---------------|-------------------|
| **ChatGPT** | Native memory (drifts) | Conflates sessions, assumptions | Use `/summary:` + `/refresh marm` | Every 5-7 turns |
| **Claude** | Stateless | Zero memory between sessions | Full reseed required, verbose labels | New session start |
| **Replicate** | Stateless | API-based, token limits | Reliable, cost-effective | As needed |
| **Local Models** | Stateless | Variable token limits | Minimal notebook entries | Context dependent |

---

## Power-User Templates

| Template | Setup Commands | Key Benefits |
|----------|----------------|---------------|
| **Project Management** | `/log session: Sprint24` → `/notebook add: sprint_goal` | Track sprint progress, team info |
| **Daily Standups** | `/log session: DailyStandups` → `/log entry:` pattern | Quick daily progress logging |
| **Code Review** | `/log session: PR-[number]` → `/notebook add: blockers` | Systematic review tracking |

### Advanced Integration

| Pattern | Process | Benefit |
|---------|---------|----------|
| **Multi-LLM Bridge** | Export `/summary:` → Import to new AI | Cross-platform continuity |
| **External Memory** | Hook `/summary` → Notion/Docs | Persistent storage automation |

---

## Advanced Session Patterns

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
