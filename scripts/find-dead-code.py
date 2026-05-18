#!/usr/bin/env python3
"""Find potentially dead code in marm_mcp_server/."""

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


def all_py_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Check 1: Orphaned modules — never imported by anything in the package
# ---------------------------------------------------------------------------
def check_orphaned_modules() -> int:
    print(f"{YELLOW}1. Checking for orphaned modules...{RESET}")

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

        imported = (
            module_path in all_source
            or f"import {stem}" in all_source
            or f"from .{stem}" in all_source
            or f"from ..{stem}" in all_source
        )
        if not imported:
            orphaned.append(str(f))

    if orphaned:
        print(f"{RED}  Found {len(orphaned)} orphaned module(s):{RESET}")
        for path in orphaned:
            print(f"    {RED}✗{RESET} {path}")
    else:
        print(f"{GREEN}  ✓ No orphaned modules found{RESET}")

    print()
    return len(orphaned)


# ---------------------------------------------------------------------------
# Check 2: Unregistered routers — endpoint files with a router not in server.py
# ---------------------------------------------------------------------------
def check_unregistered_routers() -> int:
    print(f"{YELLOW}2. Checking for unregistered routers...{RESET}")

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
            print(f"    {RED}✗{RESET} {stem}_router not in server.py  ({path})")
    else:
        print(f"{GREEN}  ✓ All routers registered in server.py{RESET}")

    print()
    return len(unregistered)


# ---------------------------------------------------------------------------
# Check 3: Unused functions — defined but only appear once across all files
# ---------------------------------------------------------------------------
def check_unused_functions() -> int:
    print(f"{YELLOW}3. Checking for unused functions...{RESET}")

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
                print(f"    {YELLOW}?{RESET} {name}  ({filepath}:{lineno})")
        if len(unused) > 15:
            print(f"    {CYAN}... and {len(unused) - 15} more{RESET}")
        print(f"    {CYAN}Note: decorators and dynamic calls may not be detected{RESET}")
    else:
        print(f"{GREEN}  ✓ No obviously unused functions found{RESET}")

    print()
    return len(unused)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def main() -> int:
    print(f"{CYAN}=== Dead Code Finder — marm_mcp_server/ ==={RESET}\n")

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
