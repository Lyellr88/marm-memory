#!/usr/bin/env python3
"""Find potentially dead code in marm_mcp_server/.

This is a static heuristic scanner, not a deletion oracle. It is meant to
surface files/functions worth reviewing by a human or code-review agent.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

CYAN   = "\033[36m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
RED    = "\033[31m"
GRAY   = "\033[90m"
RESET  = "\033[0m"

ROOT        = Path(__file__).parent.parent / "marm-mcp-server"
PACKAGE     = ROOT / "marm_mcp_server"
SERVER_FILE = PACKAGE / "server.py"

# Names that are fine to appear only once (entry points, protocols, magic methods)
SKIP_FUNC_PREFIXES = ("__",)
SKIP_FUNC_NAMES = {
    "main", "create_server", "lifespan", "check_dependencies",
    "run_server_with_shutdown",
}

CHECK = "+"
WARN = "?"
FAIL = "x"


def all_py_files() -> list[Path]:
    """
    Collects all Python files under the package directory.
    
    Returns:
        files (list[Path]): Sorted list of Path objects for every `.py` file found recursively under PACKAGE.
    """
    return sorted(PACKAGE.rglob("*.py"))


def read(path: Path) -> str:
    """
    Read a file as UTF-8 text while ignoring decoding errors.
    
    Parameters:
        path (Path): Path to the file to read.
    
    Returns:
        content (str): The file contents decoded as UTF-8; bytes that cannot be decoded are skipped.
    """
    return path.read_text(encoding="utf-8", errors="ignore")


def display_path(path: Path | str) -> str:
    """
    Produce a path string relative to the repository root's parent when possible.
    
    Parameters:
        path (Path | str): File system path to display.
    
    Returns:
        str: Path converted to a string; relative to ROOT.parent if the input can be relativized, otherwise the original absolute/path string.
    """
    p = Path(path)
    try:
        return str(p.relative_to(ROOT.parent))
    except ValueError:
        return str(p)


def explain_static_limits() -> None:
    """
    Print a brief notice explaining the limitations of the static text-only scan.
    
    Informs the user that the scanner only examines source text and may miss dynamic imports, decorators, console entry points, framework registration, and functions called by name, and that reported items should be treated as review candidates rather than automatic deletion targets.
    """
    print(f"{GRAY}This script scans source text only. It can miss dynamic imports, decorators,{RESET}")
    print(f"{GRAY}console entry points, framework registration, and functions called by name.{RESET}")
    print(f"{GRAY}Treat findings as review candidates, not automatic delete targets.{RESET}\n")


def module_reference_patterns(module_path: str) -> set[str]:
    """
    Produce a set of common substring patterns that indicate a dotted module path is referenced or imported.
    
    Parameters:
        module_path (str): Dotted module path (e.g., "marm_mcp_server.core.memory").
    
    Returns:
        set[str]: A set of string patterns such as the module path itself, "import <module>",
        "from <module>", the module stem import forms, and package-relative or relative
        import variants that are likely to appear in source.
    """
    parts = module_path.split(".")
    stem = parts[-1]
    package_relative = ".".join(parts[1:]) if parts and parts[0] == "marm_mcp_server" else module_path

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

    return patterns


# ---------------------------------------------------------------------------
# Check 1: Orphaned modules — never imported by anything in the package
# ---------------------------------------------------------------------------
def check_orphaned_modules() -> int:
    """
    Check the package for Python modules that appear unused and report findings.
    
    Uses textual heuristics to detect modules under marm_mcp_server/ whose module
    name does not appear referenced elsewhere in the package, prints a human-
    readable report to stdout, and suggests manual review steps when candidates
    are found.
    
    Returns:
        int: The number of modules identified as potentially orphaned.
    """
    print(f"{YELLOW}1. Checking for orphaned modules...{RESET}")
    print(f"{GRAY}   Meaning: a Python file under marm_mcp_server/ whose module name was not{RESET}")
    print(f"{GRAY}   found in package imports. It may still be used by CLI entry points,{RESET}")
    print(f"{GRAY}   decorators, tests, generated packaging, or external users.{RESET}")

    files = all_py_files()
    all_source = "\n".join(read(f) for f in files)

    skip = {"__init__.py", "__main__.py", "server.py"}
    orphaned = []

    for f in files:
        if f.name in skip:
            continue
        # Build the dotted module name relative to package root
        rel = f.relative_to(PACKAGE.parent)
        module_path = ".".join(rel.with_suffix("").parts)  # e.g. marm_mcp_server.core.memory
        stem = f.stem  # e.g. memory

        imported = any(pattern in all_source for pattern in module_reference_patterns(module_path))
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


# ---------------------------------------------------------------------------
# Check 2: Unregistered routers — endpoint files with a router not in server.py
# ---------------------------------------------------------------------------
def check_unregistered_routers() -> int:
    """
    Check endpoint modules for FastAPI routers that are not referenced in server.py and report findings.
    
    Scans the package's endpoints directory for Python modules that appear to define a router and verifies whether the expected "<module>_router" variable name is referenced in server.py. Prints a human-readable report of any unregistered routers to stdout.
    
    Returns:
        int: The number of endpoint modules whose expected "<name>_router" alias is not found in server.py.
    """
    print(f"{YELLOW}2. Checking for unregistered routers...{RESET}")
    print(f"{GRAY}   Meaning: endpoint files that appear to define a FastAPI router but whose{RESET}")
    print(f"{GRAY}   expected <name>_router alias is not referenced in server.py.{RESET}")

    endpoints_dir = PACKAGE / "endpoints"
    server_src = read(SERVER_FILE) if SERVER_FILE.exists() else ""

    unregistered = []

    for f in sorted(endpoints_dir.glob("*.py")):
        if f.name in ("__init__.py",):
            continue
        src = read(f)
        if "APIRouter" not in src and "router" not in src:
            continue

        stem = f.stem  # e.g. "memory"
        router_var = f"{stem}_router"

        if router_var not in server_src:
            unregistered.append((stem, str(f)))

    if unregistered:
        print(f"{RED}  Found {len(unregistered)} unregistered router(s):{RESET}")
        for stem, path in unregistered:
            print(f"    {RED}{FAIL}{RESET} {stem}_router not in server.py  ({display_path(path)})")
        print(f"    {CYAN}Review checklist:{RESET}")
        print("      - Confirm whether the endpoint should be public, hidden, or retired")
        print("      - Hidden endpoints may still be intentionally included with include_in_schema=False")
        print("      - If retired, remove docs/tests/imports together")
    else:
        print(f"{GREEN}  {CHECK} All routers registered in server.py{RESET}")

    print()
    return len(unregistered)


# ---------------------------------------------------------------------------
# Check 3: Unused functions — defined but only appear once across all files
# ---------------------------------------------------------------------------
def check_unused_functions() -> int:
    """
    Identify function definitions in marm_mcp_server whose names appear only at their definition sites across the package.
    
    This heuristic scans all Python files in the package for top-level function definitions (excluding names starting with configured prefixes and names in the skip list) and counts those whose identifier occurs no more times than their definitions. Results are noisy: functions used via decorators, route handlers, callbacks, test discovery, or framework registration may be reported.
    
    Returns:
        count (int): Number of function names considered potentially unused.
    """
    print(f"{YELLOW}3. Checking for unused functions...{RESET}")
    print(f"{GRAY}   Meaning: a function name appears only at its definition site across{RESET}")
    print(f"{GRAY}   marm_mcp_server/. This is noisy for decorators, route handlers, protocol{RESET}")
    print(f"{GRAY}   callbacks, and framework-discovered functions.{RESET}")

    files = all_py_files()
    all_source = "\n".join(read(f) for f in files)

    # name → list of (file, lineno)
    definitions: dict[str, list[tuple[str, int]]] = defaultdict(list)

    def_pattern = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)

    for f in files:
        src = read(f)
        for m in def_pattern.finditer(src):
            name = m.group(1)
            if name.startswith(SKIP_FUNC_PREFIXES) or name in SKIP_FUNC_NAMES:
                continue
            lineno = src[: m.start()].count("\n") + 1
            definitions[name].append((str(f), lineno))

    unused = []
    for name, defs in definitions.items():
        count = len(re.findall(rf"\b{re.escape(name)}\b", all_source))
        # count == len(defs) means only the definitions themselves match
        if count <= len(defs):
            unused.append((name, defs))

    if unused:
        # Cap display at 15 — noisy otherwise
        display = unused[:15]
        print(f"{YELLOW}  Found {len(unused)} potentially unused function(s):{RESET}")
        for name, defs in display:
            for filepath, lineno in defs:
                print(f"    {YELLOW}{WARN}{RESET} {name}  ({display_path(filepath)}:{lineno})")
        if len(unused) > 15:
            print(f"    {CYAN}... and {len(unused) - 15} more{RESET}")
        print(f"    {CYAN}Review checklist:{RESET}")
        print("      - Route handlers and @mcp.tool functions may be used by decorators")
        print("      - Check tests and public API docs before deleting")
        print("      - Prefer deprecating public behavior before removing it")
    else:
        print(f"{GREEN}  {CHECK} No obviously unused functions found{RESET}")

    print()
    return len(unused)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def main() -> int:
    """
    Run static heuristic scans for dead code in marm_mcp_server and print a colorized summary.
    
    This function performs the script's main workflow: it attempts to ensure UTF-8 output, explains static-scan limitations, verifies the marm_mcp_server package exists, runs checks for orphaned modules, unregistered routers, and potentially unused functions, then prints a summary and a tip.
    
    Returns:
        int: 0 on normal completion, 1 if the marm_mcp_server package is not found.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print(f"{CYAN}=== Dead Code Finder — marm_mcp_server/ ==={RESET}\n")
    explain_static_limits()

    if not PACKAGE.exists():
        print(f"{RED}✗ marm_mcp_server/ not found. Run from project root.{RESET}")
        return 1

    orphaned   = check_orphaned_modules()
    routers    = check_unregistered_routers()
    unused_fns = check_unused_functions()

    print(f"{CYAN}=== Summary ==={RESET}")
    print(f"Orphaned modules:       {(RED if orphaned else GREEN)}{orphaned}{RESET}")
    print(f"Unregistered routers:   {(RED if routers else GREEN)}{routers}{RESET}")
    print(f"Potentially unused fns: {(YELLOW if unused_fns else GREEN)}{unused_fns}{RESET}")
    print()
    print(f"{CYAN}Tip: run `python -m py_compile marm_mcp_server/**/*.py` to catch syntax errors{RESET}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
