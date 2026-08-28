#!/usr/bin/env python3
"""Print the CHANGELOG section for a version, without its <details> wrapper."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section_for(version: str, text: str) -> str | None:
    version = version.lstrip("v")
    for block in re.findall(r"<details>\s*(.*?)\s*</details>", text, re.DOTALL):
        summary = re.match(r"<summary>(.*?)</summary>", block, re.DOTALL)
        if not summary or f"(v{version})" not in summary.group(1):
            continue
        return block[summary.end() :].strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    args = parser.parse_args()

    body = section_for(args.version, CHANGELOG.read_text(encoding="utf-8"))
    if body is None:
        print(f"No CHANGELOG entry for {args.version}", file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
