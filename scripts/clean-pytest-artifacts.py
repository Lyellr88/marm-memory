#!/usr/bin/env python3
"""Clean local pytest artifacts that can break Docker build context loading."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_ROOT = ROOT / "marm-mcp-server"
CONSOLE_ROOT = ROOT / "marm-console"
SAFE_ROOTS = [ROOT, SERVER_ROOT, CONSOLE_ROOT, Path(r"C:\tmp")]


def existing_safe_roots() -> list[Path]:
    return [path.resolve() for path in SAFE_ROOTS if path.exists()]


def is_safe_target(path: Path, safe_roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved == root or root in resolved.parents for root in safe_roots)


def add_existing_directory(path: Path, targets: set[Path]) -> None:
    if path.is_dir():
        targets.add(path)


def add_child_directories(base: Path, pattern: str, targets: set[Path]) -> None:
    if not base.is_dir():
        return
    for path in base.glob(pattern):
        if path.is_dir():
            targets.add(path)


def discover_targets() -> list[Path]:
    targets: set[Path] = set()

    for base in (ROOT, SERVER_ROOT, CONSOLE_ROOT):
        add_existing_directory(base / ".pytest_cache", targets)
        add_child_directories(base, ".pytest_tmp*", targets)
        add_child_directories(base, ".pytest-review-*", targets)
        add_child_directories(base, ".pytest-smoke-*", targets)
        add_child_directories(base / "tmp", "pytest-*", targets)

    add_child_directories(ROOT, "marm-pytest-*", targets)

    add_existing_directory(Path(r"C:\tmp\marm-pytest"), targets)

    safe_roots = existing_safe_roots()
    return sorted(
        (target for target in targets if is_safe_target(target, safe_roots)),
        key=lambda path: str(path).lower(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean local pytest artifacts.")
    parser.add_argument(
        "--what-if",
        action="store_true",
        help="Show what would be removed without deleting anything.",
    )
    args = parser.parse_args()

    targets = discover_targets()
    if not targets:
        print("No pytest artifacts found.")
        return 0

    for target in targets:
        if args.what_if:
            print(f"Would remove: {target}")
            continue
        try:
            shutil.rmtree(target)
            print(f"Removed: {target}")
        except OSError as exc:
            print(f"WARNING: Could not remove {target}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
