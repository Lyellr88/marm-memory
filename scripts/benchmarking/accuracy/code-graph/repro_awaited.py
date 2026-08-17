#!/usr/bin/env python3
"""Minimal reproduction: which Python call shapes does the engine record as CALLS?

WNA-3 in docs/current/code-graph-accuracy-benchmark.md says awaited calls are
recorded 29.8 points less often than plain ones, and that the mechanism is
unnamed. Counting more call sites cannot name it. This varies one property at a
time against a generated package small enough to read in full, so the result is a
trigger rather than a statistic.

Each probe is a caller whose name encodes its shape, calling exactly one target
named after it. A missing edge is therefore attributable to that one difference.

A first pass tested `await` alone and recorded every shape, which refutes
"awaited calls are dropped" as stated. The shapes below add what the real missed
call in server_stdio.py carries beyond an await: keyword arguments, a call spread
over several lines, a try block, and stacked decorators.

Runs against the engine CLI, not MARM: the finding is upstream, and an issue is
only actionable if it reproduces without this project in the picture. Indexes a
temp directory so it gets its own project and store, then deletes both.

    python scripts/benchmarking/accuracy/code-graph/repro_awaited.py
    python scripts/benchmarking/accuracy/code-graph/repro_awaited.py --keep
"""

import argparse
import asyncio
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store_cleanup import (
    drop_project,
    engine_binary,
    engine_cli,
    report_kept,
    succeeded,
)

# name -> caller source. The caller is call_<name> and its one target is
# target_<name>, so a missing edge is attributable to that shape alone.
SHAPES: dict[str, str] = {
    "sync_expr": """
def call_sync_expr():
    x = target_sync_expr()
    return x
""",
    "sync_return": """
def call_sync_return():
    return target_sync_return()
""",
    "await_assign": """
async def call_await_assign():
    x = await target_await_assign()
    return x
""",
    "await_return": """
async def call_await_return():
    return await target_await_return()
""",
    "await_expr": """
async def call_await_expr():
    await target_await_expr()
    return 1
""",
    "async_no_await": """
async def call_async_no_await():
    coro = target_async_no_await()
    return coro
""",
    "await_try": """
async def call_await_try():
    try:
        return await target_await_try()
    except ValueError:
        return None
""",
    "await_kwargs": """
async def call_await_kwargs():
    return await target_await_kwargs(action=1, name=2)
""",
    "await_kwargs_multiline": """
async def call_await_kwargs_multiline():
    return await target_await_kwargs_multiline(
        action=1,
        name=2,
        data=3,
        session_name=4,
    )
""",
    "await_try_kwargs_multiline": """
async def call_await_try_kwargs_multiline():
    try:
        return await target_await_try_kwargs_multiline(
            action=1,
            name=2,
            data=3,
        )
    except ValueError:
        return None
""",
    "decorated_await": """
@simple_decorator
async def call_decorated_await():
    return await target_decorated_await()
""",
    "decorated_await_kwargs_multiline": """
@simple_decorator
@second_decorator()
async def call_decorated_await_kwargs_multiline():
    try:
        return await target_decorated_await_kwargs_multiline(
            action=1,
            name=2,
            data=3,
        )
    except ValueError:
        return None
""",
    "decorated_sync": """
@simple_decorator
def call_decorated_sync():
    return target_decorated_sync()
""",
    "sync_kwargs_multiline": """
def call_sync_kwargs_multiline():
    return target_sync_kwargs_multiline(
        action=1,
        name=2,
    )
""",
}

DECORATORS = """def simple_decorator(fn):
    return fn


def second_decorator():
    def wrap(fn):
        return fn

    return wrap
"""

# The shapes above all import at the top of the module, relatively. Every real
# missed call in server_stdio.py does one of these three instead, so each gets its
# own module to keep import style from mixing with import position.
IMPORT_STYLES: dict[str, str] = {
    "relative_top": """from .targets import target_relative_top


async def call_relative_top():
    return await target_relative_top(action=1)
""",
    "absolute_top": """from pkg.targets import target_absolute_top


async def call_absolute_top():
    return await target_absolute_top(action=1)
""",
    "absolute_late": '''"""Import below module-level code, which is what earns a noqa: E402."""

import os

_MARKER = os.sep

from pkg.targets import target_absolute_late  # noqa: E402


async def call_absolute_late():
    return await target_absolute_late(action=1)
''',
    "function_body": """async def call_function_body():
    from pkg.targets import target_function_body

    return await target_function_body(action=1)
""",
}


ALL_PROBES = {**SHAPES, **IMPORT_STYLES}


def _is_async(name: str) -> bool:
    return "await" in ALL_PROBES[name]


