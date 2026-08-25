#!/usr/bin/env python3

import re
import sys
from collections import defaultdict
from pathlib import Path

CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
GRAY = "\033[90m"
RESET = "\033[0m"

REPO_ROOT = Path(__file__).parent.parent
SERVER_ROOT = REPO_ROOT / "marm-mcp-server"
CONSOLE_ROOT = REPO_ROOT / "marm-console"
PACKAGE_DIRS = [
    SERVER_ROOT / "marm_mcp_server",
    SERVER_ROOT / "marm_graph",
]
PACKAGE_NAMES = {package.name for package in PACKAGE_DIRS}
SERVER_PACKAGE = SERVER_ROOT / "marm_mcp_server"
SERVER_FILE = SERVER_PACKAGE / "server.py"

SKIP_FUNC_PREFIXES = ("__",)
SKIP_FUNC_NAMES = {
    "main",
    "create_server",
    "lifespan",
    "check_dependencies",
    "run_server_with_shutdown",
    "on_any_event",
    "format_help",
}

CHECK = "+"
WARN = "?"
FAIL = "x"


def all_py_files() -> list[Path]:
    """Collect shipped sources, announcing any configured package that is gone.

    A silently skipped package reads as a clean report, which is how a renamed
    or relocated package can drop out of the scan unnoticed.
    """
    files: list[Path] = []
    for package in PACKAGE_DIRS:
        if not package.exists():
            print(
                f"{YELLOW}  Warning: {display_path(package)}/ not found, skipping{RESET}"
            )
            continue
        files.extend(package.rglob("*.py"))
    return sorted(files)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def display_path(path: Path | str) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def module_path_for_file(path: Path) -> str:
    for root in (SERVER_ROOT, CONSOLE_ROOT):
        try:
            rel = path.relative_to(root)
            return ".".join(rel.with_suffix("").parts)
        except ValueError:
            continue
    return ".".join(path.with_suffix("").parts)


def explain_static_limits() -> None:
    print(
        f"{GRAY}This script scans source text only. It can miss dynamic imports, decorators,{RESET}"
    )
    print(
        f"{GRAY}console entry points, framework registration, and functions called by name.{RESET}"
    )
    print(
        f"{GRAY}Treat findings as review candidates, not automatic delete targets.{RESET}\n"
    )


def module_reference_patterns(module_path: str) -> set[str]:
    """Return import/reference strings that can indicate a module is used."""
    parts = module_path.split(".")
    stem = parts[-1]
    relative_parts = parts[1:] if parts and parts[0] in PACKAGE_NAMES else parts
    package_relative = ".".join(relative_parts)
    parent_relative = ".".join(relative_parts[:-1])

    patterns = {
        module_path,
        f"import {module_path}",
        f"from {module_path}",
        f"import {stem}",
        f"from .{stem}",
        f"from ..{stem}",
    }

    if package_relative:
        patterns.update(
            {
                f"from .{package_relative}",
                f"from ..{package_relative}",
                f"import {package_relative}",
            }
        )
    if parent_relative:
        patterns.update(
            {
                f"from .{parent_relative} import {stem}",
                f"from ..{parent_relative} import {stem}",
            }
        )

    return patterns


def module_is_referenced(module_path: str, all_source: str) -> bool:
    if any(pattern in all_source for pattern in module_reference_patterns(module_path)):
        return True
    stem = re.escape(module_path.split(".")[-1])
    if re.search(rf"from\s+\.+\s+import\s+[^\n#]*\b{stem}\b", all_source):
        return True
    return (
        re.search(rf"from\s+[.\w]+\s+import\s+\([^)]*\b{stem}\b", all_source, re.DOTALL)
        is not None
    )


def check_orphaned_modules() -> int:
    print(f"{YELLOW}1. Checking for orphaned modules...{RESET}")
    print(
        f"{GRAY}   Meaning: a Python file under shipped packages whose module name was not{RESET}"
    )
    print(
        f"{GRAY}   found in package imports. It may still be used by CLI entry points,{RESET}"
    )
    print(f"{GRAY}   decorators, tests, generated packaging, or external users.{RESET}")

    files = all_py_files()
    all_source = "\n".join(read(f) for f in files)

    skip = {"__init__.py", "__main__.py", "server.py"}
    orphaned = []

    for f in files:
        if f.name in skip:
            continue
        module_path = module_path_for_file(f)

        imported = module_is_referenced(module_path, all_source)
        if not imported:
            orphaned.append(str(f))

    if orphaned:
        print(f"{RED}  Found {len(orphaned)} orphaned module(s):{RESET}")
        for path in orphaned:
            print(f"    {RED}{FAIL}{RESET} {display_path(path)}")
        print(f"    {CYAN}Review checklist:{RESET}")
        print("      - Search tests/docs for the module name")
        print("      - Check pyproject console scripts and Docker commands")
        print("      - Check whether imports are indirect through package __init__.py")
        print("      - Delete only after import/runtime smoke tests pass")
    else:
        print(f"{GREEN}  {CHECK} No orphaned modules found{RESET}")

    print()
    return len(orphaned)


