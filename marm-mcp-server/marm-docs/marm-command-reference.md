# MARM Protocol - Complete Command Reference

## Detailed Usage Guide for All MARM Commands

**MARM v2.2.6** - Universal Protocol for AI Memory Intelligence

---

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

---

## Critical Notebook Behaviors

### Session-Bound Nature

- Entries are **session-bound** - they don't persist across chats
- Must be manually reseeded each new session
- Token limits apply - keep entries concise
- Ideal for: project guidelines, tone rules, technical specs, workflow definitions

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

---

## Session Management Commands

### `/start marm`

**Purpose**: Activates memory and accuracy layers
**When to use**: Must be first command in any MARM session
**Best Practice**: Always run at the beginning of important work

### `/refresh marm`

**Purpose**: Recenters AI mid-session to maintain focus
**When to use**: After 8-10 conversation turns or topic pivots
**Best Practice**: Use when responses feel generic or unfocused

---

## Logging Commands

### `/log session: [name]`

**Purpose**: Labels session for organization (think of it as creating folders)
**Format**: Descriptive names that identify the work context
**Examples**:

- `/log session: AppRedesign-Q3-2025`
- `/log session: ResearchPaper-AI-Memory`
- `/log session: CustomerSupport-Case1247`

### `/log entry: [YYYY-MM-DD-topic-summary]`

**Purpose**: Logs structured milestones with schema enforcement
**Format**: `[Date | Topic | Summary]`
**Examples**:

- `/log entry: [2025-07-14 | Set project scope | Phase 1 started]`
- `/log entry: [2025-07-14 | Completed wireframes | Ready for review]`
- `/log entry: [2025-07-14 | Pivoted to API design | Frontend work paused]`

**Schema Enforcement**: Corrects invalid formats automatically

---

## Accuracy Commands

### `/deep dive`

**Purpose**: Forces accuracy-driven responses with validation
**When to use**: For critical outputs, legal documents, technical specifications
**Features**:

- Enhanced validation and self-checks
- Reasoning transparency
- Error detection and correction

### `/show reasoning`

**Purpose**: Displays AI's reasoning trail for transparency
**When to use**: To verify logic paths and decision-making
**Benefits**:

- Transparency in AI thinking
- Verification of logical consistency
- Educational value for understanding AI processes

---

## Summary Commands

### `/summary: [SessionName]`

**Purpose**: Provides condensed log + reseed block
**Format**: One-line-per-entry format for easy copying
**Output Example**:

```txt
[2025-07-14 | Set project scope | Phase 1 started]
[2025-07-14 | Completed wireframes | Ready for review]
[2025-07-14 | Pivoted to API design | Frontend work paused]
```

**Use Cases**:

- Session end summary
- Context reseeding for new sessions
- Progress tracking and reporting

---

## Notebook Commands

### `/notebook add: [name] [data]`

**Purpose**: Add trusted user-defined information
**Best Practices**:

- Keep entries concise for token efficiency
- Use descriptive names
- Focus on reusable information

**Examples**:

```txt
/notebook add: project_tone Professional, technical documentation style
/notebook add: api_endpoint https://api.example.com/v1
/notebook add: coding_standards PEP8 with 88-char line limit
```

### `/notebook use: [name1,name2,...]`

**Purpose**: Activate notebook entries as active instructions
**Format**: Multiple entries separated by commas
**Examples**:

```txt
/notebook use: coding_standards,api_docs
/notebook use: project_tone,research_methodology
```

### `/notebook show:`

**Purpose**: Lists all stored keys and summaries
**Benefits**:

- Check token usage
- Review available entries
- Verify entry content

### `/notebook clear:`

**Purpose**: Clears the active instruction list
**Note**: Does not delete stored entries
**Use Case**: When switching to different work contexts

### `/notebook status:`

**Purpose**: Shows current active instruction list
**Benefits**:

- View what's currently activated
- Verify active instructions
- Troubleshoot unexpected behavior
