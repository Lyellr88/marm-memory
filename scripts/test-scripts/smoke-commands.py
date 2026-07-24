"""Run local smoke coverage for the marm-memory command surface."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "marm-mcp-server"
TEST_TARGET = "tests/test_command_smoke.py"


def _marker_expression(args: argparse.Namespace) -> str:
    groups = ["smoke"]
    if args.docker:
        groups.append("smoke_docker")
    if args.destructive:
        groups.append("smoke_destructive")
    expression = " or ".join(f"({group})" for group in groups)
    if "lifecycle" in args.skip:
        expression = f"({expression}) and not smoke_lifecycle"
    return expression


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run local marm-memory command smoke tests."
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Include real Docker lifecycle coverage when a daemon is available.",
    )
    parser.add_argument(
        "--destructive",
        action="store_true",
        help="Include the opt-in uninstall/reinstall lifecycle test.",
    )
    parser.add_argument(
        "--skip",
        action="append",
        choices=("lifecycle",),
        default=[],
        help="Skip a selected smoke tier. May be repeated.",
    )
    args = parser.parse_args()

    command = [
        sys.executable,
        "-m",
        "pytest",
        TEST_TARGET,
        "-m",
        _marker_expression(args),
        "-ra",
        "-v",
    ]
    print(f"Running command smoke tests: {' '.join(command)}")
    return subprocess.run(command, cwd=PACKAGE_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
