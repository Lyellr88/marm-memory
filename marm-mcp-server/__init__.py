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
Version: 2.2.5
"""

__version__ = "2.2.5"
__author__ = "Lyell"
__email__ = "lyell@marmsystems.com"

from .server import create_server, main

__all__ = ["create_server", "main", "__version__"]