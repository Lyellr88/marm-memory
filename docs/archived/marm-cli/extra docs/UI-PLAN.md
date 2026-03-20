# Phase 4: Polish CLI Interface and UX - Implementation Plan

**Goal:** Make MARM CLI feel as smooth as qwen-code/Claude CLI using Python (Rich + Prompt Toolkit)

**Philosophy:** Copy and paste should work intuitively. Mouse highlighting + right-click copy. Keyboard shortcuts users already know. Make it feel native.

---

## 🎯 What We're Mimicking from qwen-code

**Key UX Patterns:**
1. **Native Copy/Paste** - Terminal handles mouse selection, we enable bracketed paste
2. **Keyboard Shortcuts** - Ctrl+C, Ctrl+L, Ctrl+U, Arrow keys, Ctrl+R search
3. **Multi-line Input** - Shift+Enter for newlines, Enter to submit
4. **Command History** - Up/Down navigation with Ctrl+R reverse search
5. **Rich Output** - Markdown rendering with syntax highlighting
6. **Smart Text Wrapping** - Don't break words mid-line

---

## ✅ What We Already Have (Phase 2b/3b Complete)

### Current Implementation (chat.py)
```python
# Rich Console for output
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# Prompt Toolkit for input
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

console = Console()
```

**Already Working:**
- ✅ Markdown rendering (via Rich)
- ✅ Command history (via Prompt Toolkit FileHistory)
- ✅ Syntax highlighting (Rich built-in)
- ✅ Color output (Rich themes)
- ✅ Panel/box rendering
- ✅ Multi-line input support (Prompt Toolkit default)

---

## 🔨 What Needs Enhancement

### 1. Keyboard Shortcuts & Keybindings

**Current State:** Prompt Toolkit provides most standard shortcuts by default

**What Prompt Toolkit Already Has (Built-in, no code needed):**
- ✅ Ctrl+C - Cancel operation
- ✅ Ctrl+D - Exit (when input empty)
- ✅ Ctrl+A / Home - Move to start of line
- ✅ Ctrl+E / End - Move to end of line
- ✅ Ctrl+Left/Right - Word-by-word navigation
- ✅ Up/Down Arrow - History navigation
- ✅ Ctrl+U - Cut from cursor to start
- ✅ Ctrl+K - Cut from cursor to end
- ✅ Ctrl+W - Cut word before cursor
- ✅ Ctrl+R - Reverse search history
- ✅ Tab - Auto-completion (when enabled)

**Custom Shortcuts We Need to Add:**
```python
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

kb = KeyBindings()

# Clear screen (Ctrl+L)
@kb.add('c-l')
def clear_screen(event):
    """Clear the entire screen (industry standard)"""
    console.clear()

# Multi-line input alternatives
@kb.add('escape', 'enter')  # Alt+Enter (standard alternative)
def newline_alt(event):
    """Insert newline - Alt+Enter (common in CLIs)"""
    event.current_buffer.insert_text('\n')

@kb.add('c-s-j')  # Ctrl+Shift+J (user preference)
def newline_ctrl_shift_j(event):
    """Insert newline - Ctrl+Shift+J (power user option)"""
    event.current_buffer.insert_text('\n')

# Custom: Toggle thinking mode
@kb.add('c-s-tab')
def toggle_thinking_mode(event):
    """Toggle thinking mode - Ctrl+Shift+Tab"""
    self.thinking_mode = not self.thinking_mode
    status = "enabled" if self.thinking_mode else "disabled"
    console.print(f"[dim]💭 Thinking mode {status}[/dim]")

# Custom: Clear input (double escape)
@kb.add('escape', 'escape')
def clear_input_double_escape(event):
    """Clear current input - Tap Escape twice"""
    event.current_buffer.reset()
    console.print("[dim]✗ Input cleared[/dim]")
```

