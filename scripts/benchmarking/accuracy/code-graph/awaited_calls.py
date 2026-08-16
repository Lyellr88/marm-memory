#!/usr/bin/env python3
"""Does the code graph record awaited calls as reliably as plain ones?

Compares call edges in the graph against call sites resolved from Python's own
`ast`, matched by qualified name rather than by bare name.

Bare-name matching is what an earlier throwaway version of this did, and it is
wrong in both directions: same-named functions in different modules collapse into
one, so a call resolved against the wrong definition scores as a hit. That biases
recall upward. Every pair here is resolved through the importing file's own import
table and matched on a module-qualified suffix.

Only pairs where BOTH ends resolve to an indexed graph symbol are counted. Calls
into builtins, the stdlib, and third-party packages are excluded: those were never
graph nodes, so counting them would report a low rate that means nothing.

Usage, from repo root:
    python scripts/benchmarking/accuracy/code-graph/awaited_calls.py
    python scripts/benchmarking/accuracy/code-graph/awaited_calls.py --db <path> --json out.json

Reads the graph store directly. That is deliberate and is the exception to the
tool-surface rule in the spec: no public tool enumerates every call edge, and this
measures the graph's contents rather than what a caller receives.
"""

import argparse
import ast
import json
import platform
import sqlite3
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "marm-mcp-server"
STORE_DIR = Path.home() / ".cache" / "codebase-memory-mcp"


@dataclass
class CallSite:
    caller: str
    callee: str
    awaited: bool


@dataclass
class FileScan:
    module: str
    imports: dict[str, str] = field(default_factory=dict)
    sites: list[CallSite] = field(default_factory=list)


def _store_for_repo() -> Path | None:
    """The engine store for this checkout, found rather than hard-coded.

    The engine names each store after the mangled absolute repo path, so any
    literal default only works on the machine that wrote it. Matching on the
    mangled form keeps this runnable from any clone.
    """
    key = str(REPO_ROOT).replace("\\", "-").replace("/", "-").replace(":", "")
    candidate = STORE_DIR / f"{key}.db"
    if candidate.exists():
        return candidate
    tail = REPO_ROOT.name.lower()
    matches = [
        p
        for p in STORE_DIR.glob("*.db")
        if p.stem.lower().endswith(tail) and p.stem != "_config"
    ]
    return matches[0] if len(matches) == 1 else None


def _provenance(db: Path) -> dict:
    """Recorded with every result set. Engine accuracy is not under MARM's control,
    so a number with no engine version attached is worthless six months on."""

    def _git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", "-C", str(REPO_ROOT), *args],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    try:
        sys.path.insert(0, str(PACKAGE_ROOT))
        from marm_graph.config import settings as gs

        engine = gs.PINNED_CBM_VERSION
    except Exception:
        engine = "unknown"

    return {
        "commit": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "engine_version": engine,
        "os": f"{platform.system()} {platform.release()}",
        "store": str(db),
        "source": "direct graph-store read, NOT a public-tool result",
        "population": (
            "direct-name calls only (ast.Name); attribute calls excluded because "
            "resolving their owner needs type inference. Both ends must resolve to "
            "exactly one indexed graph symbol."
        ),
    }


