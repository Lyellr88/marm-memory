"""Shared FastMCP instance for the STDIO transport.

Lives in its own module so tool-registration modules (e.g.
services/stdio_graph_tools.py) can import `mcp` without a circular
dependency on server_stdio.py, which itself imports those modules to
trigger `@mcp.tool()` registration at import time.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("MARM MCP Server")