**Copy/Paste Shortcuts:**
- ✅ Ctrl+Shift+C - Copy (terminal handles this)
- ✅ Ctrl+Shift+V - Paste (terminal handles this)
- ✅ Mouse selection + right-click - Copy/paste (terminal native)
- **No code needed** - these are terminal emulator features

**Files to Modify:**
- `src/chat.py` - Add KeyBindings to PromptSession initialization
- `src/chat.py` - Add `self.thinking_mode` flag to MARMChat class

---

# IMPORTANT


THIS IS NOT THNKING MODE FOR CLAUDE THIS IS - "Thinking mode" in the Claude Code CLI refers to the ability for Claude to spend additional computation time and effort on complex problems before providing a solution. It is particularly useful for intricate coding tasks, architectural decisions, and bug fixes where a quick response is less important than a deeply reasoned one. 
How thinking mode works
Instead of immediately generating a response, the "thinking mode" causes Claude to engage in a step-by-step internal reasoning process. This can lead to more robust and accurate solutions. The process is made visible to the developer in the CLI, allowing you to observe Claude's thought process. 
Levels of thinking
You can trigger different levels of thinking by including specific keywords in your prompt, which allocate a progressively larger "thinking budget" of tokens. 
think: Triggers a basic level of extended thinking, useful for straightforward tasks or planning.
think hard: Instructs Claude to dedicate more computational effort, which is suitable for complex business logic or architectural decisions.
think harder / ultrathink: Unlocks the maximum reasoning capabilities for the most challenging and intricate problems, such as performance optimization or legacy code integration. 

For a full-stack architect building complex tools, using thinking mode is a recommended best practice for critical design and implementation phases. It provides a transparent, controllable, and high-performance way to leverage Claude's most advanced reasoning capabilities. 

---

