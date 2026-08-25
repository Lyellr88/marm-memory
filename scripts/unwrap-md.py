#!/usr/bin/env python3

import argparse
import re
import sys
from pathlib import Path

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


BLOCK = re.compile(
    r"""^\s*(
      \#{1,6}\s
    | [-*+][ \t]
    | \d+[.)][ \t]
    | >
    | \|
    | <
    | \[[^\]]+\]:
    | \|?[:-]{3,}
    )""",
    re.VERBOSE,
)

THEMATIC = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")

ABSORBING = re.compile(r"^\s*([-*+][ \t]|\d+[.)][ \t]|>)")


def _is_prose(line: str) -> bool:
    if not line.strip():
        return False
    if line.startswith(("    ", "\t")):
        return False
    return not BLOCK.match(line) and not THEMATIC.match(line)


def _hard_break(line: str) -> bool:
    """Trailing two spaces or a backslash is an intentional line break."""
    return line.endswith("  ") or line.rstrip().endswith("\\")


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


def _closes(opening: str, candidate: str, rest: str) -> bool:
    """A fence closes only on its own marker, at its own length or longer, and bare.

    An info string is allowed when opening a fence and not when closing one, so a
    ```bash line inside a ```markdown block is content rather than the end of it.
    Without the bare check that inner line closed the outer block and the rest of it
    was treated as prose.
    """
    return (
        candidate[0] == opening[0]
        and len(candidate) >= len(opening)
        and not rest.strip()
    )


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
    open_fence: str | None = None

    for line in body.split("\n"):
        fence = FENCE.match(line)
        if fence and (
            open_fence is None
            or _closes(open_fence, fence.group(1), line[fence.end(1) :])
        ):
            if buf is not None:
                out.append(buf)
                buf = None
            open_fence = None if open_fence else fence.group(1)
            out.append(line)
            continue

        in_fence = open_fence is not None
        if in_fence or not _is_prose(line):
            if buf is not None:
                out.append(buf)
                buf = None
            if (
                not in_fence
                and ABSORBING.match(line)
                and not THEMATIC.match(line)
                and not _hard_break(line)
            ):
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

    if args.width <= SLACK * 2:
        ap.error(f"--width must be greater than {SLACK * 2}, got {args.width}")

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
