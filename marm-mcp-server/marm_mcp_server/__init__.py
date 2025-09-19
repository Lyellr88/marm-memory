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

Author: Lyell - MARM Systems
Version: 2.2.4
"""

__version__ = "2.2.4"
__author__ = "Lyell"
__email__ = "lyell@marmsystems.com"

from .server import main

__all__ = ["main", "__version__"]