"""A fingerprint of the code a memory was linked to."""

import hashlib
from pathlib import Path
from typing import Optional


def span_hash(
    root: str | Path, file_path: Optional[str], start: object, end: object
) -> Optional[str]:
    """Hash of lines start..end of a file inside root, or None if unreadable.

    Trailing whitespace and blank lines are ignored so a reformat alone does
    not read as a change; line numbers are not hashed, so code that only moved
    keeps its fingerprint.
    """
    if not file_path or not isinstance(start, int) or not isinstance(end, int):
        return None
    if start < 1 or end < start:
        return None
    try:
        base = Path(root).resolve()
        target = (base / file_path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            return None
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if end > len(lines):
        return None
    body = "\n".join(line.rstrip() for line in lines[start - 1 : end] if line.strip())
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
