"""MARM Tools - 14 Manual Tools for Memory & Accuracy

Implements all MARM tools using DeclarativeTool pattern:
- 1 Memory Intelligence: marm_smart_recall
- 4 Logging System: marm_log_session, marm_log_entry, marm_log_show, marm_log_delete
- 1 Reasoning: marm_summary
- 6 Notebook: marm_notebook_add/use/show/delete/clear/status
- 1 Session: marm_start
- 1 System: marm_system_info
"""

from pydantic import BaseModel, Field
from typing import Optional, Callable, List, Dict
from datetime import datetime
import logging
import platform
import os

from .tools import BaseDeclarativeTool, BaseToolInvocation, ToolKind
from .tool_error import ToolResult
from .database import MARMDatabase
from .semantic import SemanticSearch
from .protocol import ProtocolInjector
from .tool_context import get_shared_db, get_shared_semantic

logger = logging.getLogger(__name__)


# ============================================================================
# 🧠 MEMORY INTELLIGENCE (1 tool)
# ============================================================================

class SmartRecallParams(BaseModel):
    """Parameters for marm_smart_recall"""
    query: str = Field(..., description="Search query to find in conversation history")
    session_name: str = Field(default="main", description="Session to search in (use 'all' for search_all)")
    limit: int = Field(default=5, description="Maximum number of results to return", ge=1, le=20)


