"""MARM memory and accuracy layer - Direct integration"""
from .database import MARMDatabase
from .semantic import SemanticSearch
from .protocol import ProtocolInjector
from .tools import BaseDeclarativeTool, BaseToolInvocation, ToolKind, ToolState
from .tool_registry import ToolRegistry, get_tool_registry, register_tool
from .tool_error import ToolError, ToolResult, ToolErrorType
from .tool_schema import SchemaGenerator, generate_function_declaration
from .ollama_client import OllamaClient, Message
from .marm_tools import get_all_marm_tools
from .automation import AutomationManager, ContextualLogger, SmartRefreshTimer, ContextBridgeDetector

__all__ = [
    # Core infrastructure
    'MARMDatabase',
    'SemanticSearch',
    'ProtocolInjector',
    # Tool system
    'BaseDeclarativeTool',
    'BaseToolInvocation',
    'ToolKind',
    'ToolState',
    'ToolRegistry',
    'get_tool_registry',
    'register_tool',
    'ToolError',
    'ToolResult',
    'ToolErrorType',
    'SchemaGenerator',
    'generate_function_declaration',
    # Ollama integration
    'OllamaClient',
    'Message',
    # MARM Tools
    'get_all_marm_tools',
    # Automation
    'AutomationManager',
    'ContextualLogger',
    'SmartRefreshTimer',
    'ContextBridgeDetector',
]
