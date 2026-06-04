#!/usr/bin/env python3
"""Run local MARM MCP tests with fast defaults and explicit Docker opt-in."""

from __future__ import annotations

import argparse
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
TESTS_ROOT = SERVER_ROOT / "tests"
BASE_TEMP = Path(r"C:\tmp\marm-pytest") if os.name == "nt" else Path("/tmp/marm-pytest")
FAST_TEMP_ROOT = SERVER_ROOT / ".pytest_tmp_fast"
DOCKER_IMAGE = "lyellr88/marm-mcp-server:latest"


def pytest_env() -> dict[str, str]:
    env = os.environ.copy()
    temp_root_path = FAST_TEMP_ROOT / f"run-{os.getpid()}"
    temp_root_path.mkdir(parents=True, exist_ok=True)
    temp_root = str(temp_root_path)
    env["PYTEST_DEBUG_TEMPROOT"] = temp_root
    env["TMP"] = temp_root
    env["TEMP"] = temp_root
    env["TMPDIR"] = temp_root
    return env


def run_step(name: str, command: list[str], cwd: Path, env: dict[str, str] | None = None) -> bool:
    print(f"\n{CYAN}==> {name}{RESET}")
    print(" ".join(command))
    result = subprocess.run(command, cwd=cwd, env=env)
    if result.returncode == 0:
        print(f"{GREEN}PASS: {name}{RESET}")
        return True
    print(f"{RED}FAIL: {name} (exit {result.returncode}){RESET}")
    return False


def docker_available() -> bool:
    try:
        ps = subprocess.run(
            ["docker", "ps"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        if ps.returncode != 0:
            return False
        image = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return image.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def pytest_base_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    if not args.project_addopts:
        # pyproject.toml sets --basetemp=.pytest_tmp globally. Fast local runs
        # intentionally bypass that cleanup cost unless --clean-temp/--full is used.
        command.extend(["-o", "addopts="])
    if not args.show_warnings:
        command.append("--disable-warnings")
    if args.clean_temp:
        BASE_TEMP.parent.mkdir(parents=True, exist_ok=True)
        command.extend(["--basetemp", str(BASE_TEMP)])
    if args.last_failed:
        command.append("--lf")
    marker_filters = []
    if not args.docker:
        marker_filters.append("not docker")
    if not args.slow:
        marker_filters.append("not slow_stdio")
    if marker_filters:
        command.extend(["-m", " and ".join(marker_filters)])
    return command


def run_pytest_all(args: argparse.Namespace) -> bool:
    command = pytest_base_command(args)
    command.append("tests")
    return run_step("Pytest suite", command, SERVER_ROOT, env=pytest_env())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MARM MCP tests with Docker and slow checks opt-in."
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run one non-Docker pytest pass with fast local defaults.",
    )
    parser.add_argument(
        "--slow",
        action="store_true",
        help="Include slow subprocess STDIO transport tests.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run compile check and clean pytest temp directory.",
    )
    parser.add_argument(
        "--compile",
        action="store_true",
        help="Run compileall before pytest.",
    )
    parser.add_argument(
        "--clean-temp",
        action="store_true",
        help=f"Pass --basetemp={BASE_TEMP} to pytest. This deletes that temp tree.",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Include Docker transport tests if Docker and the local image are available.",
    )
    parser.add_argument(
        "--last-failed",
        action="store_true",
        help="Pass --lf to pytest.",
    )
    parser.add_argument(
        "--show-warnings",
        action="store_true",
        help="Show pytest warning summaries. Hidden by default for fast local runs.",
    )
    parser.add_argument(
        "--project-addopts",
        action="store_true",
        help="Use pytest addopts from pyproject.toml instead of clearing them.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.full:
        args.compile = True
        args.clean_temp = True
        args.slow = True

    if not SERVER_ROOT.exists():
        print(f"{RED}MCP server folder not found: {SERVER_ROOT}{RESET}")
        return 1

    if args.docker:
        if not docker_available():
            print(
                f"{YELLOW}Docker tests requested but Docker/image is unavailable; "
                f"skipping docker-marked tests.{RESET}"
            )
            args.docker = False
    else:
        print(f"{YELLOW}Docker tests skipped by default. Use --docker to include them.{RESET}")

    if args.compile and not run_step(
        "Python compile check",
        [sys.executable, "-m", "compileall", "-q", "marm_mcp_server", "tests"],
        SERVER_ROOT,
    ):
        print(f"\n{RED}Test runner failed.{RESET}")
        return 1

    if not TESTS_ROOT.exists():
        print(f"{RED}Tests folder not found: {TESTS_ROOT}{RESET}")
        return 1

    ok = run_pytest_all(args)
    if not ok:
        print(f"\n{RED}Test runner failed.{RESET}")
        return 1

    print(f"\n{GREEN}All test checks passed.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
