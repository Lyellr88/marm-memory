"""Interactive help menu for MARM CLI - Styled modal overlay using prompt_toolkit"""
import asyncio
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl, Dimension
from prompt_toolkit.widgets import Frame, RadioList, Label, Button, Box
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style


# Custom cyan theme matching MARM CLI
help_style = Style.from_dict({
    'frame.border': '#00CED1',  # Cyan border
    'frame.label': '#00CED1 bold',  # Cyan title
    'radio-list': '',
    'radio-list focused': 'reverse',
    'radio-list selected': '#00CED1',
    'radio': '#00CED1',
    'button': '',
    'button.focused': 'reverse',
    'text': '',
})


async def show_help_menu():
    """Display interactive help menu as a styled modal overlay"""
    try:
        await _show_main_menu()
    finally:
        # Force terminal reset after help menu closes
        import sys
        sys.stdout.write('\033[?1049l')  # Exit alternate screen
        sys.stdout.write('\033[?25h')     # Show cursor
        sys.stdout.flush()


async def _show_main_menu():
    """Main help menu with styled radiolist"""

    while True:
        radio_list = RadioList(
            values=[
                ("system", "System Tools (Keyboard shortcuts & commands)"),
                ("marm", "MARM Tools (AI memory & automation)"),
            ],
            show_scrollbar=False
        )

        # Track clicks for double-click detection
        import time
        from prompt_toolkit.mouse_events import MouseEventType, MouseButton
        last_left_click_time = 0.0
        last_left_click_value = None
        last_right_click_time = 0.0

        # Wrap the RadioList control to intercept mouse clicks
        original_mouse_handler = radio_list.control.mouse_handler

        def custom_mouse_handler(mouse_event):
            nonlocal last_left_click_time, last_left_click_value, last_right_click_time
            # Call original handler first
            result = original_mouse_handler(mouse_event)

            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                current_time = time.time()
                current_value = radio_list.current_value
                from prompt_toolkit.application import get_app

                # LEFT CLICK - double click to select and proceed
                if mouse_event.button == MouseButton.LEFT:
                    if (current_time - last_left_click_time < 0.5 and
                        current_value == last_left_click_value):
                        # Double left-click! Select and proceed
                        get_app().exit(result=current_value)
                    last_left_click_time = current_time
                    last_left_click_value = current_value

                # RIGHT CLICK - double click to go back
                elif mouse_event.button == MouseButton.RIGHT:
                    if current_time - last_right_click_time < 0.5:
                        # Double right-click! Go back
                        get_app().exit(result=None)
                    last_right_click_time = current_time

            return result

        radio_list.control.mouse_handler = custom_mouse_handler

        kb = KeyBindings()

        @kb.add('escape')
        def _(event):
            """Handle Escape - close menu"""
            event.app.exit(result=None)

        @kb.add('q')
        def _(event):
            """Handle 'q' key - close menu"""
            event.app.exit(result=None)

        # Build dialog layout
        dialog = Frame(
            body=HSplit([
                Label(text="Select a category (click to navigate, double L-click to select, double R-click to go back):", style='class:label'),
                Window(height=1),  # Spacer
                radio_list,
            ]),
            title="MARM CLI - Help Menu",
            style='class:frame',
        )

        # Center the dialog with reasonable size
        root_container = Box(
            body=dialog,
            padding=2,
            padding_top=5,
            padding_bottom=5,
        )

        layout = Layout(root_container)

        # Merge bindings - put custom kb LAST so it overrides defaults
        merged_kb = merge_key_bindings([load_key_bindings(), kb])

        app = Application(
            layout=layout,
            key_bindings=merged_kb,
            style=help_style,
            full_screen=True,
            mouse_support=True,
        )

        result = await app.run_async()

        if result is None:
            break
        elif result == "system":
            await _show_system_tools()
        elif result == "marm":
            await _show_marm_tools()