ROUTER_TARGETS = [
    (SERVER_PACKAGE / "endpoints", SERVER_FILE),
    (SERVER_ROOT / "marm_graph" / "endpoints", SERVER_ROOT / "marm_graph" / "server.py"),
]


def check_unregistered_routers() -> int:
    print(f"{YELLOW}2. Checking for unregistered routers...{RESET}")
    print(
        f"{GRAY}   Meaning: endpoint files that appear to define a FastAPI router but are{RESET}"
    )
    print(
        f"{GRAY}   never imported (as <name>_router or endpoints.<name>) in their server.py.{RESET}"
    )

    unregistered = []

    for endpoints_dir, server_file in ROUTER_TARGETS:
        if not endpoints_dir.exists():
            continue
        server_src = read(server_file) if server_file.exists() else ""

        for f in sorted(endpoints_dir.glob("*.py")):
            if f.name in ("__init__.py",):
                continue
            src = read(f)
            if "APIRouter" not in src and "router" not in src:
                continue

            stem = f.stem
            registered = f"{stem}_router" in server_src or f"endpoints.{stem}" in server_src

            if not registered:
                unregistered.append((stem, str(f)))

    if unregistered:
        print(f"{RED}  Found {len(unregistered)} unregistered router(s):{RESET}")
        for stem, path in unregistered:
            print(
                f"    {RED}{FAIL}{RESET} {stem} not registered in its server.py  ({display_path(path)})"
            )
        print(f"    {CYAN}Review checklist:{RESET}")
        print(
            "      - Confirm whether the endpoint should be public, hidden, or retired"
        )
        print(
            "      - Hidden endpoints may still be intentionally included with include_in_schema=False"
        )
        print("      - If retired, remove docs/tests/imports together")
    else:
        print(f"{GREEN}  {CHECK} All routers registered in server.py{RESET}")

    print()
    return len(unregistered)


def check_unused_functions() -> int:
    print(f"{YELLOW}3. Checking for unused functions...{RESET}")
    print(
        f"{GRAY}   Meaning: a function name appears only at its definition site across{RESET}"
    )
    print(
        f"{GRAY}   shipped packages. This is noisy for decorators, route handlers, protocol{RESET}"
    )
    print(f"{GRAY}   callbacks, and framework-discovered functions.{RESET}")

    files = all_py_files()
    all_source = "\n".join(read(f) for f in files)

    definitions: dict[str, list[tuple[str, int]]] = defaultdict(list)

    def_pattern = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)

    for f in files:
        src = read(f)
        lines = src.splitlines()
        for m in def_pattern.finditer(src):
            name = m.group(1)
            if name.startswith(SKIP_FUNC_PREFIXES) or name in SKIP_FUNC_NAMES:
                continue
            lineno = src[: m.start()].count("\n") + 1
            index = lineno - 2
            decorated = False
            while index >= 0 and lines[index].strip():
                if lines[index].lstrip().startswith("@"):
                    decorated = True
                    break
                index -= 1
            if decorated:
                continue
            definitions[name].append((str(f), lineno))

    unused = []
    for name, defs in definitions.items():
        count = len(re.findall(rf"\b{re.escape(name)}\b", all_source))
        if count <= len(defs):
            unused.append((name, defs))

    if unused:
        display = unused[:15]
        print(f"{YELLOW}  Found {len(unused)} potentially unused function(s):{RESET}")
        for name, defs in display:
            for filepath, lineno in defs:
                print(
                    f"    {YELLOW}{WARN}{RESET} {name}  ({display_path(filepath)}:{lineno})"
                )
        if len(unused) > 15:
            print(f"    {CYAN}... and {len(unused) - 15} more{RESET}")
        print(f"    {CYAN}Review checklist:{RESET}")
        print(
            "      - Route handlers and @mcp.tool functions may be used by decorators"
        )
        print("      - Check tests and public API docs before deleting")
        print("      - Prefer deprecating public behavior before removing it")
    else:
        print(f"{GREEN}  {CHECK} No obviously unused functions found{RESET}")

    print()
    return len(unused)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print(f"{CYAN}=== Dead Code Finder — shipped MARM Python packages ==={RESET}\n")
    explain_static_limits()

    if not any(package.exists() for package in PACKAGE_DIRS):
        print(f"{RED}✗ No shipped package folders found. Run from project root.{RESET}")
        return 1

    orphaned = check_orphaned_modules()
    routers = check_unregistered_routers()
    unused_fns = check_unused_functions()

    print(f"{CYAN}=== Summary ==={RESET}")
    print(f"Orphaned modules:       {(RED if orphaned else GREEN)}{orphaned}{RESET}")
    print(f"Unregistered routers:   {(RED if routers else GREEN)}{routers}{RESET}")
    print(
        f"Potentially unused fns: {(YELLOW if unused_fns else GREEN)}{unused_fns}{RESET}"
    )
    print()
    print(
        f"{CYAN}Tip: run `python -m compileall marm_mcp_server marm_graph` from marm-mcp-server/ to catch syntax errors{RESET}\n"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