**What is Thinking Mode?**
When enabled, AI will show its reasoning process before answering (like Claude's "thinking" feature).
- **Enabled:** AI explains its thought process step-by-step
- **Disabled:** AI gives direct answers without showing reasoning
- **Toggle:** Ctrl+Shift+Tab
- **Visual Feedback:** `[dim]Thinking mode enabled/disabled[/dim]`

**Implementation:**
```python
class MARMChat:
    def __init__(self):
        # ... existing initialization ...
        self.thinking_mode = False  # Default off

    async def _get_response_with_tools(self, user_input: str) -> Message:
        # Modify system prompt based on thinking mode
        if self.thinking_mode:
            thinking_instruction = "\n\nBefore answering, explain your reasoning step-by-step using <thinking> tags."
            # Prepend to user message or inject into system prompt
        # ... rest of method ...
```

---

### 2. Bracketed Paste Mode

**What it does:** Detects when user pastes text vs types it

**Why it matters:**
- Prevents accidental command execution
- Better handling of multi-line pastes
- Prevents formatting corruption

**Implementation:**
```python
from prompt_toolkit import PromptSession
from prompt_toolkit.application import run_in_terminal

# Enable bracketed paste (Prompt Toolkit supports this)
prompt_session = PromptSession(
    history=FileHistory(str(history_file)),
    enable_history_search=True,
    enable_system_prompt=True,  # Enables bracketed paste
    multiline=True,
    wrap_lines=True,
)
```

**Already Supported:** Prompt Toolkit has built-in bracketed paste support via `enable_system_prompt=True`

---

### 3. Copy/Paste Native Terminal Support

**qwen-code Approach:** Let terminal emulator handle mouse selection

**Our Approach:** Same - terminal already supports:
- Mouse highlight to select text
- Right-click to copy (Windows/Linux)
- Cmd+C to copy (macOS)
- Middle-click paste (Linux)
- Ctrl+Shift+V paste (most terminals)

**No custom code needed** - terminals handle this natively when we output plain text

**What we need to avoid:**
- ❌ Don't use Rich's `overflow="ignore"` (breaks selection)
- ❌ Don't use `no_wrap=True` (makes copy include ANSI codes)
- ✅ Use `console.print()` with defaults
- ✅ Enable `markup=False` for code blocks

---

### 4. Smart Text Wrapping

**Current:** Rich auto-wraps but may break mid-word

**Enhancement:**
```python
from rich.console import Console

# Create console with word wrapping
console = Console(
    width=None,  # Auto-detect terminal width
    soft_wrap=True,  # Don't break words mid-line
    markup=True,  # Allow Rich markup
    emoji=True,  # Support emoji rendering
)

# For code blocks - disable wrapping
console.print(code_block, markup=False, soft_wrap=False, overflow="ignore")
```

**Files to Modify:**
- `src/chat.py` - Update Console initialization

---

### 5. Enhanced Command History with Ctrl+R

**Current State:** Basic history via FileHistory

**Enhancement:**
```python
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

prompt_session = PromptSession(
    history=FileHistory(str(history_file)),
    enable_history_search=True,  # Ctrl+R reverse search
    auto_suggest=AutoSuggestFromHistory(),  # Fish-style suggestions
    complete_while_typing=False,  # Don't auto-complete mid-typing
)
```

**Already Supported:** Prompt Toolkit has Ctrl+R built-in when `enable_history_search=True`

---

### 6. Multi-line Input with Visual Feedback

**Goal:** Show continuation prompt for multi-line input

**Implementation:**
```python
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML

# Primary prompt
primary_prompt = HTML('<ansiblue><b>&gt;</b></ansiblue> ')

# Continuation prompt (for multi-line)
continuation_prompt = HTML('<ansiblue>...</ansiblue> ')

prompt_session = PromptSession(
    message=primary_prompt,
    prompt_continuation=continuation_prompt,
    multiline=True,
)
```

**Files to Modify:**
- `src/chat.py` - Update prompt formatting

---

### 7. Loading Indicators & Streaming

**Current:** No visual feedback during LLM response

**Enhancement:**
```python
from rich.live import Live
from rich.spinner import Spinner

# Option 1: Spinner while waiting
with console.status("[cyan]Thinking...", spinner="dots"):
    response = await self.ollama.chat_completion(messages)

# Option 2: Stream tokens as they arrive (requires streaming API)
with Live(console=console, refresh_per_second=10) as live:
    async for token in self.ollama.stream_completion(messages):
        live.update(token)
```

**Current Limitation:** Our Ollama client doesn't stream yet (Phase 3 was non-streaming)

**Recommendation:** Add simple spinner for now, implement streaming in Phase 5

---

### 8. Better Error Messages

**Current:** Basic exception logging

**Enhancement:**
```python
from rich.panel import Panel
from rich.traceback import Traceback

try:
    result = await some_operation()
except ToolError as e:
    console.print(Panel(
        f"[red]✗ {e.error_type.value}[/red]\n\n{e.message}",
        title="Tool Error",
        border_style="red"
    ))
except Exception as e:
    console.print(Traceback.from_exception(
        type(e), e, e.__traceback__,
        show_locals=True,
        max_frames=10
    ))
```

**Files to Modify:**
- `src/chat.py` - Wrap try/except blocks with Rich error rendering

---

### 9. Status Bar / Session Info

**Goal:** Show model, session, token count at top/bottom

**Implementation:**
```python
from rich.layout import Layout
from rich.panel import Panel

layout = Layout()
layout.split(
    Layout(name="header", size=3),
    Layout(name="main"),
    Layout(name="footer", size=1)
)

# Header with session info
layout["header"].update(Panel(
    f"MARM CLI v1.0.0 | Model: {model} | Session: {session_id[:8]}",
    style="cyan"
))

# Footer with shortcuts
layout["footer"].update(
    "Ctrl+L Clear | Ctrl+R Search | Ctrl+C Cancel | /help Commands"
)
```

**Optional for v1.0** - Nice-to-have but not essential

---

### 10. Help Command Enhancement

**Current:** Basic help text in chat.py

**Enhancement:**
```python
from rich.table import Table
from rich.panel import Panel

def _show_help(self):
    # Create shortcuts table grouped by category

    # Process Control
    process = Table(title="Process Control", show_header=True, border_style="cyan")
    process.add_column("Shortcut", style="cyan", no_wrap=True)
    process.add_column("Action")
    process.add_row("Ctrl+C", "Cancel current operation")
    process.add_row("Ctrl+D", "Exit (when input is empty)")
    console.print(process)
    console.print()

    # Cursor Movement
    cursor = Table(title="Cursor Movement", show_header=True, border_style="blue")
    cursor.add_column("Shortcut", style="blue", no_wrap=True)
    cursor.add_column("Action")
    cursor.add_row("Ctrl+A / Home", "Move to beginning of line")
    cursor.add_row("Ctrl+E / End", "Move to end of line")
    cursor.add_row("Ctrl+Left/Right", "Move by word")
    console.print(cursor)
    console.print()

    # Editing & History
    editing = Table(title="Editing & History", show_header=True, border_style="green")
    editing.add_column("Shortcut", style="green", no_wrap=True)
    editing.add_column("Action")
    editing.add_row("↑ / ↓", "Navigate command history")
    editing.add_row("Ctrl+R", "Reverse search history")
    editing.add_row("Ctrl+U", "Cut from cursor to start of line")
    editing.add_row("Ctrl+K", "Cut from cursor to end of line")
    editing.add_row("Ctrl+W", "Cut word before cursor")
    editing.add_row("Ctrl+L", "Clear screen")
    editing.add_row("Tab", "Auto-complete (when available)")
    console.print(editing)
    console.print()

    # Multi-line Input
    multiline = Table(title="Multi-line Input", show_header=True, border_style="yellow")
    multiline.add_column("Shortcut", style="yellow", no_wrap=True)
    multiline.add_column("Action")
    multiline.add_row("Shift+Enter", "Insert newline")
    multiline.add_row("Alt+Enter", "Insert newline (alternative)")
    multiline.add_row("Ctrl+Shift+J", "Insert newline (power user)")
    multiline.add_row("Enter", "Submit message")
    console.print(multiline)
    console.print()

    # Copy & Paste
    copypaste = Table(title="Copy & Paste", show_header=True, border_style="magenta")
    copypaste.add_column("Shortcut", style="magenta", no_wrap=True)
    copypaste.add_column("Action")
    copypaste.add_row("Ctrl+Shift+C", "Copy selected text")
    copypaste.add_row("Ctrl+Shift+V", "Paste text")
    copypaste.add_row("Mouse Highlight", "Select text to copy")
    copypaste.add_row("Right-Click", "Copy/paste context menu")
    console.print(copypaste)
    console.print()

    # Custom Features
    custom = Table(title="MARM Features", show_header=True, border_style="red")
    custom.add_column("Shortcut", style="red", no_wrap=True)
    custom.add_column("Action")
    custom.add_row("Escape Escape", "Clear input (tap twice)")
    custom.add_row("Ctrl+Shift+Tab", "Toggle thinking mode 💭")
    console.print(custom)
    console.print()

    # Create commands table
    commands = Table(title="Available Commands", show_header=True)
    commands.add_column("Command", style="green")
    commands.add_column("Description")

    commands.add_row("/help", "Show this help message")
    commands.add_row("/clear", "Clear screen (preserves context)")
    commands.add_row("/status", "Show system status")
    commands.add_row("/export", "Export conversation")
    commands.add_row("/exit", "Exit chat")

    console.print(commands)
```

**Files to Modify:**
- `src/chat.py` - Replace `_show_help()` method with Rich tables

---

## 📝 Implementation Checklist

### Quick Wins (1-2 hours)
- [ ] Add KeyBindings to PromptSession (Ctrl+L, Ctrl+U)
- [ ] Enable bracketed paste (`enable_system_prompt=True`)
- [ ] Add continuation prompt for multi-line (`...`)
- [ ] Update Console with `soft_wrap=True`
- [ ] Add AutoSuggestFromHistory for fish-style hints
- [ ] Enhance help command with Rich tables

### Medium Priority (2-4 hours)
- [ ] Add loading spinner for LLM responses
- [ ] Wrap errors in Rich Panels with better formatting
- [ ] Add validation for empty/whitespace-only input
- [ ] Add confirmation prompts for dangerous operations
- [ ] Show tool execution feedback with icons (🔧, ✓, ✗)

### Optional Enhancements (Later)
- [ ] Status bar with session info
- [ ] Token counter display
- [ ] Streaming response support
- [ ] Custom themes/color schemes
- [ ] Tab completion for commands

---

## 🎨 Visual Style Guide

### Colors (Rich built-in themes)
- **Primary Prompt:** Blue (`[cyan]`)
- **Success Messages:** Green (`[green]`)
- **Errors:** Red (`[red]`)
- **Warnings:** Yellow (`[yellow]`)
- **Info:** Dim white (`[dim]`)
- **Code Blocks:** Auto-highlighted by Rich

### Formatting
- **Headings:** Bold (`[bold]`)
- **Emphasis:** Italic (`[italic]`)
- **Commands:** Monospace (`[code]`)
- **Panels:** Border style based on message type

### Icons (Unicode)
- ✓ Success
- ✗ Error
- ⚠️  Warning
- 🔧 Tool execution
- 💾 Save operation
- 🔄 Loading/processing
- 📋 Copy operation

---

## 🚀 Testing Checklist

### Terminal Compatibility
- [ ] Windows Terminal
- [ ] PowerShell
- [ ] Command Prompt
- [ ] WSL Terminal
- [ ] macOS Terminal
- [ ] iTerm2
- [ ] Linux terminals (gnome-terminal, konsole)

### Copy/Paste Testing
- [ ] Mouse selection copies correctly
- [ ] Right-click paste works
- [ ] Ctrl+Shift+V paste works
- [ ] Multi-line paste preserves formatting
- [ ] Code blocks copy without ANSI codes

### Keyboard Shortcuts
- [ ] Ctrl+L clears screen
- [ ] Ctrl+U clears line
- [ ] Ctrl+R searches history
- [ ] Ctrl+C cancels operation
- [ ] Ctrl+D exits gracefully
- [ ] Arrow keys navigate history
- [ ] Shift+Enter adds newline
- [ ] Ctrl+Shift+J adds line break
- [ ] Enter submits message
- [ ] Escape Escape clears input
- [ ] Ctrl+Shift+Tab toggles thinking mode

### Edge Cases
- [ ] Very long messages (>1000 lines)
- [ ] Unicode/emoji rendering
- [ ] ANSI color codes in output
- [ ] Terminal resize mid-conversation
- [ ] Paste with special characters
- [ ] Ctrl+C during LLM response

---

## 📂 Files to Modify

**Primary File:**
- `src/chat.py` - Main chat loop (currently ~200 lines)

**Expected Changes:**
1. Update `PromptSession` initialization with KeyBindings
2. Add `Console` configuration for soft wrapping
3. Enhance error handling with Rich Panels
4. Update `_show_help()` with Rich tables
5. Add loading indicators for async operations
6. Add validation for empty input

**Estimated Total:** ~250-300 lines after Phase 4

---

---

## 📋 Task Tracking System (Automated Todos)

### How It Works (Like Claude Code's TodoWrite)

**User-Initiated, AI-Managed:**
- User says: "Track our progress with todos" or "Create a todo list for Phase 4"
- AI creates relevant todos (3-10 items, not 100+)
- AI automatically updates status as work progresses
- Shows up in compacts/summaries for visibility

**Example Flow:**
```bash
User: "Let's implement Phase 4. Track our progress with todos"

AI: "I'll create a todo list for Phase 4 implementation:
📋 Todos created:
[ ] Add keyboard shortcuts (Ctrl+L, Alt+Enter, Esc Esc, Ctrl+Shift+Tab)
[ ] Enhance help command with Rich tables
[ ] Implement streaming responses
[ ] Add /clear command
[ ] Better error formatting"

[AI starts work]

AI: "Added keyboard shortcuts to chat.py"
✅ Marked complete: Add keyboard shortcuts

📋 Remaining todos:
[ ] Enhance help command with Rich tables
[ ] Implement streaming responses
[ ] Add /clear command
[ ] Better error formatting
```

### Implementation Details

**Storage:**
- In-memory list during session (not database - keeps it lightweight)
- Shows in `/status` command
- Included in conversation compacts

**AI Control:**
```python
# AI can call these via function calling
todo_add(task: str, status: str = "pending")
todo_update(task_id: int, status: str)  # "pending", "in_progress", "completed"
todo_list() -> List[Dict]
todo_clear()  # Clear all completed
```

**Display Format:**
```
📋 Current Tasks (3/5 complete):
✅ Add keyboard shortcuts
✅ Enhance help command
✅ Implement streaming
🔄 Add /clear command (in progress)
⏳ Better error formatting (pending)
```

**Limits:**
- Max 15 todos per session (prevents clutter)
- Auto-clear completed after 10+ todos
- Only shows when todos exist (not always visible)

### When Todos Appear

1. **User explicitly requests tracking**
2. **AI suggests it for complex multi-step tasks**
3. **Shows in compacts** (conversation summaries)
4. **Shows in `/status`** command output

### Files to Create
- `src/marm/todos.py` - Todo management class
- Add to tool registry as automated tool (like ContextualLogger)

---

## 🌊 Streaming Responses

### Implementation Plan

**Goal:** Real-time token display like Claude/Qwen CLIs

**Current State:**
- `ollama_client.py` uses non-streaming `chat_completion()`
- Response appears all at once after 5-10 seconds

**Target State:**
- Tokens appear as generated
- "Thinking..." spinner before first token
- Smooth, responsive feel

**Implementation:**
```python
# Add to ollama_client.py
async def stream_chat_completion(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
    """Stream tokens as they're generated"""
    response = await self.client.post(
        f"{self.base_url}/chat/completions",
        json={
            "model": self.model,
            "messages": messages,
            "tools": self.tools,
            "stream": True  # Enable streaming
        },
        timeout=120.0
    )

    async for line in response.aiter_lines():
        if line.startswith("data: "):
            chunk = json.loads(line[6:])
            if "choices" in chunk:
                delta = chunk["choices"][0].get("delta", {})
                if "content" in delta:
                    yield delta["content"]

# Update chat.py
from rich.live import Live

async def _get_response_with_tools(self, user_input: str):
    with Live(console=console, refresh_per_second=10) as live:
        response_text = ""

        # Show spinner while waiting for first token
        live.update("[cyan]Thinking...[/cyan]")

        async for token in self.ollama.stream_chat_completion(messages):
            response_text += token
            # Update display with accumulated text
            live.update(Markdown(response_text))

        return response_text
```

**Estimated Lines:** ~100-150 for streaming implementation

---

## 🎯 Success Criteria

**Phase 4 is complete when:**
1. ✅ Copy/paste works naturally (mouse + right-click)
2. ✅ All keyboard shortcuts functional (Ctrl+L, Ctrl+U, Ctrl+R)
3. ✅ Multi-line input works with Shift+Enter
4. ✅ Command history with up/down arrows
5. ✅ Help command shows formatted tables
6. ✅ **Streaming responses** show tokens in real-time
7. ✅ **Todos system** tracks multi-step tasks automatically
8. ✅ Error messages clearly formatted
9. ✅ Works across Windows/macOS/Linux terminals

**Feel Test:** Should feel as smooth as qwen-code/Claude CLI with todos + streaming

---

**Next:** Start with quick wins (KeyBindings + help command), then add streaming, then todos system.
