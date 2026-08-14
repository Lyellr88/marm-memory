#!/usr/bin/env python3
"""Decide whether a console dependency PR is safe to merge.

Green CI does not answer this. The Ruff job never reads package.json or the
lockfile, and the console build only runs on a release tag, so a broken
dependency stays invisible until a tag is already cut.

Builds the PR in a throwaway git worktree, so the working tree, the current
branch, and marm-console/node_modules are untouched. Compares the emitted asset
filenames against the base branch: those names are content hashes, so identical
names mean an identical bundle.

    python scripts/check-console-pr.py 137          one PR
    python scripts/check-console-pr.py 135 136 137  several
    python scripts/check-console-pr.py --ref MARM-main   a branch instead

Needs node, pnpm, and gh on PATH. Exits non-zero if any target fails.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLE = "marm-console"
ASSET_DIR = "artifacts/marm-console/dist/public/assets"
BASE_REF = "origin/MARM-main"

_created_refs: list[str] = []


def run(
    cmd: list[str], cwd: Path, timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    # Resolved rather than passed bare: pnpm is a .cmd shim on Windows, which
    # CreateProcess cannot launch by name without a shell. Resolving keeps
    # shell=False instead of reaching for shell=True.
    resolved = shutil.which(cmd[0]) or cmd[0]
    return subprocess.run(
        [resolved, *cmd[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
        check=False,
    )


def tool_missing() -> list[str]:
    return [t for t in ("node", "pnpm", "gh", "git") if shutil.which(t) is None]


def fetch_pr(number: str) -> tuple[str, str, bool]:
    """Fetch a PR into a private ref. Returns (ref, label suffix, mergeable).

    Prefers refs/pull/N/merge, GitHub's preview of the PR already merged into
    the base. Testing the head alone compares a branch that may predate recent
    base commits, which reports every intervening change as a difference in this
    PR. Falls back to the head when no merge ref exists, which is GitHub's way
    of saying the PR does not merge cleanly.
    """
    # Under refs/console-check/ rather than refs/heads/: a branch there would
    # collide with a developer's own branch of that name, which cleanup deletes.
    local = f"refs/console-check/pr{number}"
    for ref, suffix, mergeable in (
        (f"refs/pull/{number}/merge", "merged", True),
        (f"refs/pull/{number}/head", "head only, does not merge cleanly", False),
    ):
        proc = run(
            ["git", "fetch", "--force", "origin", f"{ref}:{local}"], REPO_ROOT, 120
        )
        if proc.returncode == 0:
            _created_refs.append(local)
            return local, suffix, mergeable
    raise RuntimeError(f"could not fetch PR {number}: no merge or head ref")


def assets(worktree: Path) -> set[str]:
    d = worktree / CONSOLE / ASSET_DIR
    return {p.name for p in d.iterdir()} if d.is_dir() else set()


def check(ref: str, label: str, workdir: Path) -> tuple[bool, str, set[str]]:
    """Install, typecheck, and build one ref. Returns (ok, detail, asset names)."""
    tree = workdir / label.replace("/", "_").replace("#", "")
    add = run(["git", "worktree", "add", "-q", "--detach", str(tree), ref], REPO_ROOT)
    if add.returncode != 0:
        return False, f"worktree failed: {add.stderr.strip()}", set()

    console = tree / CONSOLE
    for name, cmd in (
        ("install", ["pnpm", "install", "--frozen-lockfile"]),
        ("typecheck", ["pnpm", "typecheck"]),
        ("build", ["pnpm", "build"]),
    ):
        print(f"  {label}: {name} ...", flush=True)
        try:
            proc = run(cmd, console)
        except subprocess.TimeoutExpired:
            return False, f"{name} timed out", set()
        if proc.returncode != 0:
            return (
                False,
                f"{name} failed\n{_first_error(proc.stdout + proc.stderr)}",
                set(),
            )

    return True, "install, typecheck, build all passed", assets(tree)


def _first_error(output: str) -> str:
    """The lines a reader needs, not the whole log."""
    keep = [
        line
        for line in output.splitlines()
        if any(
            marker in line
            for marker in (
                "error",
                "Error",
                "ERR_",
                "failed",
                "not defined",
                "Cannot find",
            )
        )
    ]
    return (
        "\n".join(f"      {line.strip()}" for line in keep[:8])
        or "      (no error lines captured)"
    )


def prune(workdir: Path) -> None:
    """Drop git's worktree records. The directories themselves live in the OS
    temp dir; nested node_modules paths regularly defeat rmtree on Windows, and
    a leftover temp directory is not worth failing the run over."""
    run(["git", "worktree", "prune"], REPO_ROOT, 60)
    for ref in _created_refs:
        run(["git", "update-ref", "-d", ref], REPO_ROOT, 60)
    shutil.rmtree(workdir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prs", nargs="*", help="PR numbers to check")
    parser.add_argument("--ref", action="append", default=[], help="git ref to check")
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="skip the base-branch build (faster, but no bundle comparison)",
    )
    args = parser.parse_args()

    if not args.prs and not args.ref:
        parser.error("give at least one PR number or --ref")

    missing = tool_missing()
    if missing:
        print(f"FAIL  missing required tools: {', '.join(missing)}")
        return 2

    # Checked, not fired and forgotten: silently reusing a stale origin/MARM-main
    # makes base drift show up as a bundle difference the PR did not cause.
    fetched = run(["git", "fetch", "--quiet", "origin", "MARM-main"], REPO_ROOT, 120)
    if fetched.returncode != 0:
        print(f"FAIL  could not fetch {BASE_REF}:\n      {fetched.stderr.strip()}")
        return 2

    targets: list[tuple[str, str, bool]] = []
    for number in args.prs:
        try:
            ref, suffix, mergeable = fetch_pr(number)
            targets.append((ref, f"PR #{number} ({suffix})", mergeable))
        except RuntimeError as exc:
            print(f"FAIL  {exc}")
            return 2
    targets += [(ref, ref, True) for ref in args.ref]

    workdir = Path(tempfile.mkdtemp(prefix="marm-console-check-"))
    results: list[tuple[str, bool, str]] = []
    try:
        baseline: set[str] = set()
        if not args.no_baseline:
            print(f"baseline: {BASE_REF}")
            ok, detail, baseline = check(BASE_REF, "baseline", workdir)
            if not ok:
                # Every later verdict would be meaningless: a failure could be
                # the base branch rather than the PR.
                print(f"\nFAIL  baseline {BASE_REF} does not build.\n{detail}")
                print(
                    "Fix the base branch first; PR verdicts cannot be trusted until then."
                )
                return 2
            print(f"  baseline ok, {len(baseline)} asset(s)")

        for ref, label, mergeable in targets:
            print(f"\n{label}  ({ref})")
            ok, detail, produced = check(ref, label, workdir)
            if ok and baseline:
                if produced == baseline:
                    detail += (
                        "\n      bundle identical to baseline (same content hashes)"
                    )
                else:
                    changed = sorted(produced ^ baseline)
                    detail += "\n      bundle changed: " + ", ".join(changed[:6])
            if ok and not mergeable:
                # A clean build of the head says nothing about a PR GitHub cannot
                # merge, so the verdict has to override the build result.
                ok = False
                detail += "\n      no merge ref: GitHub cannot merge this PR cleanly"
            results.append((label, ok, detail))
    finally:
        prune(workdir)

    print("\n" + "=" * 60)
    for label, ok, detail in results:
        print(f"{'SAFE' if ok else 'UNSAFE'}  {label}\n      {detail.lstrip()}")
    failed = [label for label, ok, _ in results if not ok]
    print("=" * 60)
    if failed:
        print(f"\n{len(failed)} of {len(results)} unsafe to merge: {', '.join(failed)}")
        return 1
    print(f"\nAll {len(results)} safe to merge.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
