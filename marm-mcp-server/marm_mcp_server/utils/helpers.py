from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "resources" / "marm-docs"


def docs_dir() -> Path | None:
    """Return the packaged marm-docs directory, or None if it is missing."""
    return DOCS_DIR if DOCS_DIR.is_dir() else None


async def read_protocol_file() -> str:
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


async def read_protocol_lite_file() -> str:
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
