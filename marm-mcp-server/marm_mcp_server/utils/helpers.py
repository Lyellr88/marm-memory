"""Utility helper functions for MARM MCP Server."""

from pathlib import Path


async def read_protocol_file():
    """Read the PROTOCOL.md file and return its content."""
    try:
        protocol_path = (
            Path(__file__).parent.parent.parent / "marm-docs" / "PROTOCOL.md"
        )
        if protocol_path.exists():
            with open(protocol_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            return "PROTOCOL.md file not found. Please ensure documentation is properly loaded."
    except Exception as e:
        return f"Error reading PROTOCOL.md: {e!s}"


async def read_protocol_lite_file():
    """Read the PROTOCOL-LITE.md file and return its content."""
    try:
        lite_path = (
            Path(__file__).parent.parent.parent / "marm-docs" / "PROTOCOL-LITE.md"
        )
        if lite_path.exists():
            with open(lite_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            return ""  # silent — lite protocol is optional
    except Exception:
        return ""
