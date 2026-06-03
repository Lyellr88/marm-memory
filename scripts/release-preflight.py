#!/usr/bin/env python3
"""Interactive release preflight for MARM Systems."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

ROOT = Path(__file__).resolve().parent.parent


def run_step(
    name: str,
    command: list[str],
    *,
    input_text: str | None = None,
    required: bool = True,
) -> bool:
    print(f"\n{CYAN}==> {name}{RESET}")
    print(" ".join(command))
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=input_text,
        text=True,
    )
    if result.returncode == 0:
        print(f"{GREEN}PASS: {name}{RESET}")
        return True

    color = RED if required else YELLOW
    label = "FAIL" if required else "WARN"
    print(f"{color}{label}: {name} (exit {result.returncode}){RESET}")
    return not required


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def git_status() -> None:
    print(f"\n{CYAN}==> Git status summary{RESET}")
    subprocess.run(["git", "status", "--short"], cwd=ROOT)


def main() -> int:
    print(f"{CYAN}=== MARM Release Preflight ==={RESET}")
    print("This runs the local checks normally needed before push.\n")

    steps: list[tuple[str, list[str], str | None, bool]] = [
        (
            "Version scan",
            [sys.executable, "scripts/find-versions.py"],
            "n\n",
            True,
        ),
        (
            "Stale docs scan",
            [sys.executable, "scripts/scan-stale-docs.py"],
            None,
            False,
        ),
        (
            "Known-good test runner",
            [sys.executable, "scripts/run-tests.py"],
            None,
            True,
        ),
    ]

    failed = False
    for name, command, input_text, required in steps:
        if not run_step(name, command, input_text=input_text, required=required):
            failed = True
            break

    if not failed and ask_yes_no("\nRun Docker smoke test now?", default=True):
        if not run_step("Docker smoke", [sys.executable, "scripts/test-scripts/docker-smoke.py"], required=True):
            failed = True
    elif not failed:
        print(f"{YELLOW}Docker smoke skipped by user.{RESET}")

    git_status()

    if failed:
        print(f"\n{RED}Release preflight failed. Fix the failing step before push.{RESET}")
        return 1

    print(f"\n{GREEN}Release preflight completed. Review warnings/git status before push.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