class SmartRecallInvocation(BaseToolInvocation[SmartRecallParams, ToolResult]):
    """Smart recall invocation - semantic memory search"""

    def get_description(self) -> str:
        search_scope = "all sessions" if self.params.session_name == "all" else f"session '{self.params.session_name}'"
        return f"Searching {search_scope} for: {self.params.query}"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Execute semantic memory search"""
        try:
            db = get_shared_db()
            semantic = get_shared_semantic()

            search_all = self.params.session_name == "all"
            session_filter = None if search_all else self.params.session_name

            # Search conversations (get more for similarity filtering)
            conversations = db.search_conversations(session_id=session_filter, limit=100)

            if not conversations:
                message = f"🤔 No memories found" + (f" in session '{self.params.session_name}'" if not search_all else "")
                # db.close() - using shared instance, don't close
                return ToolResult(llm_content=message, return_display=message)

            # Build corpus for semantic search
            corpus = [(conv['id'], f"{conv['user_message']} {conv['ai_response']}") for conv in conversations]

            # Find similar conversations
            results = semantic.search_text(query=self.params.query, corpus=corpus, top_k=self.params.limit, threshold=0.3)

            if not results:
                message = f"🤔 No relevant memories for: '{self.params.query}'"
                if not search_all:
                    message += f". Try session_name='all' to search everywhere."
                # db.close() - using shared instance, don't close
                return ToolResult(llm_content=message, return_display=message)

            # Format results
            output_lines = [f"🧠 Found {len(results)} relevant memories:\n"]
            for idx, (conv_id, score, text) in enumerate(results, 1):
                conv = next((c for c in conversations if c['id'] == conv_id), None)
                if conv:
                    timestamp = datetime.fromisoformat(conv['timestamp']).strftime("%Y-%m-%d %H:%M")
                    output_lines.append(f"{idx}. [{timestamp}] (similarity: {score:.2f})")
                    output_lines.append(f"   User: {conv['user_message'][:100]}...")
                    output_lines.append(f"   AI: {conv['ai_response'][:100]}...\n")

            result_text = "\n".join(output_lines)
            # db.close() - using shared instance, don't close
            return ToolResult(llm_content=result_text, return_display=result_text)

        except Exception as e:
            logger.exception("Smart recall failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Search failed: {str(e)}")


class SmartRecallTool(BaseDeclarativeTool[SmartRecallParams]):
    """Search conversation history using semantic similarity"""

    def __init__(self):
        super().__init__(
            name="marm_smart_recall",
            display_name="MARM Smart Recall",
            description="Search conversation history semantically. Use when user asks about past conversations, decisions, or setups. Set session_name='all' to search across all sessions.",
            kind=ToolKind.READ,
            parameters_model=SmartRecallParams,
            is_output_markdown=True,
            can_update_output=False
        )

    def create_invocation(self, params: SmartRecallParams) -> SmartRecallInvocation:
        return SmartRecallInvocation(params)


# ============================================================================
# 📚 LOGGING SYSTEM (4 tools)
# ============================================================================

class LogSessionParams(BaseModel):
    """Parameters for marm_log_session"""
    session_name: str = Field(..., description="Name of the session to create or switch to")


class LogSessionInvocation(BaseToolInvocation[LogSessionParams, ToolResult]):
    """Log session invocation"""

    def get_description(self) -> str:
        return f"Creating/switching to session: {self.params.session_name}"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Create or switch to a named session"""
        try:
            db = get_shared_db()
            existing = db.get_session_info(self.params.session_name)

            if existing:
                message = f"✓ Switched to session: '{self.params.session_name}'"
            else:
                db._update_session_activity(self.params.session_name)
                message = f"✓ Created session: '{self.params.session_name}'"

            # db.close() - using shared instance, don't close
            return ToolResult(llm_content=message, return_display=message)

        except Exception as e:
            logger.exception("Log session failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class LogSessionTool(BaseDeclarativeTool[LogSessionParams]):
    """Create or switch to a named session container"""

    def __init__(self):
        super().__init__(
            name="marm_log_session",
            display_name="MARM Log Session",
            description="Create or switch to a named session container for organizing logs. Use when starting a new topic or project.",
            kind=ToolKind.WRITE,
            parameters_model=LogSessionParams,
            is_output_markdown=False,
            can_update_output=False
        )

    def create_invocation(self, params: LogSessionParams) -> LogSessionInvocation:
        return LogSessionInvocation(params)


class LogEntryParams(BaseModel):
    """Parameters for marm_log_entry"""
    entry: str = Field(..., description="Log entry in format: YYYY-MM-DD-topic-summary or just topic-summary (auto-dates)")
    session_name: str = Field(default="main", description="Session to log to")
    entry_type: str = Field(default="general", description="Type: accomplishment, decision, setup, solution, general")


class LogEntryInvocation(BaseToolInvocation[LogEntryParams, ToolResult]):
    """Log entry invocation"""

    def get_description(self) -> str:
        return f"Logging to '{self.params.session_name}': {self.params.entry[:50]}..."

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Add structured log entry"""
        try:
            db = get_shared_db()
            semantic = get_shared_semantic()

            # Auto-add date if not present
            entry = self.params.entry
            if not entry.startswith("20"):  # Simple date check
                today = datetime.now().strftime("%Y-%m-%d")
                entry = f"{today}-{entry}"

            # Generate embedding
            embedding = semantic.get_embedding_bytes(entry)

            # Save to database
            db.add_log_entry(
                session_id=self.params.session_name,
                content=entry,
                entry_type=self.params.entry_type,
                auto_detected=False,
                embedding=embedding
            )

            # db.close() - using shared instance, don't close
            message = f"✓ Logged: {entry}"
            return ToolResult(llm_content=message, return_display=message)

        except Exception as e:
            logger.exception("Log entry failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class LogEntryTool(BaseDeclarativeTool[LogEntryParams]):
    """Add structured log entry to session"""

    def __init__(self):
        super().__init__(
            name="marm_log_entry",
            display_name="MARM Log Entry",
            description="Add structured log entry for milestones, decisions, setups, solutions. Format: YYYY-MM-DD-topic-summary or just topic-summary (auto-dates)",
            kind=ToolKind.WRITE,
            parameters_model=LogEntryParams,
            is_output_markdown=False,
            can_update_output=False
        )

    def create_invocation(self, params: LogEntryParams) -> LogEntryInvocation:
        return LogEntryInvocation(params)


class LogShowParams(BaseModel):
    """Parameters for marm_log_show"""
    session_name: str = Field(default="all", description="Session to show logs from (use 'all' for all sessions)")
    limit: int = Field(default=10, description="Maximum number of entries to show", ge=1, le=50)


class LogShowInvocation(BaseToolInvocation[LogShowParams, ToolResult]):
    """Show log entries"""

    def get_description(self) -> str:
        return f"Showing logs from {self.params.session_name}"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Display log entries"""
        try:
            db = get_shared_db()

            # Get log entries
            query = "SELECT * FROM log_entries"
            params = []

            if self.params.session_name != "all":
                query += " WHERE session_id = ?"
                params.append(self.params.session_name)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(self.params.limit)

            cursor = db.conn.execute(query, params)
            entries = [dict(row) for row in cursor.fetchall()]

            if not entries:
                message = f"📋 No log entries found"
                # db.close() - using shared instance, don't close
                return ToolResult(llm_content=message, return_display=message)

            # Format output
            output_lines = [f"📋 Found {len(entries)} log entries:\n"]
            for entry in entries:
                timestamp = datetime.fromisoformat(entry['timestamp']).strftime("%Y-%m-%d %H:%M")
                entry_type = entry['entry_type'].upper()
                content = entry['content']
                auto = " [AUTO]" if entry['auto_detected'] else ""
                output_lines.append(f"[{timestamp}] [{entry_type}]{auto} {content}")

            result_text = "\n".join(output_lines)
            # db.close() - using shared instance, don't close
            return ToolResult(llm_content=result_text, return_display=result_text)

        except Exception as e:
            logger.exception("Log show failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class LogShowTool(BaseDeclarativeTool[LogShowParams]):
    """Display all log entries"""

    def __init__(self):
        super().__init__(
            name="marm_log_show",
            display_name="MARM Log Show",
            description="Display all entries/sessions. Use session_name='all' to show all sessions or specify a session name.",
            kind=ToolKind.READ,
            parameters_model=LogShowParams,
            is_output_markdown=True,
            can_update_output=False
        )

    def create_invocation(self, params: LogShowParams) -> LogShowInvocation:
        return LogShowInvocation(params)


class LogDeleteParams(BaseModel):
    """Parameters for marm_log_delete"""
    session_name: str = Field(..., description="Session to delete (WARNING: deletes all entries in session)")


class LogDeleteInvocation(BaseToolInvocation[LogDeleteParams, ToolResult]):
    """Delete log session"""

    def get_description(self) -> str:
        return f"Deleting session: {self.params.session_name}"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Delete specified session"""
        try:
            db = get_shared_db()

            # Delete log entries
            db.conn.execute("DELETE FROM log_entries WHERE session_id = ?", (self.params.session_name,))
            # Delete session metadata
            db.conn.execute("DELETE FROM sessions WHERE session_id = ?", (self.params.session_name,))
            db.conn.commit()

            # db.close() - using shared instance, don't close
            message = f"✓ Deleted session: '{self.params.session_name}'"
            return ToolResult(llm_content=message, return_display=message)

        except Exception as e:
            logger.exception("Log delete failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class LogDeleteTool(BaseDeclarativeTool[LogDeleteParams]):
    """Delete specified session or entries"""

    def __init__(self):
        super().__init__(
            name="marm_log_delete",
            display_name="MARM Log Delete",
            description="Delete specified session and all its entries. WARNING: This is permanent.",
            kind=ToolKind.WRITE,
            parameters_model=LogDeleteParams,
            is_output_markdown=False,
            can_update_output=False
        )

    def create_invocation(self, params: LogDeleteParams) -> LogDeleteInvocation:
        return LogDeleteInvocation(params)


# ============================================================================
# 🔄 REASONING & WORKFLOW (1 tool)
# ============================================================================

class SummaryParams(BaseModel):
    """Parameters for marm_summary"""
    session_name: str = Field(default="main", description="Session to summarize")
    limit: int = Field(default=20, description="Number of recent messages to include", ge=5, le=100)


class SummaryInvocation(BaseToolInvocation[SummaryParams, ToolResult]):
    """Generate summary"""

    def get_description(self) -> str:
        return f"Generating summary for '{self.params.session_name}'"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Generate context-aware summary"""
        try:
            db = get_shared_db()

            # Get recent conversations
            conversations = db.search_conversations(session_id=self.params.session_name, limit=self.params.limit)

            if not conversations:
                message = f"📊 No conversations found in session '{self.params.session_name}'"
                # db.close() - using shared instance, don't close
                return ToolResult(llm_content=message, return_display=message)

            # Build summary
            output_lines = [f"📊 Summary of '{self.params.session_name}' ({len(conversations)} recent messages):\n"]

            for conv in reversed(conversations):  # Chronological order
                timestamp = datetime.fromisoformat(conv['timestamp']).strftime("%Y-%m-%d %H:%M")
                output_lines.append(f"[{timestamp}] User: {conv['user_message'][:80]}...")
                output_lines.append(f"              AI: {conv['ai_response'][:80]}...\n")

            result_text = "\n".join(output_lines)
            # db.close() - using shared instance, don't close
            return ToolResult(llm_content=result_text, return_display=result_text)

        except Exception as e:
            logger.exception("Summary failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class SummaryTool(BaseDeclarativeTool[SummaryParams]):
    """Generate context-aware summary"""

    def __init__(self):
        super().__init__(
            name="marm_summary",
            display_name="MARM Summary",
            description="Generate paste-ready context block summarizing session. Use when switching topics or bridging conversations.",
            kind=ToolKind.READ,
            parameters_model=SummaryParams,
            is_output_markdown=True,
            can_update_output=False
        )

    def create_invocation(self, params: SummaryParams) -> SummaryInvocation:
        return SummaryInvocation(params)


# ============================================================================
# 📔 NOTEBOOK MANAGEMENT (6 tools)
# ============================================================================

class NotebookAddParams(BaseModel):
    """Parameters for marm_notebook_add"""
    name: str = Field(..., description="Unique name for the entry (prefer snake_case)")
    data: str = Field(..., description="Content to save")
    summary: Optional[str] = Field(None, description="Brief description (optional)")


class NotebookAddInvocation(BaseToolInvocation[NotebookAddParams, ToolResult]):
    """Add notebook entry"""

    def get_description(self) -> str:
        return f"Saving to notebook: {self.params.name}"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Add entry to notebook"""
        try:
            db = get_shared_db()
            semantic = get_shared_semantic()

            # Generate embedding
            embedding = semantic.get_embedding_bytes(self.params.data)

            # Save to database
            success = db.add_notebook_entry(
                key=self.params.name,
                content=self.params.data,
                summary=self.params.summary,
                embedding=embedding
            )

            # db.close() - using shared instance, don't close

            if success:
                message = f"✓ Saved to notebook: '{self.params.name}'"
                return ToolResult(llm_content=message, return_display=message)
            else:
                return ToolResult(llm_content="❌ Failed to save", return_display="❌ Failed to save")

        except Exception as e:
            logger.exception("Notebook add failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class NotebookAddTool(BaseDeclarativeTool[NotebookAddParams]):
    """Add new entry to notebook"""

    def __init__(self):
        super().__init__(
            name="marm_notebook_add",
            display_name="MARM Notebook Add",
            description="Save reusable instructions or knowledge. Use for coding patterns, preferences, project info.",
            kind=ToolKind.WRITE,
            parameters_model=NotebookAddParams,
            is_output_markdown=False,
            can_update_output=False
        )

    def create_invocation(self, params: NotebookAddParams) -> NotebookAddInvocation:
        return NotebookAddInvocation(params)


class NotebookUseParams(BaseModel):
    """Parameters for marm_notebook_use"""
    names: str = Field(..., description="Comma-separated list of notebook entry names to activate")


class NotebookUseInvocation(BaseToolInvocation[NotebookUseParams, ToolResult]):
    """Activate notebook entries"""

    def get_description(self) -> str:
        return f"Activating notebook entries: {self.params.names}"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Activate notebook entries as instructions"""
        try:
            db = get_shared_db()

            # Clear existing active instructions
            db.clear_active_instructions()

            # Activate each entry
            names = [name.strip() for name in self.params.names.split(',')]
            activated = []

            for name in names:
                if db.activate_instruction(name):
                    activated.append(name)

            # db.close() - using shared instance, don't close

            if activated:
                message = f"✓ Activated: {', '.join(activated)}"
                return ToolResult(llm_content=message, return_display=message)
            else:
                return ToolResult(llm_content="❌ No entries activated", return_display="❌ Failed")

        except Exception as e:
            logger.exception("Notebook use failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class NotebookUseTool(BaseDeclarativeTool[NotebookUseParams]):
    """Activate saved instructions"""

    def __init__(self):
        super().__init__(
            name="marm_notebook_use",
            display_name="MARM Notebook Use",
            description="Activate one or more entries as active instructions. Multiple: marm_notebook_use('name1,name2')",
            kind=ToolKind.WRITE,
            parameters_model=NotebookUseParams,
            is_output_markdown=False,
            can_update_output=False
        )

    def create_invocation(self, params: NotebookUseParams) -> NotebookUseInvocation:
        return NotebookUseInvocation(params)


class NotebookShowParams(BaseModel):
    """Parameters for marm_notebook_show"""
    pass  # No parameters needed


class NotebookShowInvocation(BaseToolInvocation[NotebookShowParams, ToolResult]):
    """Show notebook entries"""

    def get_description(self) -> str:
        return "Showing notebook entries"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Display all saved keys and summaries"""
        try:
            db = get_shared_db()
            entries = db.get_notebook_entries()
            # db.close() - using shared instance, don't close

            if not entries:
                message = "📔 Notebook is empty"
                return ToolResult(llm_content=message, return_display=message)

            # Format output
            output_lines = [f"📔 Notebook ({len(entries)} entries):\n"]
            for entry in entries:
                summary = f" - {entry['summary']}" if entry['summary'] else ""
                output_lines.append(f"  {entry['key']}{summary}")

            result_text = "\n".join(output_lines)
            return ToolResult(llm_content=result_text, return_display=result_text)

        except Exception as e:
            logger.exception("Notebook show failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class NotebookShowTool(BaseDeclarativeTool[NotebookShowParams]):
    """Display all saved keys and summaries"""

    def __init__(self):
        super().__init__(
            name="marm_notebook_show",
            display_name="MARM Notebook Show",
            description="Display all saved notebook keys and summaries.",
            kind=ToolKind.READ,
            parameters_model=NotebookShowParams,
            is_output_markdown=True,
            can_update_output=False
        )

    def create_invocation(self, params: NotebookShowParams) -> NotebookShowInvocation:
        return NotebookShowInvocation(params)


class NotebookDeleteParams(BaseModel):
    """Parameters for marm_notebook_delete"""
    name: str = Field(..., description="Name of notebook entry to delete")


class NotebookDeleteInvocation(BaseToolInvocation[NotebookDeleteParams, ToolResult]):
    """Delete notebook entry"""

    def get_description(self) -> str:
        return f"Deleting notebook entry: {self.params.name}"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Delete specific notebook entry"""
        try:
            db = get_shared_db()

            # Delete from notebook
            db.conn.execute("DELETE FROM notebook WHERE key = ?", (self.params.name,))
            # Remove from active instructions if present
            db.conn.execute("DELETE FROM active_instructions WHERE notebook_key = ?", (self.params.name,))
            db.conn.commit()

            # db.close() - using shared instance, don't close
            message = f"✓ Deleted notebook entry: '{self.params.name}'"
            return ToolResult(llm_content=message, return_display=message)

        except Exception as e:
            logger.exception("Notebook delete failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class NotebookDeleteTool(BaseDeclarativeTool[NotebookDeleteParams]):
    """Delete specific notebook entry"""

    def __init__(self):
        super().__init__(
            name="marm_notebook_delete",
            display_name="MARM Notebook Delete",
            description="Delete specific notebook entry permanently.",
            kind=ToolKind.WRITE,
            parameters_model=NotebookDeleteParams,
            is_output_markdown=False,
            can_update_output=False
        )

    def create_invocation(self, params: NotebookDeleteParams) -> NotebookDeleteInvocation:
        return NotebookDeleteInvocation(params)


class NotebookClearParams(BaseModel):
    """Parameters for marm_notebook_clear"""
    pass  # No parameters needed


class NotebookClearInvocation(BaseToolInvocation[NotebookClearParams, ToolResult]):
    """Clear active instructions"""

    def get_description(self) -> str:
        return "Clearing active instructions"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Clear the active instruction list"""
        try:
            db = get_shared_db()
            db.clear_active_instructions()
            # db.close() - using shared instance, don't close

            message = "✓ Cleared all active instructions"
            return ToolResult(llm_content=message, return_display=message)

        except Exception as e:
            logger.exception("Notebook clear failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class NotebookClearTool(BaseDeclarativeTool[NotebookClearParams]):
    """Clear active instruction list"""

    def __init__(self):
        super().__init__(
            name="marm_notebook_clear",
            display_name="MARM Notebook Clear",
            description="Clear the active instruction list (does not delete saved entries).",
            kind=ToolKind.WRITE,
            parameters_model=NotebookClearParams,
            is_output_markdown=False,
            can_update_output=False
        )

    def create_invocation(self, params: NotebookClearParams) -> NotebookClearInvocation:
        return NotebookClearInvocation(params)


class NotebookStatusParams(BaseModel):
    """Parameters for marm_notebook_status"""
    pass  # No parameters needed


class NotebookStatusInvocation(BaseToolInvocation[NotebookStatusParams, ToolResult]):
    """Show active instructions"""

    def get_description(self) -> str:
        return "Showing active instructions"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Show current active instruction list"""
        try:
            db = get_shared_db()
            active = db.get_active_instructions()
            # db.close() - using shared instance, don't close

            if not active:
                message = "📋 No active instructions"
                return ToolResult(llm_content=message, return_display=message)

            # Format output
            output_lines = [f"📋 Active instructions ({len(active)}):\n"]
            for key in active:
                output_lines.append(f"  ✓ {key}")

            result_text = "\n".join(output_lines)
            return ToolResult(llm_content=result_text, return_display=result_text)

        except Exception as e:
            logger.exception("Notebook status failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class NotebookStatusTool(BaseDeclarativeTool[NotebookStatusParams]):
    """Show current active instructions"""

    def __init__(self):
        super().__init__(
            name="marm_notebook_status",
            display_name="MARM Notebook Status",
            description="Show the current active instruction list.",
            kind=ToolKind.READ,
            parameters_model=NotebookStatusParams,
            is_output_markdown=True,
            can_update_output=False
        )

    def create_invocation(self, params: NotebookStatusParams) -> NotebookStatusInvocation:
        return NotebookStatusInvocation(params)


# ============================================================================
# 🚀 SESSION MANAGEMENT (1 tool)
# ============================================================================

class StartParams(BaseModel):
    """Parameters for marm_start"""
    pass  # No parameters needed - auto-runs on startup


class StartInvocation(BaseToolInvocation[StartParams, ToolResult]):
    """Activate MARM"""

    def get_description(self) -> str:
        return "Activating MARM memory & accuracy layers"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Activate MARM memory & accuracy layers"""
        try:
            # This is mostly informational - MARM is always active in CLI
            message = """✓ MARM activated. Ready to log context.

MARM is your memory architect and guardian of conversation continuity.
All conversations are automatically saved with semantic search capabilities.

Key features available:
- Smart memory recall across sessions
- Structured logging with sessions
- Notebook for reusable instructions
- Automatic context preservation

Type /help to see available commands, or just chat naturally - MARM tools are invoked automatically based on your needs."""

            return ToolResult(llm_content=message, return_display=message)

        except Exception as e:
            logger.exception("MARM start failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class StartTool(BaseDeclarativeTool[StartParams]):
    """Activate MARM memory & accuracy layers"""

    def __init__(self):
        super().__init__(
            name="marm_start",
            display_name="MARM Start",
            description="Activate MARM memory & accuracy layers (auto-runs on startup). Provides welcome message and feature overview.",
            kind=ToolKind.READ,
            parameters_model=StartParams,
            is_output_markdown=True,
            can_update_output=False
        )

    def create_invocation(self, params: StartParams) -> StartInvocation:
        return StartInvocation(params)


# ============================================================================
# ⚙️ SYSTEM UTILITIES (1 tool)
# ============================================================================

class SystemInfoParams(BaseModel):
    """Parameters for marm_system_info"""
    pass  # No parameters needed


class SystemInfoInvocation(BaseToolInvocation[SystemInfoParams, ToolResult]):
    """Get system info"""

    def get_description(self) -> str:
        return "Getting system information"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Comprehensive system info, health status, loaded docs"""
        try:
            db = get_shared_db()

            # Get database stats
            cursor = db.conn.execute("SELECT COUNT(*) FROM conversations")
            total_conversations = cursor.fetchone()[0]

            cursor = db.conn.execute("SELECT COUNT(*) FROM log_entries")
            total_logs = cursor.fetchone()[0]

            cursor = db.conn.execute("SELECT COUNT(*) FROM notebook")
            total_notebook = cursor.fetchone()[0]

            cursor = db.conn.execute("SELECT COUNT(*) FROM sessions")
            total_sessions = cursor.fetchone()[0]

            active_instructions = db.get_active_instructions()

            # db.close() - using shared instance, don't close

            # System info
            output_lines = [
                "⚙️ MARM CLI System Information\n",
                "**Platform:**",
                f"  OS: {platform.system()} {platform.release()}",
                f"  Python: {platform.python_version()}",
                f"  User: {os.getenv('USER') or os.getenv('USERNAME') or 'unknown'}",
                f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
                "**Database Statistics:**",
                f"  Total conversations: {total_conversations}",
                f"  Log entries: {total_logs}",
                f"  Notebook entries: {total_notebook}",
                f"  Sessions: {total_sessions}",
                f"  Active instructions: {len(active_instructions)}\n",
                "**MARM Status:**",
                "  ✓ Memory system: Active",
                "  ✓ Semantic search: Ready",
                "  ✓ Auto-logging: Enabled",
                "  ✓ Protocol: Loaded"
            ]

            result_text = "\n".join(output_lines)
            return ToolResult(llm_content=result_text, return_display=result_text)

        except Exception as e:
            logger.exception("System info failed")
            return ToolResult(llm_content=f"❌ Error: {str(e)}", return_display=f"❌ Failed: {str(e)}")


class SystemInfoTool(BaseDeclarativeTool[SystemInfoParams]):
    """Comprehensive system info"""

    def __init__(self):
        super().__init__(
            name="marm_system_info",
            display_name="MARM System Info",
            description="Show comprehensive system information, health status, database statistics, and loaded documentation.",
            kind=ToolKind.READ,
            parameters_model=SystemInfoParams,
            is_output_markdown=True,
            can_update_output=False
        )

    def create_invocation(self, params: SystemInfoParams) -> SystemInfoInvocation:
        return SystemInfoInvocation(params)


# ============================================================================
# EXPORT ALL TOOLS
# ============================================================================

def get_all_marm_tools() -> List[BaseDeclarativeTool]:
    """Get all 14 manual MARM tools"""
    return [
        # Memory Intelligence (1)
        SmartRecallTool(),
        # Logging System (4)
        LogSessionTool(),
        LogEntryTool(),
        LogShowTool(),
        LogDeleteTool(),
        # Reasoning (1)
        SummaryTool(),
        # Notebook (6)
        NotebookAddTool(),
        NotebookUseTool(),
        NotebookShowTool(),
        NotebookDeleteTool(),
        NotebookClearTool(),
        NotebookStatusTool(),
        # Session (1)
        StartTool(),
        # System (1)
        SystemInfoTool(),
    ]
