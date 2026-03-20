"""Tool registry for managing and discovering MARM tools"""
from typing import Dict, List, Optional, Any
import logging

from .tools import BaseDeclarativeTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central registry for all MARM tools

    Manages tool registration, lookup, and function declarations for LLM
    """

    def __init__(self):
        self._tools: Dict[str, BaseDeclarativeTool] = {}

    def register(self, tool: BaseDeclarativeTool) -> None:
        """
        Register a tool in the registry

        Args:
            tool: Tool instance to register

        Raises:
            ValueError: If tool with same name already registered
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")

        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name} ({tool.kind.value})")

    def unregister(self, tool_name: str) -> bool:
        """
        Unregister a tool

        Args:
            tool_name: Name of tool to unregister

        Returns:
            True if tool was unregistered, False if not found
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            logger.info(f"Unregistered tool: {tool_name}")
            return True
        return False

    def get_tool(self, tool_name: str) -> Optional[BaseDeclarativeTool]:
        """
        Get tool by name

        Args:
            tool_name: Name of tool to retrieve

        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(tool_name)

    def get_all_tools(self) -> List[BaseDeclarativeTool]:
        """
        Get all registered tools

        Returns:
            List of all tool instances
        """
        return list(self._tools.values())

    def get_all_tool_names(self) -> List[str]:
        """
        Get names of all registered tools

        Returns:
            List of tool names
        """
        return list(self._tools.keys())

    def get_function_declarations(self) -> List[Dict[str, Any]]:
        """
        Get function declarations for all tools

        For sending to LLM function calling API

        Returns:
            List of function declaration dicts
        """
        return [tool.get_function_declaration() for tool in self._tools.values()]

    def get_function_declarations_filtered(self, tool_names: List[str]) -> List[Dict[str, Any]]:
        """
        Get function declarations for specific tools

        Args:
            tool_names: List of tool names to include

        Returns:
            List of function declarations for requested tools
        """
        declarations = []
        for name in tool_names:
            tool = self._tools.get(name)
            if tool:
                declarations.append(tool.get_function_declaration())
            else:
                logger.warning(f"Tool not found for declaration: {name}")

        return declarations

    def get_tools_by_kind(self, kind: str) -> List[BaseDeclarativeTool]:
        """
        Get all tools of a specific kind

        Args:
            kind: Tool kind (read, write, edit, delete, etc.)

        Returns:
            List of tools matching the kind
        """
        return [tool for tool in self._tools.values() if tool.kind.value == kind]

    def has_tool(self, tool_name: str) -> bool:
        """
        Check if tool is registered

        Args:
            tool_name: Name to check

        Returns:
            True if tool exists
        """
        return tool_name in self._tools

    def clear(self) -> None:
        """Clear all registered tools"""
        self._tools.clear()
        logger.info("Cleared all tools from registry")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get registry statistics

        Returns:
            Dict with tool counts by kind
        """
        stats = {
            "total": len(self._tools),
            "by_kind": {}
        }

        for tool in self._tools.values():
            kind = tool.kind.value
            stats["by_kind"][kind] = stats["by_kind"].get(kind, 0) + 1

        return stats

    def __len__(self):
        """Number of registered tools"""
        return len(self._tools)

    def __contains__(self, tool_name: str):
        """Check if tool is registered (for 'in' operator)"""
        return tool_name in self._tools

    def __repr__(self):
        return f"<ToolRegistry tools={len(self._tools)}>"


# Global tool registry instance
_global_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """
    Get global tool registry instance (singleton)

    Returns:
        ToolRegistry instance
    """
    global _global_registry

    if _global_registry is None:
        _global_registry = ToolRegistry()

    return _global_registry


def register_tool(tool: BaseDeclarativeTool) -> None:
    """
    Register tool in global registry

    Args:
        tool: Tool to register
    """
    registry = get_tool_registry()
    registry.register(tool)
