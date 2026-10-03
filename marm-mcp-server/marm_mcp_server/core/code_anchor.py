"""A fingerprint of the code a memory was linked to."""

import hashlib
import itertools
import os
import textwrap
from pathlib import Path
from typing import Optional

#: Bumped whenever the hashing changes, so an old fingerprint is replaced
#: rather than read as changed code.
ANCHOR_VERSION = "2"


def _state(st: os.stat_result) -> tuple[int, int, int, int]:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def span_hash(
    root: str | Path,
    file_path: Optional[str],
    start: object,
    end: object,
    not_after: Optional[float] = None,
) -> Optional[str]:
    """Hash of lines start..end of a file inside root, or None if unreadable.

    Trailing whitespace, blank lines and the span's common indentation are
    ignored, and line numbers are not hashed, so code that only moved or was
    re-indented keeps its fingerprint; relative indentation still counts. It
    is a practical source-change signal, not semantic equivalence.

    None when the file was modified after `not_after` (a POSIX time), or
    replaced or modified while it was read: the line numbers came from an
    index that may not have seen that version.
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
            before = os.fstat(handle.fileno())
            if not_after is not None and before.st_mtime > not_after:
                return None
            lines = list(itertools.islice(handle, start - 1, end))
        # The fingerprint is of the file the index saw only if it is still
        # that file, unchanged, once read.
        if _state(target.stat()) != _state(before):
            return None
    except OSError:
        return None
    if len(lines) < end - start + 1:
        return None
    kept = [line.rstrip() for line in lines if line.strip()]
    body = textwrap.dedent("\n".join(kept))
    return f"{ANCHOR_VERSION}:{hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}"
