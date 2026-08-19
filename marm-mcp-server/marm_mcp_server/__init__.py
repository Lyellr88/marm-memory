"""
MARM MCP Server - Universal Memory Intelligence for AI Agents

MARM (Memory Accurate Response Mode) is a production-ready Universal MCP Server
that provides advanced AI memory capabilities, semantic search, and intelligent
context management for Claude and other AI agents.

Features:
- Universal MCP Protocol compliance
- Semantic search with sentence transformers
- Intelligent memory management
- FastAPI-based architecture
- Docker deployment ready
- Production-grade performance

Author: Ryan Lyell - marm-memory
Version: 2.39.4
"""

from typing import Any

__version__ = "2.39.4"
__author__ = "Ryan Lyell"
__email__ = "ryanlyell@marmemory.com"

__all__ = ["__version__", "create_server", "main"]


def __getattr__(name: str) -> Any:
    """Lazy-load HTTP server exports without side effects during STDIO imports."""
    if name == "create_server":
        from .server import create_server

        return create_server
    if name == "main":
        from .cli import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
