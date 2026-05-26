"""Utility helper functions for MARM MCP Server."""

from pathlib import Path

async def read_protocol_file():
    """
    Load and return the contents of the project's PROTOCOL.md file.
    
    Returns:
        str: The full text of PROTOCOL.md if found; a warning string "⚠️ PROTOCOL.md file not found. Please ensure documentation is properly loaded." if the file does not exist; or an error string formatted as "❌ Error reading PROTOCOL.md: {error}" if an exception occurs while reading.
    """
    try:
        protocol_path = Path(__file__).parent.parent.parent / "marm-docs" / "PROTOCOL.md"
        if protocol_path.exists():
            with open(protocol_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return "⚠️ PROTOCOL.md file not found. Please ensure documentation is properly loaded."
    except Exception as e:
        return f"❌ Error reading PROTOCOL.md: {str(e)}"
