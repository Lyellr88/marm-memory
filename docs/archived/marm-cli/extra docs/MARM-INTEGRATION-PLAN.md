# MARM Integration Plan for CLI v1.0.0

## 📋 Table of Contents

- [Strategy: Direct Integration](#strategy-direct-integration-option-2)
- [MARM Tools (17 Total)](#marm-tools-18-total--17-after-removing-reload_docs)
  - [Manual Tools (14 tools)](#manual-tools-14-tools---userai-calls-explicitly)
  - [Automated Tools (3 tools)](#automated-tools-3-tools---run-in-background)
  - [Removed Tools](#removed-tools-1-tool)
- [Automation Strategy](#automation-strategy)
- [Protocol Effectiveness](#protocol-effectiveness-critical)
- [Loaded Documentation Access](#loaded-documentation-access)
- [CLI Tools](#cli-tools-10-visible--3-internal)
- [Architecture Integration](#architecture-integration)
- [File Structure](#file-structure)
- [Build Order](#build-order-today)
- [Decisions Made](#decisions-made-)
- [Ready to Build](#ready-to-build)

---

═══════════════════════════════════════════════════════════════════════════════
## Strategy: Direct Integration (Option 2)
═══════════════════════════════════════════════════════════════════════════════

MARM becomes a **built-in memory/accuracy layer**, not a separate MCP server.

**What we keep from MARM MCP:**
- ✅ All 18 tools (with modifications)
- ✅ SQLite database with semantic search
- ✅ Sentence transformers for embeddings
- ✅ MARM protocol effectiveness
- ✅ Auto-detection intelligence

**What we skip:**
- ❌ FastAPI server
- ❌ WebSocket layer
- ❌ MCP protocol overhead
- ❌ HTTP requests

---

═══════════════════════════════════════════════════════════════════════════════
## MARM Tools (18 Total → 17 after removing reload_docs)
═══════════════════════════════════════════════════════════════════════════════

### Manual Tools (14 tools - User/AI calls explicitly)

#### 🧠 Memory Intelligence (1 tool)
| Tool | Description |
|------|-------------|
| `marm_smart_recall` | Semantic search across all memories with `search_all=True` flag |

#### 📚 Logging System (4 tools)
| Tool | Description |
|------|-------------|
| `marm_log_session` | Create/switch named session container |
| `marm_log_entry` | Add structured log entry with auto-date |
| `marm_log_show` | Display all entries/sessions (filterable) |
| `marm_log_delete` | Delete specified session or entries |

#### 🔄 Reasoning & Workflow (1 tool)
| Tool | Description |
|------|-------------|
| `marm_summary` | Generate context-aware summaries with intelligent truncation |

#### 📔 Notebook Management (6 tools)
| Tool | Description |
|------|-------------|
| `marm_notebook_add` | Add new entry with semantic embeddings |
| `marm_notebook_use` | Activate entries as instructions (comma-separated) |
| `marm_notebook_show` | Display all saved keys and summaries |
| `marm_notebook_delete` | Delete specific notebook entry |
| `marm_notebook_clear` | Clear the active instruction list |
| `marm_notebook_status` | Show current active instruction list |

#### 🚀 Session Management (1 tool)
| Tool | Description |
|------|-------------|
| `marm_start` | Activate MARM memory & accuracy layers (auto-runs on startup) |

#### ⚙️ System Utilities (1 tool)
| Tool | Description |
|------|-------------|
| `marm_system_info` | Comprehensive system info, health status, loaded docs |

---

### Automated Tools (3 tools - Run in background)

| Tool | Trigger | Description |
|------|---------|-------------|
| `marm_contextual_log` | **Phrase detection** | Auto-logs important moments (accomplishments, setups, decisions, solutions) |
| `marm_refresh` | **Smart timer** | Auto-refreshes protocol every 30min / 50 messages / 10min idle |
| `marm_context_bridge` | **Context shift detection** | Auto-detects workflow transitions (explicit statements + implicit topic/domain/file/intent shifts) |

---

### Removed Tools (1 tool)

| Tool | Reason |
|------|--------|
| `marm_reload_docs` | Redundant with `marm_refresh` (which reloads protocol & docs) |
| `marm_current_context` | Replaced with system clock injection in system prompt |

---

═══════════════════════════════════════════════════════════════════════════════
## Automation Strategy
═══════════════════════════════════════════════════════════════════════════════

### 1. `marm_contextual_log` - Phrase Detection

**Goal:** Auto-log important moments without user manually calling tool

**Implementation:**
```python
# Phrase patterns to detect
AUTO_LOG_PATTERNS = [
    # Accomplishments
    r"(fixed|solved|completed|finished|done with) (.+)",
    r"(successfully|finally) (.+)",

    # Setups/configurations
    r"(set up|configured|installed) (.+)",
    r"(created|built|deployed) (.+)",

    # Decisions
    r"(decided to|going with|chose) (.+)",
    r"(will use|switching to) (.+)",

    # Problems/solutions
    r"(bug|issue|problem) (.+) (fixed|resolved)",
    r"(found that|discovered) (.+)",

    # Recall triggers
    r"(remember|recall|we discussed) (.+)",
]

def detect_auto_log(user_message: str, ai_response: str):
    """Detect if message should be auto-logged"""
    for pattern in AUTO_LOG_PATTERNS:
        if re.search(pattern, user_message, re.IGNORECASE):
            # Auto-log this conversation
            marm_contextual_log(
                entry=f"User: {user_message}\nAI: {ai_response}",
                auto_detected=True
            )
            break
```

**User sees:** Nothing (silent background operation)
**Database builds:** Personal context history automatically

### 2. `marm_refresh` - Smart Timer

**Goal:** Keep protocol fresh without manual refresh commands

**Implementation:**
```python
class SmartRefreshTimer:
    def __init__(self):
        self.session_start = time.time()
        self.last_refresh = time.time()
        self.message_count = 0

    def should_refresh(self) -> bool:
        """Determine if refresh needed"""
        elapsed = time.time() - self.last_refresh

        # Refresh triggers:
        # - Every 30 minutes of session time
        # - Every 50 messages
        # - If context getting stale (no activity for 10+ min)

        if elapsed > 1800:  # 30 minutes
            return True
        if self.message_count > 50:
            return True
        if elapsed > 600 and self.message_count > 10:  # 10 min idle
            return True

        return False

    def refresh(self):
        """Trigger background refresh"""
        marm_refresh()  # Reload protocol, clear stale state
        self.last_refresh = time.time()
        self.message_count = 0
```

**User sees:** Nothing (silent background operation)
**Effect:** Protocol stays fresh, AI maintains accuracy

### 3. `marm_current_context` - System Clock

**Goal:** Use system time/date instead of tool call

**Implementation:**
```python
from datetime import datetime
import platform

def get_current_context() -> dict:
    """Get current system context"""
    return {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "timezone": datetime.now().astimezone().tzname(),
        "platform": platform.system(),
        "user": os.getenv("USER", "unknown")
    }

# Inject into AI system prompt
system_prompt = f"""
Current Context:
- Date: {get_current_context()['date']}
- Time: {get_current_context()['time']}
- Platform: {get_current_context()['platform']}

[Rest of MARM protocol...]
"""
```

**User sees:** Nothing (automatic in system prompt)
**Effect:** AI always knows current date/time

### 4. `marm_context_bridge` - Smart Context Shift Detection

**Goal:** Detect workflow transitions even when user doesn't explicitly state they're switching tasks

**Explicit Detection (Easy):**
```python
EXPLICIT_TRANSITION_PATTERNS = [
    r"(now let's|let's move to|switching to|moving on to) (.+)",
    r"(next task|different topic|change of subject)",
    r"(forget that|never mind|actually)",
]
```

**Implicit Detection (Robust - For users who pivot without announcing):**
```python
class ContextBridgeDetector:
    def __init__(self):
        self.current_topic_embedding = None
        self.current_files = set()
        self.message_window = []  # Last 5 messages

    def detect_implicit_shift(self, user_message: str, current_files: set) -> bool:
        """Detect task switch without explicit statement"""

        # 1. Topic Embedding Shift
        new_embedding = get_embedding(user_message)
        if self.current_topic_embedding is not None:
            similarity = cosine_similarity(new_embedding, self.current_topic_embedding)
            if similarity < 0.3:  # Large topic shift
                return True

        # 2. File Context Change
        if current_files != self.current_files and len(current_files) > 0:
            # User switched to different files
            if len(self.current_files.intersection(current_files)) == 0:
                return True  # Completely different file set

        # 3. Keyword Domain Shift
        current_domains = extract_domains(self.message_window)
        new_domains = extract_domains([user_message])
        if not current_domains.intersection(new_domains):
            # Completely different technical domain
            return True

        # 4. Question Type Shift
        # "How do I..." → "Debug this error..." = workflow change
        current_intent = detect_intent(self.message_window)
        new_intent = detect_intent([user_message])
        if current_intent != new_intent:
            return True

        return False

    def trigger_bridge(self, conversation_history):
        """Auto-trigger context bridge on shift detection"""
        # Summarize previous workflow context
        summary = marm_summary(conversation_history[-10:])

        # Save to memory for recall
        marm_contextual_log(
            entry=f"Context Shift Detected\nPrevious: {summary}",
            auto_detected=True
        )

        # Update current context
        self.current_topic_embedding = get_embedding(conversation_history[-1])
        self.message_window = conversation_history[-5:]


def extract_domains(messages: list) -> set:
    """Extract technical domains from messages"""
    domains = {
        'docker': ['docker', 'container', 'dockerfile', 'compose'],
        'database': ['sql', 'database', 'query', 'table', 'sqlite'],
        'frontend': ['react', 'component', 'ui', 'css', 'html'],
        'backend': ['api', 'server', 'endpoint', 'fastapi', 'flask'],
        'cli': ['command', 'terminal', 'shell', 'bash'],
        'ai': ['model', 'llm', 'prompt', 'embedding', 'semantic'],
    }

    detected = set()
    text = " ".join(messages).lower()

    for domain, keywords in domains.items():
        if any(kw in text for kw in keywords):
            detected.add(domain)

    return detected


def detect_intent(messages: list) -> str:
    """Detect user intent type"""
    text = " ".join(messages).lower()

    if any(word in text for word in ['how', 'what', 'why', 'explain']):
        return 'learning'
    elif any(word in text for word in ['error', 'bug', 'broken', 'not working', 'debug']):
        return 'debugging'
    elif any(word in text for word in ['build', 'create', 'implement', 'add']):
        return 'building'
    elif any(word in text for word in ['review', 'check', 'validate', 'test']):
        return 'reviewing'
    else:
        return 'general'
```

**Example Detection:**

```
User: "Help me fix this Docker GPU issue"
[Working on Docker for 10 messages]

User: "Now read the config file for the CLI"
→ Explicit transition detected ("Now...")

User: "What's in settings.json?"
→ Implicit detected:
   - File context changed (Docker → config files)
   - Domain shift (docker → cli configuration)
   - Topic embedding similarity: 0.25 (low)
→ Auto-trigger context bridge
```

**User sees:** Nothing (silent background operation)
**Effect:** Maintains context continuity across task switches

---

═══════════════════════════════════════════════════════════════════════════════
## Protocol Effectiveness (Critical)
═══════════════════════════════════════════════════════════════════════════════

**Challenge:** MARM protocol designed for Claude - will it work with Qwen?

**Solution: Protocol Injection via System Prompt**

```python
def build_system_prompt() -> str:
    """Build MARM-enhanced system prompt for Qwen"""

    # Load MARM protocol from .claude.md or embedded file
    protocol = load_marm_protocol()

    # Load all documentation
    docs = load_documentation()

    # Inject current context
    context = get_current_context()

    return f"""
{protocol}

## Current Context
Date: {context['date']}
Time: {context['time']}

## Loaded Documentation
{docs}

## Available MARM Tools
- marm_smart_recall: Search conversation history
- marm_log_entry: Save important information
- marm_notebook_add: Save reusable instructions
[... full tool list ...]

Remember: Use MARM tools proactively to maintain context and accuracy.
"""
```

**Testing protocol effectiveness:**
1. Test with Qwen3-Coder
2. Verify tool usage patterns
3. Compare to Claude behavior
4. Adjust prompts if needed

---

═══════════════════════════════════════════════════════════════════════════════
## Loaded Documentation Access
═══════════════════════════════════════════════════════════════════════════════

**Goal:** AI can search all MARM Systems docs to understand the project

**Documentation to load:**
```
docs/
├── MARM-CLI-PLAN.md           # CLI architecture
├── MARM-CSA.md                # Customer service builds
├── MARM-CSA-code-reference.md # Code snippets
├── QWEN-CODE-ANALYSIS.md      # CLI patterns learned
├── DOCKER-SETUP.md            # Docker commands
└── .claude/CLAUDE.md          # Development notes
```

**Implementation:**
```python
def load_documentation() -> str:
    """Load all documentation into AI context"""
    docs_path = Path("docs/")

    docs = []
    for md_file in docs_path.glob("**/*.md"):
        content = md_file.read_text()
        docs.append(f"# {md_file.name}\n{content}")

    return "\n\n---\n\n".join(docs)

# Add to system prompt or make searchable
def search_documentation(query: str) -> str:
    """Semantic search across documentation"""
    docs = load_documentation()

    # Use sentence transformers to find relevant sections
    embeddings = get_embeddings(docs)
    query_embedding = get_embedding(query)

    # Find most relevant sections
    relevant = find_similar(query_embedding, embeddings, top_k=3)

    return relevant
```

**Usage:**
```python
# User asks about MARM architecture
> "How does MARM memory work?"

# AI uses search_documentation("MARM memory architecture")
# Gets relevant sections from docs
# Answers based on actual documentation
```

---

═══════════════════════════════════════════════════════════════════════════════
## CLI Tools (10 visible + 3 internal)
═══════════════════════════════════════════════════════════════════════════════

### Visible to User (10)
```
📁 Files: /read, /write, /edit
🔍 Search: /search, /find
💬 Chat: /continue, /clear, /export
⚙️ System: /model, /status
```

### Internal (Not shown in /help) (3)
```
🔧 Internal: /run (execute commands)
🔧 File operations (used by AI)
🔧 MARM tools (background automation)
```

**Total:** 13 CLI commands + 18 MARM tools = 31 total capabilities

---

═══════════════════════════════════════════════════════════════════════════════
## Architecture Integration
═══════════════════════════════════════════════════════════════════════════════

```
MARM CLI v1.0.0
│
├── Ollama (Docker)
│   └── Qwen3-Coder:14b
│
├── MARM Memory Layer (Direct Integration)
│   ├── SQLite Database (conversations.db)
│   ├── Sentence Transformers (embeddings)
│   ├── 18 MARM Tools
│   │   ├── 15 Manual Tools (user/AI calls)
│   │   └── 3 Automated Tools (background)
│   └── Protocol Injection (system prompt)
│
└── CLI Interface (Rich + Prompt Toolkit)
    ├── 10 User Commands
    └── 3 Internal Tools
```

---

═══════════════════════════════════════════════════════════════════════════════
## File Structure
═══════════════════════════════════════════════════════════════════════════════

```
marm-cli/
├── src/
│   ├── main.py              # Entry point
│   ├── cli.py               # CLI framework
│   ├── chat.py              # Chat loop
│   │
│   ├── marm/                # MARM integration
│   │   ├── __init__.py
│   │   ├── database.py      # SQLite + embeddings
│   │   ├── semantic.py      # Sentence transformers
│   │   ├── protocol.py      # Protocol injection
│   │   ├── tools.py         # 18 MARM tools
│   │   ├── automation.py    # Auto-log, refresh, etc.
│   │   └── docs.py          # Documentation loader
│   │
│   ├── commands/            # CLI commands
│   │   ├── files.py         # read/write/edit
│   │   ├── search.py        # search/find
│   │   ├── model.py         # model switching
│   │   └── chat.py          # continue/clear/export
│   │
│   ├── config/
│   │   ├── settings.py      # Settings manager
│   │   └── schema.py        # Pydantic validation
│   │
│   └── ui/
│       ├── theme.py         # Colors/themes
│       └── prompts.py       # Rich/Prompt Toolkit
│
├── docs/                    # Loaded into AI context
│   ├── MARM-CLI-PLAN.md
│   ├── MARM-CSA.md
│   └── *.md
│
├── data/
│   ├── conversations.db     # SQLite database
│   └── embeddings/          # Cached embeddings
│
└── config/
    └── settings.json
```

---

═══════════════════════════════════════════════════════════════════════════════
## Build Order (Today!)
═══════════════════════════════════════════════════════════════════════════════

### Phase 1: Foundation
1. **Project structure** - Create marm-cli/ with src/ layout
2. **Dependencies** - Install Rich, Prompt Toolkit, Click, sentence-transformers
3. **SQLite + embeddings** - Set up database schema
4. **MARM protocol injection** - Load .claude.md into system prompt

### Phase 2: MARM Tools (14 Manual + 3 Automated)
5. **Implement 14 manual tools:**
   - Memory: `marm_smart_recall`
   - Logging: `marm_log_*` (4 tools)
   - Workflow: `marm_summary`
   - Notebook: `marm_notebook_*` (6 tools)
   - Session: `marm_start`
   - System: `marm_system_info`

6. **Build 3 automation systems:**
   - `marm_contextual_log` - Phrase detection + auto-log
   - `marm_refresh` - Smart timer (30min/50msg/10min idle)
   - `marm_context_bridge` - Context shift detection (4 signals)

7. **Test with Qwen** - Verify protocol adherence and tool usage

### Phase 3: CLI Interface
8. **Chat loop** - Rich output + Prompt Toolkit input
9. **10 user commands** - Files, Search, Chat, System categories
10. **Documentation loader** - Load all .md files into AI context
11. **Full integration test** - End-to-end workflow

---

═══════════════════════════════════════════════════════════════════════════════
## Decisions Made ✅
═══════════════════════════════════════════════════════════════════════════════

1. **✅ marm_context_bridge automation** - 4-signal detection (topic embedding, file context, domain shift, intent shift)
2. **✅ Tool visibility** - Show ALL 17 tools in `/help` (14 manual + 3 automated in separate section)
3. **✅ Protocol testing** - User will test directly with Qwen to verify adherence
4. **✅ Automation strategies** - Phrase detection, smart timer, context shift detection approved

---

═══════════════════════════════════════════════════════════════════════════════
## Ready to Build!
═══════════════════════════════════════════════════════════════════════════════

**Next action:** Start Phase 1 - Project structure and dependencies

**Need from you:**
- Test MARM protocol with Qwen (while I build foundation)
- Report back on protocol adherence quality
- We'll adjust system prompt if needed
