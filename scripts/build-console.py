#!/usr/bin/env python3
"""Build the Console frontend and replace the bundled copy the server serves.

Only needed to refresh the packaged Console that `marm-memory console` serves on
port 8002. For iterating on frontend code, do not use this: run the dev server,
which hot-reloads and points itself at the backend on 8002 automatically.

    cd marm-console/artifacts/marm-console
    pnpm dev                                   # http://127.0.0.1:5173

Publishing does not need this either; publish-mcp.yml builds and copies the same
way on every tag.

    python scripts/build-console.py
    python scripts/build-console.py --check     # verify the bundle, build nothing

Exists because doing it by hand has two traps. The destination must be removed
first or stale asset hashes accumulate, and `Copy-Item`/`cp` semantics differ:
copying a directory onto an existing directory nests it, producing
`static/public/index.html`, which the server does not serve and which reports
only as a 503 with assets "missing".
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "marm-console"
APP = WORKSPACE / "artifacts" / "marm-console"
DIST = APP / "dist" / "public"
STATIC = ROOT / "marm-mcp-server" / "marm_mcp_server" / "console" / "static"

REQUIRED = ("index.html", "assets")


def fail(message: str) -> int:
    print(f"{RED}FAIL{RESET} {message}")
    return 1


def referenced_assets(index_html: Path) -> list[str]:
    """Asset paths index.html actually loads.

    Checked rather than assumed: the failure this script exists to prevent leaves
    an index.html whose assets are one directory away, and every individual file
    is present, so only the reference resolves wrong.
    """
    text = index_html.read_text(encoding="utf-8", errors="replace")
    return sorted(set(re.findall(r'(?:src|href)="\.?/?(assets/[^"]+)"', text)))


def verify(root: Path) -> tuple[bool, list[str]]:
    problems: list[str] = []
    for name in REQUIRED:
        if not (root / name).exists():
            problems.append(f"missing {name}")
    index = root / "index.html"
    if index.exists():
        refs = referenced_assets(index)
        if not refs:
            problems.append("index.html references no assets")
        for ref in refs:
            if not (root / ref).exists():
                problems.append(f"index.html references {ref}, which is not there")
        if (root / "public").is_dir():
            problems.append(
                "a nested public/ directory is present, so the copy landed one "
                "level too deep"
            )
    return not problems, problems


def run(cmd: list[str], cwd: Path) -> int:
    print(f"{YELLOW}$ {' '.join(cmd)}{RESET}  (in {cwd})")
    try:
        return subprocess.run(cmd, cwd=cwd).returncode
    except FileNotFoundError:
        print(f"{RED}FAIL{RESET} {cmd[0]} not found on PATH")
        return 127


def _pnpm_command() -> str:
    """Use the Windows command shim when Python launches pnpm directly."""
    return "pnpm.cmd" if sys.platform == "win32" else "pnpm"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the currently bundled Console and exit without building",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="skip pnpm install (use when dependencies are known current)",
    )
    args = parser.parse_args()

    if args.check:
        ok, problems = verify(STATIC)
        if ok:
            index = STATIC / "index.html"
            print(f"{GREEN}OK{RESET}  bundled Console is coherent")
            for ref in referenced_assets(index):
                print(f"    {ref}")
            return 0
        for problem in problems:
            print(f"{RED}  {problem}{RESET}")
        return fail(f"bundled Console at {STATIC} is not servable")

    if not APP.is_dir():
        return fail(f"console app not found at {APP}")

    if not args.skip_install:
        if run([_pnpm_command(), "install", "--frozen-lockfile"], WORKSPACE):
            return fail("pnpm install failed")

    if run([_pnpm_command(), "build"], WORKSPACE):
        return fail("pnpm build failed; the bundled Console was left untouched")

    # Verified before anything is deleted. Removing the destination first and then
    # discovering the build produced nothing leaves no Console at all, which is
    # exactly how this went wrong by hand.
    ok, problems = verify(DIST)
    if not ok:
        for problem in problems:
            print(f"{RED}  {problem}{RESET}")
        return fail(f"build output at {DIST} is incomplete; nothing was replaced")

    # Staged beside the destination and verified before the swap, so a copy that
    # fails part way through cannot leave the server with no Console. Verifying
    # DIST above only proves the source is complete; a full disk or a locked file
    # can still abort the copy itself, and the symptom is a bare 503.
    staging = STATIC.parent / f"{STATIC.name}.incoming"
    previous = STATIC.parent / f"{STATIC.name}.previous"
    for scratch in (staging, previous):
        if scratch.exists():
            shutil.rmtree(scratch)

    try:
        shutil.copytree(DIST, staging)
        ok, problems = verify(staging)
        if not ok:
            for problem in problems:
                print(f"{RED}  {problem}{RESET}")
            shutil.rmtree(staging, ignore_errors=True)
            return fail("the staged bundle is not servable; nothing was replaced")
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return fail(f"could not stage the bundle ({exc}); nothing was replaced")

    if STATIC.exists():
        STATIC.rename(previous)
    try:
        staging.rename(STATIC)
    except OSError as exc:
        if previous.exists() and not STATIC.exists():
            previous.rename(STATIC)
        shutil.rmtree(staging, ignore_errors=True)
        return fail(f"could not swap the bundle into place ({exc}); rolled back")

    ok, problems = verify(STATIC)
    if not ok:
        for problem in problems:
            print(f"{RED}  {problem}{RESET}")
        # Roll back rather than leave a half-working Console behind.
        shutil.rmtree(STATIC, ignore_errors=True)
        if previous.exists():
            previous.rename(STATIC)
            print(f"{YELLOW}  rolled back to the previous bundle{RESET}")
        return fail("the swapped bundle did not verify")

    shutil.rmtree(previous, ignore_errors=True)

    assets = sorted(p.name for p in (STATIC / "assets").iterdir())
    print(f"{GREEN}OK{RESET}  bundled Console replaced at {STATIC}")
    for ref in referenced_assets(STATIC / "index.html"):
        print(f"    serves {ref}")
    extra = [
        name
        for name in assets
        if not any(name in r for r in referenced_assets(STATIC / "index.html"))
    ]
    if extra:
        print(f"    {len(extra)} unreferenced file(s) in assets/: {', '.join(extra)}")
    print("    restart the server, then reload the Console on port 8002")
    return 0


if __name__ == "__main__":
    sys.exit(main())
