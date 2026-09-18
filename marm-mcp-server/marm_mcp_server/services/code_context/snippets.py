"""Read source directly off disk.

The search results already carry file_path and a line range, and this process
runs on the same machine as the code, so a round trip through the engine to get
text it would read from the same file buys nothing. Reading locally also means a
snippet can never disagree with what is on disk.
"""

from __future__ import annotations

import os

MAX_LINES = 60


def _contained(root_path: str, file_path: str) -> "str | None":
    """Resolve `file_path` under `root_path`, or None if it escapes.

    `os.path.join` returns the second argument unchanged when it is absolute, and
    does nothing about `..` or a symlink pointing out of the tree. The text this
    reads is handed back to the MCP caller, so the path has to be checked rather
    than trusted -- the engine indexes the repository, but nothing here re-derives
    that the row it returned still names a file inside it.
    """
    try:
        root = os.path.realpath(root_path)
        full = os.path.realpath(os.path.join(root, file_path))
    except (OSError, ValueError):
        return None
    if full == root or full.startswith(root + os.sep):
        return full
    return None


def read(
    root_path: str, file_path: str, start: int, end: int, *, max_lines: int = MAX_LINES
) -> tuple[str, bool]:
    """Return (text, truncated). Line numbers are 1-based and inclusive."""
    full = _contained(root_path, file_path)
    if full is None:
        return "", False
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except (OSError, ValueError):
        return "", False
    if start < 1:
        start = 1
    end = min(end if end and end >= start else start, len(lines))
    chunk = lines[start - 1 : end]
    truncated = len(chunk) > max_lines
    if truncated:
        chunk = chunk[:max_lines]
    return "".join(chunk).rstrip("\n"), truncated


def dedent_block(text: str) -> str:
    """Strip the common leading indentation so a nested method reads cleanly."""
    lines = text.splitlines()
    bodies = [ln for ln in lines if ln.strip()]
    if not bodies:
        return text
    pad = min(len(ln) - len(ln.lstrip()) for ln in bodies)
    return "\n".join(ln[pad:] if len(ln) >= pad else ln for ln in lines)
