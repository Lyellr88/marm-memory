"""Read source directly off disk.

The search results already carry file_path and a line range, and this process
runs on the same machine as the code, so a round trip through the engine to get
text it would read from the same file buys nothing. Reading locally also means a
snippet can never disagree with what is on disk.
"""

from __future__ import annotations

import os
from typing import TextIO

MAX_LINES = 60

#: Longest physical line materialised from a source file. Bounding the line
#: COUNT is not enough: a minified or generated file is routinely one line of
#: several megabytes, so reading "one line" can still pull the whole file into
#: memory. 2,000 characters is far beyond any line a human wrote and well under
#: anything that costs.
MAX_LINE_CHARS = 2000

#: Total characters `read()` will scan for one snippet. The per-line bound caps
#: what is KEPT; draining the tail of an over-long line still had to walk it, so
#: a 40 MB minified file cost a 40 MB scan to return 2,000 characters of it. This
#: runs synchronously inside an async request, so that scan is the event loop's.
#: Running out stops the read and reports truncation rather than guessing.
MAX_SCAN_CHARS = 262144


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


def _bounded_line(
    fh: "TextIO", limit: int, budget: int
) -> "tuple[str, bool, int, bool]":
    """Read one physical line, materialising at most `limit` characters of it.

    Returns (text, over_long, scanned, complete). The line is consumed to its
    end so the caller's numbering stays correct, but only `limit` characters
    are kept.

    `complete` is False when `budget` ran out mid-line. The handle is then
    parked inside a physical line, so every later line number is unknowable and
    the caller has to stop: a short result is honest, lines numbered from the
    wrong place are not.

    `readline(limit)` returning a string with no trailing newline is ambiguous
    on its own: it means either a line longer than `limit`, or a final line with
    no newline at end of file. Draining is what distinguishes them -- if the
    drain reads nothing, it was the short final line.
    """
    piece = fh.readline(limit)
    if not piece or piece.endswith("\n"):
        return piece, False, len(piece), True
    scanned = len(piece)
    over_long = False
    while True:
        if scanned >= budget:
            return piece, True, scanned, False
        rest = fh.readline(limit)
        if not rest:
            break
        over_long = True
        scanned += len(rest)
        if rest.endswith("\n"):
            break
    return piece, over_long, scanned, True


def read(
    root_path: str, file_path: str, start: int, end: int, *, max_lines: int = MAX_LINES
) -> tuple[str, bool]:
    """Return (text, truncated). Line numbers are 1-based and inclusive."""
    full = _contained(root_path, file_path)
    if full is None:
        return "", False
    if start < 1:
        start = 1
    if not end or end < start:
        end = start
    # Bounded on both axes, because each one alone leaves a way to read an
    # arbitrarily large amount of a file:
    #   * `readlines()` materialises every line before `max_lines` applies, so a
    #     40 MB generated file cost 40 MB to return 60 lines of it.
    #   * iterating the handle fixes that but bounds only the line COUNT, and a
    #     minified file is routinely ONE line of several megabytes -- so even
    #     `start=1, end=1` pulled the whole file in as a single string.
    # Reading line-by-line with a per-line character bound, and stopping as soon
    # as the requested range is satisfied, makes the cost a function of the
    # range rather than of the file.
    chunk: list[str] = []
    truncated = False
    number = 0
    budget = MAX_SCAN_CHARS
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            while True:
                line, over_long, scanned, complete = _bounded_line(
                    fh, MAX_LINE_CHARS, budget
                )
                budget -= scanned
                if not line:
                    break
                number += 1
                if not complete:
                    # Parked mid-line with no budget left. Keep this line if it
                    # was wanted -- it is the only one whose number is still
                    # known -- and stop, because the next newline was never
                    # reached and everything after it would be misnumbered.
                    truncated = True
                    if start <= number <= end and len(chunk) < max_lines:
                        chunk.append(line.rstrip("\n") + "\n")
                    break
                if number < start:
                    continue
                if number > end:
                    break
                if len(chunk) >= max_lines:
                    truncated = True
                    break
                if over_long:
                    # Say so rather than returning a silently clipped line as if
                    # it were the whole thing.
                    truncated = True
                    line = line.rstrip("\n") + "\n"
                chunk.append(line)
                if budget <= 0:
                    truncated = True
                    break
    except (OSError, ValueError):
        return "", False
    return "".join(chunk).rstrip("\n"), truncated


def dedent_block(text: str) -> str:
    """Strip the common leading indentation so a nested method reads cleanly."""
    lines = text.splitlines()
    bodies = [ln for ln in lines if ln.strip()]
    if not bodies:
        return text
    pad = min(len(ln) - len(ln.lstrip()) for ln in bodies)
    return "\n".join(ln[pad:] if len(ln) >= pad else ln for ln in lines)
