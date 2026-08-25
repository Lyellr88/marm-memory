#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
from collections import Counter

BASELINE = 0

TIMEOUT_SECONDS = 600

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "marm-mcp-server"

TARGETS = ["marm_mcp_server/", "marm_graph/"]

_ERROR_LINE = re.compile(
    r"^(?P<path>.*?\.py):\d+: error: .*?(?:\[(?P<code>[a-z-]+)\])?$"
)
_IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"


def run_mypy() -> tuple[str, int]:
    print(f"running mypy on {' '.join(TARGETS)}", file=sys.stderr, flush=True)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "mypy", *TARGETS],
            cwd=PACKAGE_DIR,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as expired:
        partial = (expired.stdout or "") + (expired.stderr or "")
        return (
            f"{partial}\nmypy did not finish within {TIMEOUT_SECONDS}s and was killed.",
            2,
        )
    return proc.stdout + proc.stderr, proc.returncode


def _relative(path: str) -> str:
    """mypy's path, normalized to forward slashes.

    Keyed on the full relative path rather than the basename: nine basenames
    repeat across subpackages (memory.py, concepts.py, models.py, cli.py, ...),
    so grouping on the name alone merged distinct files into one count.
    """
    return path.replace("\\", "/")


def parse(output: str) -> tuple[Counter, Counter, int]:
    by_file: Counter = Counter()
    by_code: Counter = Counter()
    total = 0
    for line in output.splitlines():
        match = _ERROR_LINE.match(line.strip())
        if not match:
            continue
        total += 1
        by_file[_relative(match.group("path"))] += 1
        by_code[match.group("code") or "uncoded"] += 1
    return by_file, by_code, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw", action="store_true", help="print full mypy output and skip the gate"
    )
    args = parser.parse_args()

    output, returncode = run_mypy()

    if args.raw:
        print(output.rstrip())
        return 0

    by_file, by_code, total = parse(output)

    if returncode >= 2 or (returncode != 0 and total == 0):
        print(
            f"mypy failed without reporting diagnostics (exit {returncode}).",
            file=sys.stderr,
        )
        print(output.rstrip() or "(no output)", file=sys.stderr)
        return 2

    unresolved = list(
        dict.fromkeys(
            line.strip()
            for line in output.splitlines()
            if "is not installed" in line or "Cannot find implementation" in line
        )
    )
    if unresolved:
        print("mypy could not resolve the project's dependencies.", file=sys.stderr)
        for line in unresolved:
            print(f"  {line}", file=sys.stderr)
        print(
            "Install them first:  pip install -r marm-mcp-server/requirements.txt",
            file=sys.stderr,
        )
        return 2

    print(f"mypy: {' '.join(TARGETS)}  ({total} errors, baseline {BASELINE})\n")

    if by_code:
        print("by kind")
        for code, count in by_code.most_common():
            print(f"  {count:5d}  {code}")

    if by_file:
        print("\nby file")
        for name, count in by_file.most_common():
            print(f"  {count:5d}  {name}")
        checked = {
            _relative(str(path.relative_to(PACKAGE_DIR)))
            for target in TARGETS
            for path in (PACKAGE_DIR / target).rglob("*.py")
            if "__pycache__" not in path.parts
        }
        print(f"\nclean: {len(checked - set(by_file))} of {len(checked)} files")

    print()
    if total > BASELINE:
        message = (
            f"type errors increased: {total} > baseline {BASELINE}. "
            f"Fix the new errors, or run with --raw to see them in full."
        )
        print(f"::error::{message}" if _IN_CI else f"FAIL  {message}", file=sys.stderr)
        return 1

    if total < BASELINE:
        message = (
            f"type errors dropped to {total} (baseline {BASELINE}). "
            f"Lower BASELINE in scripts/typecheck.py to lock the improvement in."
        )
        print(f"::warning::{message}" if _IN_CI else f"NOTE  {message}")
        return 0

    print(f"OK  {total} errors, unchanged from baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
