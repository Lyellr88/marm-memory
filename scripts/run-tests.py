#!/usr/bin/env python3
"""Run local MARM MCP tests with fast defaults and explicit Docker opt-in."""

from __future__ import annotations

import argparse
import os
import shutil
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
CONSOLE_ROOT = ROOT / "marm-console"
CONSOLE_TESTS_ROOT = CONSOLE_ROOT / "tests"
CONSOLE_APP_ROOT = CONSOLE_ROOT / "artifacts" / "marm-console"
BASE_TEMP = Path(r"C:\tmp\marm-pytest") if os.name == "nt" else Path("/tmp/marm-pytest")
# Outside the repo, and shallow. Inside it, pytest's per-test temp paths ran ~100
# characters deep before the test even started, and the graph engine names each
# project's database after the repository's full path: a test repo at that depth
# produced a 283-character database path against Windows' 260 limit, and the
# engine's indexing worker exited non-zero. A sibling of BASE_TEMP rather than a
# child, so a concurrent --clean-temp run cannot delete this tree mid-run.
FAST_TEMP_ROOT = BASE_TEMP.parent / "marm-pytest-fast"
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


def run_step(
    name: str, command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> bool:
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
    include_docker = args.docker or args.slow
    if not include_docker:
        marker_filters.append("not docker")
    if not args.slow:
        marker_filters.append("not slow_stdio")
    if marker_filters:
        command.extend(["-m", " and ".join(marker_filters)])
    return command


def run_pytest_all(args: argparse.Namespace) -> bool:
    environment = pytest_env()
    if args.docker or args.slow:
        environment["MARM_SMOKE_DOCKER"] = "1"
    command = pytest_base_command(args)
    command.append("tests")
    return run_step("Pytest suite", command, SERVER_ROOT, env=environment)


def run_console_route_tests(args: argparse.Namespace) -> bool:
    command = pytest_base_command(args)
    command.append("tests")
    return run_step("Console route contracts", command, CONSOLE_ROOT, env=pytest_env())


def pnpm_executable() -> str | None:
    # PowerShell can resolve the extensionless npm shim, but subprocess on
    # Windows needs the runnable .cmd file.
    return shutil.which("pnpm.cmd") or shutil.which("pnpm")


def run_console_frontend_checks(pnpm: str) -> bool:
    for name, command in (
        ("Console typecheck", [pnpm, "typecheck"]),
        ("Console Vitest suite", [pnpm, "test"]),
        ("Console production build", [pnpm, "build"]),
    ):
        if not run_step(name, command, CONSOLE_APP_ROOT):
            return False
    return True


def run_compile_check(cwd: Path, *targets: str) -> bool:
    return run_step(
        "Python compile check",
        [sys.executable, "-m", "compileall", "-q", *targets],
        cwd,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MARM server and Console tests with Docker and slow checks opt-in."
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run one non-Docker pytest pass with fast local defaults.",
    )
    parser.add_argument(
        "--slow",
        action="store_true",
        help=(
            "Include slow subprocess STDIO tests and Docker tests. Docker tests "
            "skip themselves if Docker or the local image is unavailable."
        ),
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

    if not SERVER_ROOT.exists():
        print(f"{RED}MCP server folder not found: {SERVER_ROOT}{RESET}")
        return 1
    if not CONSOLE_TESTS_ROOT.exists() or not CONSOLE_APP_ROOT.exists():
        print(f"{RED}Console test workspace not found under: {CONSOLE_ROOT}{RESET}")
        return 1
    pnpm = pnpm_executable()
    if pnpm is None:
        print(
            f"{RED}pnpm is required for Console checks but was not found on PATH.{RESET}"
        )
        return 1

    if args.docker:
        if not docker_available():
            print(
                f"{YELLOW}Docker tests requested but Docker/image is unavailable; "
                f"skipping docker-marked tests.{RESET}"
            )
            args.docker = False
    elif args.slow:
        if not docker_available():
            print(
                f"{YELLOW}Slow mode includes Docker tests, but Docker/image is "
                f"unavailable; docker-marked tests will skip.{RESET}"
            )
    else:
        print(
            f"{YELLOW}Docker tests skipped by default. Use --docker to include them.{RESET}"
        )

    if args.compile and not run_compile_check(
        SERVER_ROOT, "marm_mcp_server", "marm_graph", "tests"
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

    if not run_console_route_tests(args) or not run_console_frontend_checks(pnpm):
        print(f"\n{RED}Test runner failed.{RESET}")
        return 1

    print(f"\n{GREEN}All test checks passed.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
