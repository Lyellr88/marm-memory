#!/usr/bin/env python3
"""Join hard-wrapped paragraph lines in Markdown back into single lines.

Usage:
    python scripts/unwrap-md.py docs/current/some-spec.md
    python scripts/unwrap-md.py --dry-run docs/current/*.md
    python scripts/unwrap-md.py docs/current            # recurses for *.md

A bare `re.sub(r'(?<!\n)\n(?!\n)', ' ', text)` destroys Markdown: it flattens
every table into one row, joins list items together, merges headings into the
following sentence, and silently eats trailing-two-space hard breaks, which
this repo's .claude/rules files use deliberately. Only lines that are plain
prose on both sides are joined here.
"""

import argparse
import re
import sys
from pathlib import Path

FENCE = re.compile(r"^\s*(```|~~~)")

# Lines that start a construct where a newline is significant. Joining one of
# these into a neighbour changes how it renders.
BLOCK = re.compile(
    r"""^\s*(
      \#{1,6}\s                    # heading
    | [-*+][ \t]                   # bullet
    | \d+[.)][ \t]                 # ordered item
    | >                            # blockquote
    | \|                           # table row
    | (-{3,}|\*{3,}|_{3,})\s*$     # thematic break
    | <                            # html block
    | \[[^\]]+\]:                  # link reference definition
    | \|?[:-]{3,}                  # table delimiter row
    )""",
    re.VERBOSE,
)

# A block that owns the wrapped lines beneath it, so those get pulled up into it.
# Headings, table rows, and rules do not: nothing following them is a
# continuation, and joining would move text into the wrong construct.
ABSORBING = re.compile(r"^\s*([-*+][ \t]|\d+[.)][ \t]|>)")


def _is_prose(line: str) -> bool:
    if not line.strip():
        return False
    if line.startswith(("    ", "\t")):
        # Indented code block, or a list continuation. Either way, leave it.
        return False
    return not BLOCK.match(line)


def _hard_break(line: str) -> bool:
    """Trailing two spaces or a backslash is an intentional line break."""
    return line.endswith("  ") or line.rstrip().endswith("\\")


# How far under `width` a line can stop and still count as full. Wrapping done by
# hand or by a model is not perfectly greedy, so an exact "would the next word
# have fit" test misses real wraps that stopped a few characters early.
SLACK = 10


def _was_wrapped(prev: str, nxt: str, width: int) -> bool:
    """Whether `prev` ran out of room, rather than ending where the author chose.

    This is what separates a wrapped paragraph from consecutive short statements.
    Two independent signals, either of which is enough:

    - `prev` is near full, so a wrapper broke it.
    - the next word would not have fit. This catches a line that stopped well
      short because what followed was one long unbreakable token, such as a
      backticked path, which the fullness test alone reads as a deliberate break.

    Without both, either deliberate short statements get merged (no fullness
    floor) or real wraps before a long token stay broken (no fit test).
    """
    if len(prev) >= width - SLACK:
        return True
    word = nxt.strip().split(" ", 1)[0]
    return len(prev) + 1 + len(word) > width


def _starts_own_line(line: str) -> bool:
    """A bold-led line opens its own line and is never joined into the one above.

    This repo's rules files list one statement per line with no bullet marker and
    no trailing hard break (`**Cut Losses Quickly** - Good instincts about ...`).
    Those read as prose on both sides, so without this the whole block collapses
    into one paragraph. A bold-led line still absorbs its own wrapped
    continuations, which is what makes `**Note.** wrapped text...` join correctly.
    """
    return line.lstrip().startswith("**")


def _split_frontmatter(text: str) -> tuple[str, str]:
    """YAML frontmatter is `key: value` lines that read as prose. Pass it through."""
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    cut = end + len("\n---\n")
    return text[:cut], text[cut:]


def unwrap(text: str, width: int = 80) -> str:
    front, body = _split_frontmatter(text)
    out: list[str] = []
    buf: str | None = None
    in_fence = False

    for line in body.split("\n"):
        if FENCE.match(line):
            if buf is not None:
                out.append(buf)
                buf = None
            in_fence = not in_fence
            out.append(line)
            continue

        if in_fence or not _is_prose(line):
            if buf is not None:
                out.append(buf)
                buf = None
            if not in_fence and ABSORBING.match(line) and not _hard_break(line):
                # Stays open so its own wrapped continuation lines join into it.
                # Indent is kept verbatim, which is what holds nested lists together.
                buf = line.rstrip()
            else:
                out.append(line)
            continue

        stripped = line.strip()
        if buf is not None and (
            _starts_own_line(line) or not _was_wrapped(buf, stripped, width)
        ):
            out.append(buf)
            buf = None
        # rstrip, not strip, when opening: an indented prose block keeps its indent.
        buf = line.rstrip() if buf is None else f"{buf} {stripped}"
        if _hard_break(line):
            out.append(buf + "  " if line.endswith("  ") else buf)
            buf = None

    if buf is not None:
        out.append(buf)
    return front + "\n".join(out)


def _targets(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        found.extend(sorted(p.rglob("*.md")) if p.is_dir() else [p])
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", help="Markdown files or directories")
    ap.add_argument("--dry-run", action="store_true", help="report, do not write")
    ap.add_argument(
        "--width", type=int, default=80, help="wrap column the file was written at"
    )
    args = ap.parse_args()

    changed = 0
    for path in _targets(args.paths):
        if not path.is_file():
            print(f"skip (not a file): {path}")
            continue
        original = path.read_text(encoding="utf-8")
        fixed = unwrap(original, args.width)
        if fixed == original:
            continue
        changed += 1
        before = len(original.splitlines())
        after = len(fixed.splitlines())
        print(
            f"{'would fix' if args.dry_run else 'fixed'}: {path} ({before} -> {after} lines)"
        )
        if not args.dry_run:
            path.write_text(fixed, encoding="utf-8", newline="\n")

    print(f"{changed} file(s) {'would change' if args.dry_run else 'changed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