def _write_package(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "deco.py").write_text(DECORATORS, encoding="utf-8")

    # *args/**kwargs so a target never fails to accept a shape's call, keeping the
    # signature from becoming a second variable.
    targets = [
        f"{'async def' if _is_async(name) else 'def'} target_{name}(*args, **kwargs):\n"
        f"    return {len(name)}\n"
        for name in ALL_PROBES
    ]
    (root / "targets.py").write_text("\n".join(targets), encoding="utf-8")

    imports = ", ".join(f"target_{n}" for n in SHAPES)
    body = [
        f"from .targets import {imports}",
        "from .deco import simple_decorator, second_decorator",
        "",
    ]
    body.extend(SHAPES.values())
    (root / "callers.py").write_text("\n".join(body), encoding="utf-8")

    # One module each, so import style and import position never mix.
    for name, source in IMPORT_STYLES.items():
        (root / f"imp_{name}.py").write_text(source, encoding="utf-8")


def _write_filler(root: Path, modules: int) -> None:
    """Unrelated modules, to move project size without touching the probes.

    Every probe shape is recorded in a 69-node project while the same shapes are
    missing from a 4,058-node one, so size is the remaining untested variable.
    The filler never references a probe, so any change in probe edges is
    attributable to scale alone.
    """
    filler = root / "filler"
    filler.mkdir(parents=True, exist_ok=True)
    (filler / "__init__.py").write_text("", encoding="utf-8")
    for i in range(modules):
        lines = [f"def filler_{i}_helper(x):\n    return x + {i}\n"]
        for j in range(6):
            lines.append(
                f"async def filler_{i}_fn_{j}(x):\n"
                f"    y = filler_{i}_helper(x)\n"
                f"    return await filler_{i}_fn_{(j + 1) % 6}(y) if x else y\n"
            )
        (filler / f"mod_{i:04d}.py").write_text("\n".join(lines), encoding="utf-8")


def _edges(store: Path) -> set[tuple[str, str]]:
    conn = sqlite3.connect(str(store))
    try:
        return {
            (s, t)
            for s, t in conn.execute(
                """SELECT s.name, t.name FROM edges e
                   JOIN nodes s ON s.id = e.source_id
                   JOIN nodes t ON t.id = e.target_id
                   WHERE e.type = 'CALLS'"""
            )
        }
    finally:
        conn.close()


def _run(args, cleanup_failed: list[str]) -> int:
    binary = engine_binary()
    if binary is None or not binary.exists():
        print("engine binary not found; run MARM once to download it")
        return 2

    work = Path(tempfile.mkdtemp(prefix="cga-repro-"))
    repo = work / "repro"
    _write_package(repo / "pkg")
    if args.filler:
        _write_filler(repo / "pkg", args.filler)
    subprocess.run(["git", "init", "-q", str(repo)], capture_output=True, timeout=60)

    project = None
    try:
        raw = engine_cli(
            binary, "index_repository", "--repo-path", str(repo), "--mode", "moderate"
        )
        indexed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        project = indexed.get("project")
        store = Path.home() / ".cache" / "codebase-memory-mcp" / f"{project}.db"
        if not store.exists():
            print(f"no store at {store}")
            return 2

        edges = _edges(store)
        print(f"indexed {indexed.get('nodes')} nodes, {indexed.get('edges')} edges\n")
        print(f"{'shape':34} {'awaited':>8} {'recorded':>9}")
        results = {
            name: (f"call_{name}", f"target_{name}") in edges for name in ALL_PROBES
        }
        for name in SHAPES:
            print(f"{name:34} {_is_async(name)!s:>8} {results[name]!s:>9}")
        print()
        print(f"{'import style':34} {'awaited':>8} {'recorded':>9}")
        for name in IMPORT_STYLES:
            print(f"{name:34} {_is_async(name)!s:>8} {results[name]!s:>9}")

        aw = [n for n in ALL_PROBES if _is_async(n)]
        pl = [n for n in ALL_PROBES if not _is_async(n)]
        print(
            f"\nawaited: {sum(results[n] for n in aw)}/{len(aw)}   "
            f"plain: {sum(results[n] for n in pl)}/{len(pl)}"
        )
        missed = [n for n, ok in results.items() if not ok]
        print(f"missed: {missed or 'none'}")
        return 0
    finally:
        # Same contract as pilot.py, via the shared helper: gated, confirmed
        # twice, and reported. An orphaned project here lands in the store a
        # running MARM is using, so a silent failure is not acceptable.
        issues: list[str] = []
        if project and not args.keep:
            status = asyncio.run(drop_project(project))
            print(f"cleanup: {status}")
            if not succeeded(status):
                issues.append(f"project {project}: {status}")
        if not args.keep:
            try:
                shutil.rmtree(work)
            except OSError as exc:
                issues.append(f"temp dir {work}: {exc}")
        else:
            report_kept(project, repo)
        cleanup_failed.extend(issues)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--keep",
        action="store_true",
        help="keep the generated files AND the indexed graph project (both need removing by hand afterwards)",
    )
    ap.add_argument(
        "--filler",
        type=int,
        default=0,
        help="pad the repo with N unrelated modules to test whether scale matters",
    )
    args = ap.parse_args()

    # Collected by _run's finally block so a leaked project fails the command,
    # matching pilot.py. A cleanup message nobody acts on is how a race stays
    # invisible.
    cleanup_failed: list[str] = []
    code = _run(args, cleanup_failed)
    if cleanup_failed:
        print("CLEANUP FAILED")
        for issue in cleanup_failed:
            print(f"    {issue}")
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
