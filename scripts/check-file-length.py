#!/usr/bin/env python3

import argparse
import sys
from collections import defaultdict
from pathlib import Path

CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
GRAY = "\033[90m"
RESET = "\033[0m"

ROOT = Path(__file__).parent.parent
SCAN_DIRS = [
    ("marm-mcp-server/marm_mcp_server", ROOT / "marm-mcp-server" / "marm_mcp_server"),
    ("marm-mcp-server/marm_graph", ROOT / "marm-mcp-server" / "marm_graph"),
    (
        "marm-console/artifacts/marm-console/src",
        ROOT / "marm-console" / "artifacts" / "marm-console" / "src",
    ),
]
TEST_DIRS = [
    ("marm-mcp-server/tests", ROOT / "marm-mcp-server" / "tests"),
    ("marm-console/tests", ROOT / "marm-console" / "tests"),
]
EXTENSIONS = {".py", ".toml", ".md", ".txt", ".json", ".ts", ".tsx", ".css"}

GENERATED_DIRS = {"models", "static", "__pycache__"}
EXCLUDED_NAMES = {"README.md"}


def is_generated(path: Path, base: Path) -> bool:
    if path.name in EXCLUDED_NAMES:
        return True
    return any(part in GENERATED_DIRS for part in path.relative_to(base).parts[:-1])


def line_count(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Check file line lengths.")
    parser.add_argument(
        "--threshold",
        "-t",
        type=int,
        default=400,
        help="Minimum line count to report (default: 400)",
    )
    parser.add_argument(
        "--versions",
        "-v",
        action="store_true",
        help="Also run find-versions after the check",
    )
    parser.add_argument(
        "--tests",
        action="store_true",
        help="Also scan test folders (marm-mcp-server/tests)",
    )
    args = parser.parse_args()

    threshold = args.threshold
    print(f"{CYAN}=== File Length Check (>{threshold} lines) ==={RESET}\n")

    scan_dirs = SCAN_DIRS + TEST_DIRS if args.tests else SCAN_DIRS

    results: dict[str, list[tuple[int, str, str]]] = defaultdict(list)

    for label, base in scan_dirs:
        if not base.exists():
            print(f"{YELLOW}Warning: {label}/ not found, skipping{RESET}")
            continue

        files = [
            f
            for f in base.rglob("*")
            if f.is_file() and f.suffix in EXTENSIONS and not is_generated(f, base)
        ]
        print(f"{GRAY}Scanning {len(files)} files in {label}/{RESET}")

        for f in files:
            count = line_count(f)
            if count > threshold:
                folder = str(f.parent)
                results[folder].append((count, f.name, str(f)))

    if not results:
        print(f"{GREEN}✓ No files over {threshold} lines found{RESET}\n")
    else:
        total = 0
        for folder in sorted(results):
            print(f"{CYAN}{folder}/{RESET}")
            for count, name, _ in sorted(results[folder], key=lambda x: -x[0]):
                total += 1
                color = RED if count > 800 else YELLOW if count > 600 else GREEN
                print(f"  {color}{count}{RESET} lines - {name}")
            print()
        print(f"{CYAN}Total: {total} file(s) over {threshold} lines{RESET}\n")

    if args.versions:
        print(f"{CYAN}{'=' * 40}{RESET}\n")
        import subprocess

        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "find-versions.py")]
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