async def _show_system_tools():
    """System tools submenu"""
    while True:
        radio_list = RadioList(
            values=[
                ("process", "Process Control (Ctrl+C, Ctrl+D)"),
                ("cursor", "Cursor Movement (Navigation)"),
                ("editing", "Editing & History (Cut, Clear, Search)"),
                ("multiline", "Multi-line Input (Enter, Alt+Enter)"),
                ("copy", "Copy & Paste"),
                ("commands", "Commands (/help, /clear, exit)"),
                ("thinking", "Thinking Mode"),
            ],
            show_scrollbar=False
        )

        # Track clicks for double-click detection
        import time
        from prompt_toolkit.mouse_events import MouseEventType, MouseButton
        last_left_click_time = 0.0
        last_left_click_value = None
        last_right_click_time = 0.0

        original_mouse_handler = radio_list.control.mouse_handler

        def custom_mouse_handler(mouse_event):
            nonlocal last_left_click_time, last_left_click_value, last_right_click_time
            result = original_mouse_handler(mouse_event)

            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                current_time = time.time()
                current_value = radio_list.current_value
                from prompt_toolkit.application import get_app

                # LEFT CLICK - double click to select and proceed
                if mouse_event.button == MouseButton.LEFT:
                    if (current_time - last_left_click_time < 0.5 and
                        current_value == last_left_click_value):
                        # Double left-click! Select and proceed
                        get_app().exit(result=current_value)
                    last_left_click_time = current_time
                    last_left_click_value = current_value

                # RIGHT CLICK - double click to go back
                elif mouse_event.button == MouseButton.RIGHT:
                    if current_time - last_right_click_time < 0.5:
                        # Double right-click! Go back
                        get_app().exit(result=None)
                    last_right_click_time = current_time

            return result

        radio_list.control.mouse_handler = custom_mouse_handler

        kb = KeyBindings()

        @kb.add('escape')
        def _(event):
            event.app.exit(result=None)

        @kb.add('b')
        def _(event):
            """Handle 'b' for back"""
            event.app.exit(result=None)

        dialog = Frame(
            body=HSplit([
                Label(text="Select a topic (click to navigate, double L-click to select, double R-click to go back):", style='class:label'),
                Window(height=1),
                radio_list,
            ], padding=0),
            title="System Tools",
            style='class:frame',
        )

        root_container = Box(body=dialog, padding=2, padding_top=5, padding_bottom=5, padding_right=0)
        layout = Layout(root_container)

        # Merge bindings - custom kb overrides defaults
        merged_kb = merge_key_bindings([load_key_bindings(), kb])

        app = Application(layout=layout, key_bindings=merged_kb, style=help_style, full_screen=True, mouse_support=True)

        result = await app.run_async()

        if result is None:
            break
        elif result == "process":
            await _show_info("Process Control",
                "Ctrl+C (once)      Cancel AI response (while thinking)\n"
                "Ctrl+C (twice)     Exit CLI (within 2 seconds)\n"
                "Ctrl+D             Exit CLI immediately")
        elif result == "cursor":
            await _show_info("Cursor Movement",
                "Ctrl+A / Home      Move to beginning of line\n"
                "Ctrl+E / End       Move to end of line\n"
                "Ctrl+Left/Right    Move by word\n"
                "↑ / ↓              Navigate up/down in input")
        elif result == "editing":
            await _show_info("Editing & History",
                "↑ / ↓ (empty)      Navigate command history\n"
                "Ctrl+R             Reverse search history\n"
                "Ctrl+U             Cut from cursor to start of line\n"
                "Ctrl+K             Cut from cursor to end of line\n"
                "Ctrl+W             Cut word before cursor\n"
                "Ctrl+L             Clear screen (keeps context)\n"
                "Escape (x2)        Clear current input")
        elif result == "multiline":
            await _show_info("Multi-line Input",
                "Enter              Submit message to AI\n"
                "Alt+Enter          Insert newline (multi-line messages)")
        elif result == "copy":
            await _show_info("Copy & Paste",
                "Ctrl+Shift+C       Copy selected text\n"
                "Ctrl+Shift+V       Paste text\n"
                "Mouse Highlight    Select text to copy\n"
                "Right-Click        Copy/paste context menu")
        elif result == "commands":
            await _show_info("Commands",
                "/help              Show this help menu\n"
                "/clear             Reset conversation (fresh start)\n"
                "exit / quit        End session\n"
                "think              Enable thinking mode\n"
                "super think        Enable super thinking mode")
        elif result == "thinking":
            await _show_info("Thinking Mode",
                "think              Enable thinking mode (show reasoning)\n"
                "super think        Enable super thinking (max depth)\n"
                "Tab (x2)           Disable thinking mode")


