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


def _finish_line(fh: "TextIO", limit: int, budget: int) -> "tuple[bool, int, bool]":
    """Consume the rest of the current physical line, keeping none of it.

    Returns (over_long, scanned, complete). Called only when the caller still
    needs the lines AFTER this one, because that is the only reason to walk a
    line whose content is already decided.

    `complete` is False when `budget` ran out mid-line. The handle is then
    parked inside a physical line, so every later line number is unknowable and
    the caller has to stop: a short result is honest, lines numbered from the
    wrong place are not.
    """
    scanned = 0
    over_long = False
    while True:
        if scanned >= budget:
            return True, scanned, False
        rest = fh.readline(limit)
        if not rest:
            return over_long, scanned, True
        over_long = True
        scanned += len(rest)
        if rest.endswith("\n"):
            return over_long, scanned, True


def _was_clipped(fh: "TextIO") -> bool:
    """Did the line just read continue past the bound, or end the file?

    `readline(limit)` returning text with no trailing newline is ambiguous: it
    means either a line longer than `limit`, or a final line with no newline at
    EOF. One character settles it, which is the whole cost -- there is no reason
    to walk to the next newline when nothing after this line is wanted.
    """
    return bool(fh.read(1))


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
    # Bounded on every axis, because each one alone leaves a way to read an
    # arbitrary amount of a file:
    #   * `readlines()` materialises every line before `max_lines` applies.
    #   * iterating bounds the line COUNT, and a minified file is routinely ONE
    #     line of several megabytes.
    #   * bounding the line LENGTH caps what is kept, but walking to the next
    #     newline still costs the whole line.
    # So: keep at most MAX_LINE_CHARS, walk at most MAX_SCAN_CHARS in total, and
    # never walk a line at all once nothing after it is wanted.
    chunk: list[str] = []
    truncated = False
    number = 0
    budget = MAX_SCAN_CHARS
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            while True:
                piece = fh.readline(MAX_LINE_CHARS)
                if not piece:
                    break
                ended = piece.endswith("\n")
                number += 1
                if number > end:
                    break
                if number < start:
                    # Not wanted, but the rest of it has to be consumed or the
                    # next line number would be wrong.
                    if not ended:
                        _, scanned, complete = _finish_line(fh, MAX_LINE_CHARS, budget)
                        budget -= scanned
                        if not complete:
                            truncated = True
                            break
                    continue
                if len(chunk) >= max_lines:
                    truncated = True
                    break
                if not ended:
                    if number == end or len(chunk) + 1 >= max_lines:
                        # Nothing after this line is wanted, so do not walk it.
                        if _was_clipped(fh):
                            truncated = True
                        chunk.append(piece.rstrip("\n") + "\n")
                        break
                    over_long, scanned, complete = _finish_line(
                        fh, MAX_LINE_CHARS, budget
                    )
                    budget -= scanned
                    if not complete:
                        truncated = True
                        chunk.append(piece.rstrip("\n") + "\n")
                        break
                    if over_long:
                        # Say so rather than returning a silently clipped line
                        # as if it were the whole thing.
                        truncated = True
                    piece = piece.rstrip("\n") + "\n"
                chunk.append(piece)
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
