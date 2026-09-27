"""A fingerprint of the code a memory was linked to."""

import hashlib
import itertools
import textwrap
from pathlib import Path
from typing import Optional


def span_hash(
    root: str | Path, file_path: Optional[str], start: object, end: object
) -> Optional[str]:
    """Hash of lines start..end of a file inside root, or None if unreadable.

    Trailing whitespace, blank lines and the span's common indentation are
    ignored, and line numbers are not hashed, so code that only moved or was
    re-indented keeps its fingerprint; relative indentation still counts.
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
        with target.open(encoding="utf-8", errors="replace") as handle:
            lines = list(itertools.islice(handle, start - 1, end))
    except OSError:
        return None
    if len(lines) < end - start + 1:
        return None
    kept = [line.rstrip() for line in lines if line.strip()]
    body = textwrap.dedent("\n".join(kept))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