async def _show_marm_tools():
    """MARM tools submenu"""
    while True:
        radio_list = RadioList(
            values=[
                ("memory", "🧠 Memory (Smart recall & search)"),
                ("logging", "📚 Logging (Session & entry management)"),
                ("reasoning", "🔄 Reasoning (Summaries & analysis)"),
                ("notebook", "📔 Notebook (Reusable instructions)"),
                ("session", "🚀 Session (Session management)"),
                ("system", "⚙️ System (System information)"),
            ],
            show_scrollbar=False
        )

        # Track clicks for double-click detection
        import time
        from prompt_toolkit.mouse_events import MouseEventType, MouseButton
        last_left_click_time = 0.0
        last_left_click_value = None
        last_right_click_time = 0.0

        original_mouse_handler = radio_list.control.mouse_handler

        def custom_mouse_handler(mouse_event):
            nonlocal last_left_click_time, last_left_click_value, last_right_click_time
            result = original_mouse_handler(mouse_event)

            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                current_time = time.time()
                current_value = radio_list.current_value
                from prompt_toolkit.application import get_app

                # LEFT CLICK - double click to select and proceed
                if mouse_event.button == MouseButton.LEFT:
                    if (current_time - last_left_click_time < 0.5 and
                        current_value == last_left_click_value):
                        # Double left-click! Select and proceed
                        get_app().exit(result=current_value)
                    last_left_click_time = current_time
                    last_left_click_value = current_value

                # RIGHT CLICK - double click to go back
                elif mouse_event.button == MouseButton.RIGHT:
                    if current_time - last_right_click_time < 0.5:
                        # Double right-click! Go back
                        get_app().exit(result=None)
                    last_right_click_time = current_time

            return result

        radio_list.control.mouse_handler = custom_mouse_handler

        kb = KeyBindings()

        @kb.add('escape')
        def _(event):
            event.app.exit(result=None)

        @kb.add('b')
        def _(event):
            event.app.exit(result=None)

        dialog = Frame(
            body=HSplit([
                Label(text="AI calls these automatically (click to navigate, double L-click to select, double R-click to go back):", style='class:label'),
                Window(height=1),
                radio_list,
            ], padding=0),
            title="MARM Tools",
            style='class:frame',
        )

        root_container = Box(body=dialog, padding=2, padding_top=5, padding_bottom=5, padding_right=0)
        layout = Layout(root_container)

        # Merge bindings - custom kb overrides defaults
        merged_kb = merge_key_bindings([load_key_bindings(), kb])

        app = Application(layout=layout, key_bindings=merged_kb, style=help_style, full_screen=True, mouse_support=True)

        result = await app.run_async()

        if result is None:
            break
        elif result == "memory":
            await _show_info("🧠 Memory Tools",
                "marm_smart_recall  Search past conversations using semantic understanding\n"
                "                   Finds relevant context even if exact words don't match\n\n"
                "┌──────┬─────────────────────────────────────────────────────────────────────┐\n"
                "│ WHAT │ Vector-based semantic search across all conversation history        │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ HOW  │ AI automatically calls this when you reference past discussions     │\n"
                "│      │ Responds to: 'What did we discuss about...', 'Remember when...',    │\n"
                "│      │              'Earlier you mentioned...'                             │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ WHY  │ Enables true long-term memory - AI recalls context from weeks/      │\n"
                "│      │ months ago                                                          │\n"
                "└──────┴─────────────────────────────────────────────────────────────────────┘\n\n"
                "💡 Natural language queries work best: 'Find that bug fix we discussed' vs 'search bug'")
        elif result == "logging":
            await _show_info("📚 Logging Tools",
                "marm_log_session   Saves entire conversation with metadata for future reference\n"
                "marm_log_entry     Captures single important exchange or code snippet\n"
                "marm_log_show      Browse saved sessions and entries by date/topic\n"
                "marm_log_delete    Remove outdated or sensitive logged content\n\n"
                "┌──────┬─────────────────────────────────────────────────────────────────────┐\n"
                "│ WHAT │ Persistent storage system for important conversations and moments   │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ HOW  │ AI auto-logs key breakthroughs, solutions, and decisions during     │\n"
                "│      │ chat. Responds to: 'Save this conversation', 'Log this solution',   │\n"
                "│      │                    'Show my logs'                                   │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ WHY  │ Build a searchable knowledge base from your AI interactions         │\n"
                "└──────┴─────────────────────────────────────────────────────────────────────┘\n\n"
                "💡 Auto-logging is ON by default - AI decides what's worth saving")
        elif result == "reasoning":
            await _show_info("🔄 Reasoning Tools",
                "marm_summary       Analyzes conversation and generates structured summary\n"
                "                   Captures decisions made, problems solved, and next steps\n\n"
                "┌──────┬─────────────────────────────────────────────────────────────────────┐\n"
                "│ WHAT │ AI-powered conversation analysis and synthesis                      │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ HOW  │ AI automatically summarizes when sessions get long or complex.      │\n"
                "│      │ Responds to: 'Summarize our conversation', 'What have we            │\n"
                "│      │              accomplished?', 'Recap please'                         │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ WHY  │ Never lose track of complex multi-topic conversations               │\n"
                "└──────┴─────────────────────────────────────────────────────────────────────┘\n\n"
                "💡 Great for ending sessions - creates a checkpoint you can recall later")
        elif result == "notebook":
            await _show_info("📔 Notebook Tools",
                "marm_notebook_add     Save reusable instructions, preferences, or context\n"
                "marm_notebook_use     Activate saved notebook to inject into current session\n"
                "marm_notebook_show    List all saved notebook entries\n"
                "marm_notebook_delete  Remove individual notebook entry\n"
                "marm_notebook_clear   Delete all notebook entries\n"
                "marm_notebook_status  Check which notebooks are active\n\n"
                "┌──────┬─────────────────────────────────────────────────────────────────────┐\n"
                "│ WHAT │ Reusable context snippets that persist across sessions              │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ HOW  │ AI saves important patterns, preferences, or instructions you want  │\n"
                "│      │ to reuse. Responds to: 'Remember this for future sessions', 'Save   │\n"
                "│      │                        this to notebook', 'Use my coding style'     │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ WHY  │ Teach AI your preferences once, apply them to every conversation    │\n"
                "└──────┴─────────────────────────────────────────────────────────────────────┘\n\n"
                "💡 Examples: Code style guides, project context, preferred explanation depth")
        elif result == "session":
            await _show_info("🚀 Session Tools",
                "marm_start         Initialize new MARM session or reset current one\n"
                "                   Loads user preferences and active notebooks automatically\n\n"
                "┌──────┬─────────────────────────────────────────────────────────────────────┐\n"
                "│ WHAT │ Session management and initialization system                        │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ HOW  │ AI auto-starts session on first message - manual start rarely       │\n"
                "│      │ needed. Responds to: 'Start fresh', 'Reset session', 'New           │\n"
                "│      │                      conversation'                                  │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ WHY  │ Ensures MARM memory system is active and ready                      │\n"
                "└──────┴─────────────────────────────────────────────────────────────────────┘\n\n"
                "💡 Sessions auto-start - you only need this for manual resets")
        elif result == "system":
            await _show_info("⚙️ System Tools",
                "marm_system_info   Display MARM version, status, and configuration\n"
                "                   Shows database size, active features, and health metrics\n\n"
                "┌──────┬─────────────────────────────────────────────────────────────────────┐\n"
                "│ WHAT │ System diagnostics and status reporting                             │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ HOW  │ AI calls this when you ask about MARM's capabilities or status.     │\n"
                "│      │ Responds to: 'Show system info', 'What version?', 'Is MARM          │\n"
                "│      │              working?'                                              │\n"
                "├──────┼─────────────────────────────────────────────────────────────────────┤\n"
                "│ WHY  │ Verify MARM is functioning and check memory usage                   │\n"
                "└──────┴─────────────────────────────────────────────────────────────────────┘\n\n"
                "💡 Useful for troubleshooting or confirming features are enabled")