def _module_of(path: Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(parts)


class _Scanner(ast.NodeVisitor):
    """Collects the import table and every resolvable call site in one file."""

    def __init__(self, module: str) -> None:
        self.out = FileScan(module=module)
        self._stack: list[str] = []
        self._awaited: set[int] = set()

    # ── imports ────────────────────────────────────────────────────
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.out.imports[alias.asname or alias.name.split(".")[0]] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # Relative imports resolve against this file's own package, which is what
        # makes `from ..services.analytics import track_usage` resolvable at all.
        base = node.module or ""
        if node.level:
            owner = self.out.module.split(".")
            trim = node.level if self.out.module else 0
            prefix = owner[: max(0, len(owner) - trim)]
            base = ".".join([*prefix, base]) if base else ".".join(prefix)
        for alias in node.names:
            self.out.imports[alias.asname or alias.name] = f"{base}.{alias.name}"

    # ── scopes ─────────────────────────────────────────────────────
    def _scoped(self, node) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    visit_ClassDef = _scoped
    visit_FunctionDef = _scoped
    visit_AsyncFunctionDef = _scoped

    # ── calls ──────────────────────────────────────────────────────
    def visit_Await(self, node: ast.Await) -> None:
        if isinstance(node.value, ast.Call):
            self._awaited.add(id(node.value))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        if not self._stack or not isinstance(node.func, ast.Name):
            # Attribute calls need type inference to resolve an owner, which is
            # beyond ast. Excluded rather than guessed.
            return
        caller = f"{self.out.module}.{'.'.join(self._stack)}"
        # Imported name first, otherwise assume the same module. Without the
        # fallback only cross-module imported calls are measured, which silently
        # drops every same-file call and makes the population unrepresentative.
        target = self.out.imports.get(node.func.id) or (
            f"{self.out.module}.{node.func.id}"
        )
        self.out.sites.append(
            CallSite(caller=caller, callee=target, awaited=id(node) in self._awaited)
        )


def _graph(db: Path) -> tuple[dict[str, set[str]], set[tuple[str, str]]]:
    """Symbol suffix index, and the set of recorded CALLS pairs by qualified name."""
    conn = sqlite3.connect(str(db))
    by_suffix: dict[str, set[str]] = {}
    for qname, name in conn.execute(
        "SELECT qualified_name, name FROM nodes WHERE label IN ('Function','Method')"
    ):
        if not qname or not name:
            continue
        by_suffix.setdefault(name, set()).add(qname)
    edges = {
        (s, t)
        for s, t in conn.execute(
            """SELECT s.qualified_name, t.qualified_name FROM edges e
               JOIN nodes s ON s.id = e.source_id
               JOIN nodes t ON t.id = e.target_id
               WHERE e.type = 'CALLS'"""
        )
    }
    conn.close()
    return by_suffix, edges


def _resolve(dotted: str, by_suffix: dict[str, set[str]]) -> str | None:
    """A graph qualified_name for a dotted Python path, or None if ambiguous.

    The graph prefixes qualified names with the project and the on-disk directory,
    so matching is by suffix. A dotted path that matches more than one symbol is
    dropped: guessing between them is exactly the error bare-name matching makes.
    """
    leaf = dotted.rsplit(".", 1)[-1]
    candidates = by_suffix.get(leaf)
    if not candidates:
        return None
    tail = dotted.replace(".", "/")
    hits = {q for q in candidates if q.replace(".", "/").endswith(tail)}
    return next(iter(hits)) if len(hits) == 1 else None


def analyse(db: Path) -> dict:
    by_suffix, edges = _graph(db)
    pairs: dict[tuple[str, str], bool] = {}
    unresolved = 0

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "build" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        scanner = _Scanner(_module_of(path))
        scanner.visit(tree)
        for site in scanner.out.sites:
            caller = _resolve(site.caller, by_suffix)
            callee = _resolve(site.callee, by_suffix)
            if not caller or not callee:
                unresolved += 1
                continue
            key = (caller, callee)
            pairs[key] = pairs.get(key, False) or site.awaited

    counts: Counter = Counter()
    misses: dict[str, list[str]] = {"awaited": [], "plain": []}
    for (caller, callee), awaited in pairs.items():
        hit = (caller, callee) in edges
        counts[("awaited" if awaited else "plain", hit)] += 1
        if not hit:
            bucket = misses["awaited" if awaited else "plain"]
            if len(bucket) < 10:
                bucket.append(f"{caller.split('.')[-1]} -> {callee.split('.')[-1]}")

    out = {
        "provenance": _provenance(db),
        "resolved_pairs": len(pairs),
        "unresolved_sites": unresolved,
    }
    for shape in ("plain", "awaited"):
        hit, miss = counts[(shape, True)], counts[(shape, False)]
        total = hit + miss
        out[shape] = {
            "recorded": hit,
            "missed": miss,
            "recall": round(hit / total, 3) if total else None,
        }
    out["sample_misses"] = misses
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        type=Path,
        help="graph store to read; omit to pick the store for this repo",
    )
    ap.add_argument("--json", type=Path, help="also write raw results here")
    args = ap.parse_args()

    db = args.db or _store_for_repo()
    if db is None:
        print(f"no graph store found for {REPO_ROOT} under {STORE_DIR}; pass --db")
        return 2
    if not db.exists():
        print(f"no graph store at {db}")
        return 2

    r = analyse(db)
    print(
        f"resolved call pairs: {r['resolved_pairs']}  (unresolved sites: {r['unresolved_sites']})\n"
    )
    print(f"{'shape':10} {'recorded':>9} {'missed':>7} {'recall':>8}")
    for shape in ("plain", "awaited"):
        d = r[shape]
        print(f"{shape:10} {d['recorded']:9} {d['missed']:7} {d['recall']!s:>8}")
    if r["awaited"]["recall"] is not None and r["plain"]["recall"] is not None:
        print(
            f"\nawaited penalty: {r['plain']['recall'] - r['awaited']['recall']:+.3f}"
        )
    print("\nsample awaited misses:")
    for line in r["sample_misses"]["awaited"]:
        print(f"  {line}")

    if args.json:
        args.json.write_text(json.dumps(r, indent=2), encoding="utf-8")
        print(f"\nraw results: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
