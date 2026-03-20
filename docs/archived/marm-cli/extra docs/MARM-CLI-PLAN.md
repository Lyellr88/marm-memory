# MARM CLI - Planning & Development Document

**Purpose:** Development roadmap and reference for MARM CLI v1.0.0 implementation
**Status:** Phases 1-3b COMPLETE | Phase 4 PENDING | Phases 5-6 PLANNED

---

## 📋 Table of Contents

- [Development Phases](#development-phases) ⭐ **START HERE**
- [Vision & Strategy](#vision--strategy)
- [Commands Reference (Planned)](#commands-reference)
- [Architecture (Implemented)](#architecture)
- [NLP Tool Invocation (Implemented)](#nlp-tool-invocation-critical-requirement)
- [Security](#security-offline-cli---minimal-needed)
- [UX & Polish](#what-makes-a-cli-feel-smooth--professional)
- [Technical Implementation](#technical-implementation-checklist)
- [Open Questions](#open-questions)

---

## 📊 Development Phases

### ✅ Phase 1: Project Structure and Dependencies (COMPLETE)
**Completed:** 2025-01-27 | **Lines:** ~500

- Created project structure with `src/` layout
- Installed core dependencies (Rich, Prompt Toolkit, Click, sentence-transformers, httpx, pydantic)
- Configured settings.json loading
- Database directory auto-creation

### ✅ Phase 2a: Tool Infrastructure (COMPLETE)
**Completed:** 2025-01-27 | **Lines:** ~800

- Built BaseDeclarativeTool pattern (Params, Invocation, Tool)
- Created ToolRegistry singleton
- Implemented ToolError handling system
- Added automatic JSON schema generation
- Followed qwen-code three-component architecture

### ✅ Phase 2b: Ollama Integration + MARM Protocol (COMPLETE)
**Completed:** 2025-01-27 | **Lines:** ~1,200

- **OllamaClient** - Full async client with tool execution loop (5 rounds max)
- **ProtocolInjector** - Loads MARM v2.2.5 protocol from PROTOCOL.md (exact copy, 16,614 chars)
- **MARMDatabase** - SQLite with WAL mode, 5 tables, connection pooling
- **SemanticSearch** - Sentence transformers (all-MiniLM-L6-v2) with 384-dim embeddings
- **Chat Loop** - Rich terminal + Prompt Toolkit with history

**Key Fix:** Added UTF-8 encoding for Windows compatibility

### ✅ Phase 3a: 14 Manual MARM Tools (COMPLETE)
**Completed:** 2025-01-28 | **Lines:** ~1,400

Implemented all 14 manual MARM tools:
- 🧠 Memory: `marm_smart_recall`
- 📚 Logging: `marm_log_session`, `marm_log_entry`, `marm_log_show`, `marm_log_delete`
- 🔄 Reasoning: `marm_summary`
- 📔 Notebook: `marm_notebook_add`, `marm_notebook_use`, `marm_notebook_show`, `marm_notebook_delete`, `marm_notebook_clear`, `marm_notebook_status`
- 🚀 Session: `marm_start`
- ⚙️ System: `marm_system_info`

**Critical Refactor:** Singleton pattern for database/semantic search (prevents repeated model loading)

### ✅ Phase 3b: 3 Automated MARM Tools (COMPLETE)
**Completed:** 2025-01-28 | **Lines:** ~600

Background automation systems:
1. **ContextualLogger** - 8 regex patterns for auto-logging accomplishments/setups/decisions
2. **SmartRefreshTimer** - Protocol refresh every 30 mins / 50 messages / 10 min idle
3. **ContextBridgeDetector** - 4 implicit signals + 3 explicit phrases for context shifts

**Critical Fixes:**
- Session name alignment (automation now logs to correct session_id)
- Full conversation context storage (not just key phrases)
- File context tracking implementation

### 🔄 Phase 4: Polish CLI Interface and UX (PENDING)

**Goal:** Make it feel like qwen-code/Claude CLI - comfort features that drive retention and feedback

**What's Already Working:**
- ✅ Markdown rendering (Rich)
- ✅ Command history (Prompt Toolkit FileHistory)
- ✅ Syntax highlighting
- ✅ Multi-line input support
- ✅ Most keyboard shortcuts (Prompt Toolkit defaults)

**What Needs Implementation:**

**4.1 Core UX Polish:**
1. **Custom Keyboard Shortcuts** (5 keybindings):
   - Ctrl+L - Clear screen
   - Alt+Enter / Ctrl+Shift+J - Insert newline
   - Ctrl+Shift+Tab - Toggle thinking mode (keyword-based: "think", "think hard", "think harder")
   - Escape Escape - Clear input

2. **Enhanced Help Command** - 6 Rich tables with categories
3. **Better Error Formatting** - Rich Panels for errors
4. **/clear Command** - Clear screen without losing context

**4.2 Comfort Features (Critical for Launch):**

5. **Streaming Responses** - Real-time token display as AI generates
   - Shows tokens as they arrive (feels instant vs waiting for full response)
   - "Thinking..." spinner before first token
   - Smooth character-by-character or word-by-word display
   - Makes it feel alive like Claude/Qwen CLIs

6. **Task Tracking (`/todos`)** - In-session todo management
   - `/todos add <task>` - Add new task
   - `/todos list` - Show all tasks with status
   - `/todos done <id>` - Mark task complete
   - `/todos clear` - Clear completed tasks
   - Persists within session, shows in `/status`
   - Helps users track multi-step work during conversation

**Why These Are Critical:**
- **Streaming** - Makes 5-10 second responses feel instant, reduces perceived wait time
- **Todos** - Users stay organized during complex builds, increases session value
- Both features = "this feels as good as Claude/Qwen" = retention + feedback

**Reference:** See `PHASE-4-UI-PLAN.md` for full implementation details

**Estimated Lines:** ~400-500 (includes streaming + todos)

### ⏳ Phase 5: File/System Tools + Security (PLANNED)

**Commands to Implement:**
- `/read <file>` - Load file into context
- `/write <file>` - Create new file
- `/edit <file>` - Modify existing file
- `/run <cmd>` - Execute shell command (with safety checks)
- `/search <pattern>` - Search file contents (grep)
- `/find <glob>` - Find files by pattern

**Security & Safety Implementation:**
- **File Overwrite Protection:** Confirm before overwriting existing files
- **Dangerous Command Detection:** Warn on `rm -rf`, `del /f`, `format`, `mkfs`, `dd if=/dev/zero`
- **System Directory Blocking:** Prevent writes to `C:\Windows\`, `/etc/`, `/usr/bin/`, `/System/`
- **Path Traversal Prevention:** Block access to `../../../` patterns to system files
- **Safe Defaults:** Configuration for `confirm_overwrite`, `warn_dangerous_commands`, `block_system_dirs`

**Why Security in Phase 5:**
Offline CLI doesn't need network security, but needs to protect users from accidentally breaking their own system. All dangerous operations happen through file/system tools, so security checks are implemented alongside them.

**Estimated Lines:** ~400-600

### ⏳ Phase 6: Terminal Commands + Agents (PLANNED)

**Global Commands to Implement:**
- `marm chat` - Start new conversation (already works)
- `marm --continue` - Resume last session
- `marm list` - Show all conversations
- `marm resume <id>` - Load specific conversation
- `marm config` - View/edit configuration
- `marm config set <key> <value>` - Update config
- `marm upgrade` - Check for updates (optional, requires internet)

**In-Chat Commands:**
- `/model` - Switch AI model (CodeLlama 32B/13B, DeepSeek Coder 14B, custom endpoint)
- `/agents` - Switch agent persona (Code Helper, Code Reviewer, Debugger, Documentation Writer, Custom)
- `/status` - System status (model, memory, uptime, current agent)
- `/export` - Export conversation (markdown/JSON/text)
- `/continue` - Resume last session
- `/resume <id>` - Resume specific session

**Agent System Implementation:**
- **Code Helper** [default] - General coding assistance, explanations, implementation
- **Code Reviewer** - Critical analysis, best practices, security checks, performance review
- **Debugger** - Root cause analysis, step-by-step debugging, error investigation
- **Documentation Writer** - Docstrings, comments, README generation, API docs
- **Custom Agent** - User-defined persona with custom system prompt

**Implementation Notes:**
- Agents modify system prompt injection (prepend persona to MARM protocol)
- Agent state persists within session
- `/status` shows current active agent
- Agent personas stored in `config/agents.json` for customization

**Estimated Lines:** ~400-600

### 📝 Missed Features / Future Enhancements

**Deferred to v1.1+:**
- Clipboard integration (`/read clipboard`, copy last response)
- File watching (monitor files for changes)
- Tab completion for commands
- Status bar with session info
- Token counter display
- Custom themes/color schemes

**Deferred to v2.0+:**
- VS Code extension
- Git integration (`/git status`, `/git commit`)
- Web UI
- Extension system / plugin architecture

---

---

═══════════════════════════════════════════════════════════════════════════════
## Vision & Strategy
═══════════════════════════════════════════════════════════════════════════════

Professional offline CLI wrapper that feels like Claude CLI - 100% local with persistent memory.

**UX Goal:** Should look and feel like big-name company CLIs (smooth, fast, polished)

**Core Principles:** Offline-first, Auto-save everything, MARM memory integration, Simple UX

**Release Strategy:**
- **v1.0.0 Beta** - Full featured release (not MVP)
- **Free base version** - Core functionality available to everyone
- **Pro version** - $20 lifetime purchase (features TBD based on user feedback, no subscription)

---

═══════════════════════════════════════════════════════════════════════════════
## Installation
═══════════════════════════════════════════════════════════════════════════════

**Package Size:** ~9GB (CLI 50MB + Ollama 500MB + qwen3-coder:14b 8.4GB)

**Install Path:** `C:\Program Files\MARM-CLI\`

**First Run:**
```bash
$ marm chat
Welcome to MARM CLI v1.0
Loading qwen3-coder:14b... ✓
>
```

---

═══════════════════════════════════════════════════════════════════════════════
## Commands Reference
═══════════════════════════════════════════════════════════════════════════════

### In-Chat Commands

| Command | Description | Sub-commands |
|---------|-------------|--------------|
| `/model` | Switch AI model or endpoint | `1` qwen:7b (4.3GB)<br>`2` qwen:14b (8.9GB) [default]<br>`3` qwen:30b (17GB)<br>`4` Custom endpoint |
| `/memory` `.md` | Persistent memory management | `search <query>` - Search conversations<br>`save <note>` - Save important note<br>`list` - Recent memories<br>`stats` - Usage stats<br>`clear` - Clear all (confirm) |
| `/agents` | Switch agent persona | `1` Code Helper [default]<br>`2` Code Reviewer<br>`3` Debugger<br>`4` Documentation Writer<br>`5` Custom... |
| `/read <file>` | Read file into context | Load file contents for discussion |
| `/write <file>` | Create new file | Write AI response or manual input |
| `/edit <file>` | Modify existing file | Describe changes or provide content |
| `/run <cmd>` | Execute shell command | Run any terminal command |
| `/search <pattern>` | Search file contents (grep) | Find text in files |
| `/find <glob>` | Find files by pattern | Match files like `*.py` |
| `/export` | Export conversation | `1` Markdown<br>`2` JSON<br>`3` Plain text |
| `/continue` | Resume last session | Load previous conversation |
| `/resume <id>` | Resume specific session | Pick from conversation list |
| `/status` | System status | Model, memory, GPU, uptime |
| `/todos` | Todo management | `add <task>` - New todo<br>`done <id>` - Mark complete<br>`list` - Show all<br>`clear` - Clear done |
| `/init` | Initialize memory DB | One-time setup for memory |
| `/clear` | Clear screen | Preserve context, clean view |
| `/compact` | Summarize conversation | Show condensed history |
| `/help` | Show all commands | Full command reference |
| `/exit` | Exit CLI | Auto-save before exit |

### Global Terminal Commands

| Command | Description |
|---------|-------------|
| `marm chat` | Start new conversation |
| `marm --continue` | Resume last session |
| `marm list` | Show all conversations |
| `marm resume <id>` | Load specific conversation |
| `marm config` | View/edit configuration |
| `marm config set <key> <value>` | Update config |
| `marm upgrade` | Check for updates (requires internet) |

### Advanced Features (Optional/Future)

| Feature | Status | Notes |
|---------|--------|-------|
| `/mcp` | v1.0 | MCP server control (start/stop/status) |
| `/style` | v1.1 | Output formatting (markdown/plain/code/minimal) |
| `/permissions` | v1.1 | File access controls (read/write/run) |
| `/upgrade` | Optional | Requires internet - skip if offline-only |
| VS Code Extension | v2.0+ | Skip for v1.0 - focus on CLI perfection |
| Streaming responses | v1.1 | Real-time token streaming |
| Git integration | v2.0 | `/git status`, `/git commit` |

---

═══════════════════════════════════════════════════════════════════════════════
## Architecture (Implemented)
═══════════════════════════════════════════════════════════════════════════════

### ✅ Implemented Components

**Database (SQLite + WAL Mode):**
- 5 tables: conversations, log_entries, notebook, active_instructions, sessions
- Connection pooling, singleton pattern
- Session validation with regex (prevents SQL injection)

**Semantic Search:**
- Sentence transformers (all-MiniLM-L6-v2)
- 384-dimension embeddings
- Lazy loading (loaded once at startup)

**MARM Protocol:**
- Loaded from `docs/PROTOCOL.md` (exact copy, 16,614 chars)
- Injected into every LLM request
- Auto-refreshes every 30 min / 50 messages / 10 min idle

**Ollama Integration:**
- Async client with tool execution loop (up to 5 rounds)
- Automatic function calling (LLM decides which tools to invoke)
- Error handling with graceful degradation

**File Structure (Actual):**
```
marm-cli/
├── src/
│   ├── main.py              # Entry point (Click CLI)
│   ├── chat.py              # Chat loop with Rich/Prompt Toolkit
│   ├── config/
│   │   └── settings.py      # Config loading
│   └── marm/
│       ├── database.py      # SQLite with WAL mode
│       ├── semantic.py      # Semantic search wrapper
│       ├── protocol.py      # Protocol loading
│       ├── ollama_client.py # Async Ollama integration
│       ├── tools.py         # Base tool classes
│       ├── tool_registry.py # Singleton registry
│       ├── tool_context.py  # Shared instances
│       ├── tool_error.py    # Error handling
│       ├── tool_schema.py   # JSON schema generation
│       ├── marm_tools.py    # 14 manual tools
│       └── automation.py    # 3 automated systems
├── config/
│   └── settings.json        # User configuration
├── data/
│   ├── conversations.db     # SQLite database
│   └── history.txt          # Command history
└── docs/
    └── PROTOCOL.md          # MARM protocol source
```

### ✅ Memory Architecture (Fully Operational)

**Two-Layer System:**

**Layer 1: Session Memory** - Context window management with protocol refresh
**Layer 2: MARM Persistent Memory** - Cross-chat semantic search with auto-detection

**17 MARM Tools Implemented:**
- 14 manual tools (LLM-invoked via NLP)
- 3 automated tools (background, no LLM invocation)

**Auto-Detection Patterns:**
- 8 regex patterns for accomplishments/setups/decisions/solutions
- 4 implicit context shift signals (embedding similarity, file changes, domain shifts, intent shifts)
- 3 explicit context shift phrases

**Why This Matters:**
- ✅ Works exactly as designed - NLP-based tool invocation operational
- ✅ Auto-logs important moments without user intervention
- ✅ Semantic search across all conversations
- ✅ Context bridges prevent memory loss during topic shifts

---

═══════════════════════════════════════════════════════════════════════════════
## NLP Tool Invocation (Implemented)
═══════════════════════════════════════════════════════════════════════════════

### ✅ How It Works (Phase 2b/3a Complete)

**Ollama Function Calling:**
- LLM receives JSON schemas for all 17 MARM tools
- LLM decides which tools to call based on natural language
- OllamaClient executes tools automatically (up to 5 rounds)
- Results integrated seamlessly into responses

**User Experience:**
```bash
User: "Remember when we set up Docker?"
→ AI detects intent, calls marm_smart_recall("docker setup")
→ Returns: "Yes, we set up Docker with GPU on January 15th..."

User: "Save this for later: npm start"
→ AI detects intent, calls marm_notebook_add()
→ Confirms: "Saved! You can recall this anytime..."
```

**Implementation Details:**
- Tool schemas generated via Pydantic models (`tool_schema.py`)
- Ollama's function calling handles intent detection
- No manual `/marm` commands needed
- Background automation runs silently (no LLM invocation)

**Validation:**
✅ All 17 tools registered with schemas
✅ Natural language triggers work
✅ Tool execution loop functional
✅ Results integrated into responses
✅ User never sees raw tool names

---

═══════════════════════════════════════════════════════════════════════════════
## Security (Offline CLI - Minimal Needed)
═══════════════════════════════════════════════════════════════════════════════

### What We DON'T Need
- ❌ API keys/authentication (no remote APIs)
- ❌ Network security (offline)
- ❌ Rate limiting (local only)
- ❌ CORS, XSS, CSRF (no web interface)

### What We DO Need (User Protection)

**1. File Operations**
```bash
> /write existing-file.py
⚠️  File exists. Overwrite? [y/n]:

> /run rm -rf /
⚠️  DANGER: This will delete your entire system. Continue? [y/n]:
```

**2. Dangerous Commands**
- Detect: `rm -rf`, `del /f`, `format`, `mkfs`, `dd if=/dev/zero`
- Action: Confirm before executing

**3. Path Traversal Protection**
```bash
> /read ../../../etc/passwd
⚠️  Accessing system files. Continue? [y/n]:
```

**4. System Directory Writes**
- Block: `C:\Windows\`, `/etc/`, `/usr/bin/`, `/System/`
- Action: Prompt + confirmation

**5. Safe Defaults**
```json
{
  "permissions": {
    "confirm_overwrite": true,
    "warn_dangerous_commands": true,
    "block_system_dirs": true,
    "allow_path_traversal": false
  }
}
```

**Bottom Line:** Protect user from breaking their own system, not external threats.

---

═══════════════════════════════════════════════════════════════════════════════
## What Makes a CLI Feel Smooth & Professional
═══════════════════════════════════════════════════════════════════════════════

### 1. Terminal UI/UX
**Colors & Formatting:**
- Syntax highlighting for code blocks
- Colored output (errors=red, success=green, warnings=yellow)
- Bold/italic text for emphasis
- Proper text wrapping (don't break mid-word)

**Visual Feedback:**
```bash
> /model 1
Downloading qwen3-coder:7b... ████████░░ 78% (3.2GB/4.3GB)

✓ Model downloaded successfully
Switching to qwen3-coder:7b... ✓
```

**Loading Indicators:**
- Spinners for quick operations
- Progress bars for downloads/large operations
- Time estimates when possible

### 2. Performance
**Fast Startup:**
- CLI loads in < 1 second
- Model lazy-loads (don't wait 10s to start chatting)

**Streaming Responses:**
```bash
> Write a Python function

def calculate_sum(numbers):
    """Calculate the sum of a list of numbers."""
    return sum(numbers)
█
```
(Response appears word-by-word, not all at once)

**Smart Caching:**
- Cache model in memory after first use
- Don't reload config file every command
- Reuse Ollama connection

### 3. User Input Experience
**Command History:**
- Arrow Up/Down to scroll through previous commands
- Search history with Ctrl+R
- Persistent across sessions

**Tab Completion:**
```bash
> /mo[TAB]
> /model

> /read src/ma[TAB]
> /read src/main.py
```

**Multi-line Input:**
```bash
> Write a function that:
... 1. Takes a list
... 2. Filters even numbers
... 3. Returns sorted result
[Enter twice to submit]
```

**Keyboard Shortcuts:**
- `Ctrl+C` - Cancel current operation
- `Ctrl+D` - Exit CLI
- `Ctrl+L` - Clear screen
- `Ctrl+U` - Clear current line

### 4. Error Handling
**Clear Error Messages:**
```bash
❌ Bad:
Error: 404

✅ Good:
Error: Model 'qwen3-coder:7b' not found
→ Available models: qwen3-coder:14b, qwen3-coder:30b
→ Download with: /model 1
```

**Graceful Degradation:**
- If GPU fails, fall back to CPU
- If model not found, suggest download
- If file doesn't exist, ask to create

**Recovery Mechanisms:**
```bash
> /run dangerous-command
[CLI crashes]

$ marm --continue
⚠️  Previous session crashed. Recover? [y/n]: y
✓ Restored conversation from 30 seconds ago
```

### 5. Configuration & Flexibility
**Settings File (settings.json):**
```json
{
  "theme": "dark",
  "streaming": true,
  "auto_save": true,
  "show_token_count": false,
  "confirm_dangerous_commands": true
}
```

**Environment Variables:**
```bash
export MARM_MODEL="qwen3-coder:30b"
export MARM_ENDPOINT="http://localhost:11434/v1"
```

**Command-line Flags:**
```bash
marm chat --model qwen3-coder:7b --no-streaming
```

### 6. State Management
**Session Awareness:**
```bash
$ marm chat
> Help me debug this function
[discusses code]
> /exit

$ marm --continue
> What was that function we were debugging?
[AI remembers context from last session]
```

**Smart Defaults:**
- Remember last model used
- Remember working directory
- Remember preferences (streaming on/off)

### 7. Installation & Updates
**One-Command Install:**
```bash
# Windows
winget install marm-cli

# Mac
brew install marm-cli

# Linux
curl -sSL https://get.marm.ai | bash
```

**Version Management:**
```bash
$ marm --version
MARM CLI v1.2.0

$ marm upgrade
New version available: v1.3.0
Changelog:
  - Added streaming responses
  - Fixed GPU detection bug
Upgrade now? [y/n]:
```


### 8. Developer-Friendly Features
**Exit Codes:**
```bash
$ marm chat --model fake-model
Error: Model not found
$ echo $?
1  # Non-zero = error
```

**Piping & Redirects:**
```bash
# Pipe file to MARM
cat code.py | marm chat "Review this code"

# Save conversation
marm chat > conversation.txt

# Chain commands
marm chat "Generate test.py" && python test.py
```

**JSON Output (for scripting):**
```bash
$ marm chat --json "What is 2+2?"
{"response": "4", "model": "qwen3-coder:14b", "tokens": 120}
```

### 9. Help & Documentation
**Built-in Help:**
```bash
$ marm --help
$ marm chat --help
$ man marm  # Unix man pages
```

**Examples in Help:**
```bash
$ marm --help

Examples:
  marm chat                    Start new conversation
  marm --continue              Resume last session
  marm chat --model qwen:7b    Use specific model
```

**Interactive Tutorial (first run):**
```bash
$ marm chat
Welcome to MARM CLI! 👋
Would you like a quick tutorial? [y/n]: y

Tutorial (1/4): Basic Chat
Type anything to chat with the AI. Try it now:
>
```

### 10. Quality of Life Features
**Smart Context Awareness:**
```bash
# Detects you're in a git repo
$ marm chat
> /status
MARM CLI v1.0
Model: qwen3-coder:14b
Git repo: marm-cli (branch: main)
Working dir: /Users/you/marm-cli
```

**Clipboard Integration:**
```bash
> /read clipboard
[reads from clipboard]

> Copy the last response
✓ Copied to clipboard
```

**File Watching:**
```bash
> Watch src/main.py and tell me if there are issues
✓ Watching src/main.py for changes...
[You edit the file]
⚠️  Detected potential bug on line 42: undefined variable
```

---

═══════════════════════════════════════════════════════════════════════════════
## Technical Implementation Checklist
═══════════════════════════════════════════════════════════════════════════════

### Terminal Library (Python)
- **Rich** - Colors, formatting, progress bars, tables
- **Prompt Toolkit** - Advanced input (history, autocomplete, multi-line)
- **Click** or **Typer** - CLI framework (commands, flags, help)

### Performance
- Lazy loading (don't load everything at startup)
- Async operations (don't block on I/O)
- Connection pooling (reuse Ollama connection)

### Storage
- SQLite for conversations/memory
- JSON for config (easy to edit)
- Flat files for exports

### Must-Have Libraries
```python
rich              # Terminal UI
prompt-toolkit    # Advanced input
click/typer       # CLI framework
requests          # API calls
sqlite3           # Built-in (database)
psutil            # System monitoring
watchdog          # File watching (future)
sentence-transformers  # Semantic search embeddings
```

---

═══════════════════════════════════════════════════════════════════════════════
## Open Questions
═══════════════════════════════════════════════════════════════════════════════

1. **Extension system** - Include in v1.0.0? ⚠️ Decide (marked as maybe)
2. **Upgrade check** - Include despite internet requirement? ⚠️ Decide
3. **Streaming responses** - v1.0.0 or later? ⚠️ Decide (deferred to v1.1+)
4. **MCP auto-start** - Always on or manual? ⚠️ Decide

---

═══════════════════════════════════════════════════════════════════════════════
## Next Steps (Original Phases)
═══════════════════════════════════════════════════════════════════════════════

**Tonight:** Review & finalize feature list ✅

**Today:** Build v1.0.0
1. **Phase 1:** Project structure + dependencies
2. **Phase 2:** Study qwen-code NLP tool invocation (CRITICAL)
3. **Phase 3:** Implement 17 MARM tools with NLP triggers
4. **Phase 4:** Build chat loop with Rich/Prompt Toolkit
5. **Phase 5:** File operations (read/write/edit)
6. **Phase 6:** Search tools (search/find)
7. **Phase 7:** Multi-layer protocol injection system
8. **Phase 8:** Auto-save system + session management
9. **Phase 9:** Full integration testing

**Goal:** Working offline CLI with full v1.0.0 features + natural language tool invocation

**Reference materials ready:**
- `C:\Users\lyell\Desktop\MARM-Systems\marm-cli\extra docs\MARM-INTEGRATION-PLAN.md`
- `C:\Users\lyell\Desktop\MARM-Systems\marm-cli\extra docs\QWEN-CODE-ANALYSIS.md`
- `C:\Users\lyell\Desktop\MARM-Systems\marm-cli\extra docs\muli-layer-protocol-injection.md`
- `C:\Users\lyell\Desktop\MARM-Systems\marm-cli\extra docs\PHASE-4-UI-PLAN.md`
- `C:\Users\lyell\Desktop\MARM-Systems\marm-cli\extra docs\Qwen-Code-NLP-Based-Tool-Invocation.md`
- `C:\Users\lyell\Desktop\qwen-code-main`
