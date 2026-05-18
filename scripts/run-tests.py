#!/usr/bin/env python3
"""Run the known-good local MARM MCP test checks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

ROOT = Path(__file__).resolve().parent.parent
SERVER_ROOT = ROOT / "marm-mcp-server"
BASE_TEMP = Path(r"C:\tmp\marm-pytest") if os.name == "nt" else Path("/tmp/marm-pytest")


def run_step(name: str, command: list[str], cwd: Path) -> bool:
    print(f"\n{CYAN}==> {name}{RESET}")
    print(" ".join(command))
    result = subprocess.run(command, cwd=cwd)
    if result.returncode == 0:
        print(f"{GREEN}PASS: {name}{RESET}")
        return True
    print(f"{RED}FAIL: {name} (exit {result.returncode}){RESET}")
    return False


def main() -> int:
    if not SERVER_ROOT.exists():
        print(f"{RED}MCP server folder not found: {SERVER_ROOT}{RESET}")
        return 1

    BASE_TEMP.parent.mkdir(parents=True, exist_ok=True)

    steps = [
        (
            "Python compile check",
            [sys.executable, "-m", "compileall", "-q", "marm_mcp_server", "tests"],
        ),
        (
            "Pytest suite",
            [sys.executable, "-m", "pytest", "-q", "--basetemp", str(BASE_TEMP)],
        ),
    ]

    failed = False
    for name, command in steps:
        if not run_step(name, command, SERVER_ROOT):
            failed = True
            break

    if failed:
        print(f"\n{RED}Test runner failed.{RESET}")
        return 1

    print(f"\n{GREEN}All test checks passed.{RESET}")
    print(f"{YELLOW}Note: Docker tests skip automatically if Docker/image is unavailable.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
