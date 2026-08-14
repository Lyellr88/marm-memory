"""Automation event handlers for MARM MCP Server."""

from ..core.events import events
from ..core.memory import memory


async def auto_classify_content(data: dict) -> None:
    """Auto-classify log entries"""
    content = data.get("content", "")
    context_type = await memory.auto_classify_content(content)
    print(f"Auto-classified '{content[:50]}...' as '{context_type}'")


async def update_knowledge_index(data: dict) -> None:
    """Update search index when notebook entries added"""
    print(f"Knowledge index updated for: {data.get('name')}")


def register_event_handlers() -> None:
    """Register all automation event handlers."""
    events.on("log_entry_created", auto_classify_content)
    events.on("notebook_entry_added", update_knowledge_index)
    print("OK: Automation event handlers registered.")
