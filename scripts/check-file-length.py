#!/usr/bin/env python3
"""Report Python files in marm_mcp_server/ that exceed a line threshold."""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

CYAN   = "\033[36m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
RED    = "\033[31m"
GRAY   = "\033[90m"
RESET  = "\033[0m"

ROOT       = Path(__file__).parent.parent / "marm-mcp-server"
SCAN_DIRS  = ["marm_mcp_server"]
EXTENSIONS = {".py", ".toml", ".md", ".txt", ".json"}


def line_count(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check file line lengths.")
    parser.add_argument("--threshold", "-t", type=int, default=400,
                        help="Minimum line count to report (default: 400)")
    parser.add_argument("--versions", "-v", action="store_true",
                        help="Also run find-versions after the check")
    args = parser.parse_args()

    threshold = args.threshold
    print(f"{CYAN}=== File Length Check (>{threshold} lines) ==={RESET}\n")

    results: dict[str, list[tuple[int, str, str]]] = defaultdict(list)

    for dir_name in SCAN_DIRS:
        base = ROOT / dir_name
        if not base.exists():
            print(f"{YELLOW}Warning: {dir_name}/ not found, skipping{RESET}")
            continue

        files = [f for f in base.rglob("*") if f.is_file() and f.suffix in EXTENSIONS]
        print(f"{GRAY}Scanning {len(files)} files in {dir_name}/{RESET}")

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
        subprocess.run([sys.executable, str(Path(__file__).parent / "find-versions.py")])

    return 0


if __name__ == "__main__":
    sys.exit(main())