async def _show_info(title: str, content: str):
    """Display an info panel with content"""
    import time
    from prompt_toolkit.mouse_events import MouseEventType, MouseButton

    kb = KeyBindings()
    last_right_click_time = 0.0

    @kb.add('enter',)
    def _(event):
        event.app.exit()

    @kb.add('escape')
    def _(event):
        event.app.exit()

    @kb.add('b')
    def _(event):
        event.app.exit()

    # Create text control with mouse handler
    text_control = FormattedTextControl(text=content)

    # Add mouse handler to the text control
    original_mouse_handler = text_control.mouse_handler

    def custom_mouse_handler(mouse_event):
        nonlocal last_right_click_time
        result = original_mouse_handler(mouse_event)

        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            if mouse_event.button == MouseButton.RIGHT:
                current_time = time.time()
                if current_time - last_right_click_time < 0.5:
                    # Double right-click! Go back
                    from prompt_toolkit.application import get_app
                    get_app().exit()
                last_right_click_time = current_time
        return result

    text_control.mouse_handler = custom_mouse_handler

    dialog = Frame(
        body=HSplit([
            Window(
                content=text_control,
                wrap_lines=True,
            ),
            Window(height=1),
        ]),
        title=title,
        style='class:frame',
    )

    root_container = Box(body=dialog, padding=2, padding_top=5, padding_bottom=5)
    layout = Layout(root_container)
    app = Application(layout=layout, key_bindings=kb, style=help_style, full_screen=True, mouse_support=True)

    await app.run_async()
