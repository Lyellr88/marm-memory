"""Utility helper functions for MARM MCP Server."""

from pathlib import Path

# The single home for MARM's shipped documentation. It lives inside the package
# so one path works for every install type -- pip wheel, Docker image, and dev
# checkout alike. Both this module and services/documentation.py resolve docs
# through DOCS_DIR; do not reintroduce a second copy outside the package, since
# a copy at the repo root is not included in the wheel and silently resolves to
# nothing once installed.
DOCS_DIR = Path(__file__).resolve().parent.parent / "resources" / "marm-docs"


def docs_dir() -> Path | None:
    """Return the packaged marm-docs directory, or None if it is missing."""
    return DOCS_DIR if DOCS_DIR.is_dir() else None


async def read_protocol_file():
    """Read the PROTOCOL.md file and return its content."""
    try:
        protocol_path = DOCS_DIR / "PROTOCOL.md"
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
        lite_path = DOCS_DIR / "PROTOCOL-LITE.md"
        if lite_path.exists():
            with open(lite_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            return ""  # silent — lite protocol is optional
    except Exception:
        return ""
