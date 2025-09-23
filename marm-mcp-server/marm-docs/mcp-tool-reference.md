# MARM MCP Server - Complete Tool Reference

## 19 Essential MCP Tools for AI Memory Intelligence

**MARM v2.2.5** - Universal MCP Server Tool Suite

---

## Complete Tool Reference (19 Tools)

| Category | Tool | Description | Usage Notes |
|----------|------|-------------|-------------|
| **🚀 Session** | `marm_start` | Activate MARM memory and accuracy layers | Call at beginning of important conversations |
| | `marm_refresh` | Refresh session state and reaffirm protocol adherence | Reset MARM behavior if responses become inconsistent |
| **🧠 Memory** | `marm_smart_recall` | Semantic similarity search across all memories | `query` (required), `limit` (default: 5), `session_name` (optional). Use natural language queries |
| | `marm_contextual_log` | Auto-classifying memory storage with embeddings | Store important information that should be remembered |
| **📚 Logging** | `marm_log_session` | Create or switch to named session container | Include LLM name, dates, be descriptive |
| | `marm_log_entry` | Add structured log entry with auto-date formatting | Format: `YYYY-MM-DD-topic-summary` |
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
| **⚙️ System** | `marm_current_context` | Get current date/time for accurate log entry timestamps | Prevent AI date confusion, ensure proper log chronology |
| | `marm_system_info` | Comprehensive system information, health status, and loaded docs | Server version, database statistics, documentation, capabilities |
| | `marm_reload_docs` | Reload documentation into memory system | Refresh MARM's knowledge after system updates |

---

## Session Management Tools

### `marm_start`

Activate MARM memory and accuracy layers for current session.

**Usage**: Call at beginning of important conversations
**Example**: "Starting work on new project - activate MARM memory"

### `marm_refresh`

Refresh session state and reaffirm protocol adherence.

**Usage**: Reset MARM behavior if responses become inconsistent
**When to use**: After long conversations or context switches

---

## Memory Intelligence Tools

### `marm_smart_recall`

Semantic similarity search across all memories.

**Parameters**:

- `query`: What to search for (required)
- `limit`: Number of results (default: 5)
- `session_name`: Specific session to search (optional)

**Example Usage**:

```txt
Query: "docker deployment issues"
Returns: Related memories about containerization, deployment errors, configuration problems
```

**Pro Tip**: Use natural language - "problems with authentication" works better than "auth error"

### `marm_contextual_log`

Auto-classifying memory storage with embeddings.

**Usage**: Store important information that should be remembered
**Auto-classification**: Code, project, book, or general content
**Best Practice**: Log key decisions, solutions, and insights

---

## Logging System Tools

### `marm_log_session`

Create or switch to named session container.

**Usage**: Include LLM name, dates, be descriptive
**Example**: `/log session: claude-code-review-2025-01`

### `marm_log_entry`

Add structured log entry with auto-date formatting.

**Format**: `YYYY-MM-DD-topic-summary`
**Example**: `/log entry: 2025-01-15-api-integration-completed`

### `marm_log_show`

Display all entries and sessions with filtering.

**Parameters**:

- `session_name`: Show specific session (optional)
- If no session specified, lists all sessions

### `marm_log_delete`

Delete specified session or individual entries.

**Usage**:

- Delete entire session: Provide session name
- Delete specific entry: Provide entry ID within session
**Warning**: Permanent deletion - use carefully

---

## Notebook Management Tools

### `marm_notebook_add`

Add new notebook entry with semantic embeddings.

**Usage**: Store reusable instructions, code snippets, procedures
**Example**: Development workflows, debugging checklists, configuration templates

### `marm_notebook_use`

Activate entries as instructions (comma-separated).

**Usage**: `marm_notebook_use("coding-standards,git-workflow")`
**Effect**: Selected entries become active context for AI responses

### `marm_notebook_show`

Display all saved keys and summaries.

**Output**: List of all notebook entries with creation dates and sizes

### `marm_notebook_delete`

Delete specific notebook entry.

**Usage**: Remove outdated or incorrect notebook entries
**Warning**: Permanent deletion - use carefully

### `marm_notebook_clear`

Clear the active instruction list.

**Usage**: Reset notebook context when switching between different types of work

### `marm_notebook_status`

Show current active instruction list.

**Usage**: See what notebook entries are currently influencing AI responses

---

## Workflow Tools

### `marm_summary`

Generate paste-ready context blocks with intelligent truncation.

**Usage**: Create summaries for new conversations or context bridging
**MCP Compliance**: Automatically truncates to fit 1MB MCP limits
**Best Practice**: Use before long sessions to compress history

### `marm_context_bridge`

Intelligent context bridging for workflow transitions.

**Usage**: Smoothly transition between different topics or projects
**Example**: Moving from debugging to feature development

---

## System Utilities

### `marm_current_context`

Get current date/time and system status.

**Usage**: Prevent AI date confusion, check system availability
**Output**: Current timestamp, system status, capabilities

### `marm_system_info`

Comprehensive system information, health status, and loaded docs.

**Output Includes**:

- Server version and health status
- Database statistics (memories, sessions, notebooks)
- Loaded documentation
- System capabilities (semantic search, scheduler)
- Docker health endpoint reference

### `marm_reload_docs`

Reload documentation into memory system.

**Usage**: Refresh MARM's knowledge of its own capabilities
**When to use**: After system updates or if documentation seems outdated
