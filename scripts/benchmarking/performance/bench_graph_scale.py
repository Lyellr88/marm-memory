#!/usr/bin/env python3
"""Throughput and correctness of a cold graph index on a ~1M-line synthetic tree.

The 1M-line figure quoted in docs/current/code-graph-accuracy-benchmark.md was
measured ad hoc and had no harness, so it could not be re-run against a new engine
build. This is that harness.

Two things are measured together on purpose. Throughput alone is what made the
original number misleading: it was taken on a tree whose calls were all
intra-module, so every edge resolved trivially and the resolver was never
exercised. Here each module also calls into two others through absolute imports,
and the run asserts those cross-module edges exist before reporting a rate. A fast
index of a tree the resolver silently gave up on is not a result.

The package is generated one directory below the repository root, which is the
layout that lost absolute-import edges entirely on engine 0.9.0. Keeping it nested
means a regression there shows up as a correctness failure at scale rather than
passing unnoticed.

    python bench_graph_scale.py --binary <path-to-engine.exe>
    python bench_graph_scale.py --binary <path> --target-lines 250000   # quick pass

Takes a binary path rather than resolving the installed package, so two engine
versions can be compared in one sitting without touching the project's pin.
"""

import argparse
import asyncio
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[3] / "marm-mcp-server"))
sys.path.insert(0, str(_HERE.parents[1] / "accuracy" / "code-graph"))

from store_cleanup import gated  # noqa: E402

STORE_DIR = Path.home() / ".cache" / "codebase-memory-mcp"

# Functions per module, and how many lines each generated function costs. Kept
# explicit because the line target is met by module count, so both feed the
# arithmetic below.
FUNCS_PER_MODULE = 30
LINES_PER_FUNC = 7
LINES_PER_MODULE_OVERHEAD = 4

PROBE_COUNT = 12


def _module_source(pkg: str, index: int, peers: tuple[int, int]) -> str:
    """One module: local helpers, intra-module calls, and calls into two peers."""
    a, b = peers
    lines = [
        f"from {pkg}.mod_{a:05d} import entry_{a:05d}",
        f"from {pkg}.mod_{b:05d} import entry_{b:05d}",
        "",
        "",
        f"def helper_{index:05d}(x):",
        f"    return x + {index}",
        "",
        "",
        f"async def entry_{index:05d}(x):",
        f"    y = helper_{index:05d}(x)",
        f"    z = await entry_{a:05d}(y) if y else y",
        f"    w = await entry_{b:05d}(z) if z else z",
        "    return w",
        "",
    ]
    for j in range(FUNCS_PER_MODULE):
        lines += [
            "",
            f"async def work_{index:05d}_{j:02d}(x, flag=False):",
            f"    total = helper_{index:05d}(x)",
            "    if flag:",
            f"        total = await entry_{a:05d}(total)",
            "    return total",
            "",
        ]
    return "\n".join(lines) + "\n"


def generate(
    root: Path, target_lines: int, nest: str
) -> tuple[int, int, list[tuple[int, int, int]]]:
    """Write the tree. Returns (modules, lines, probes as (index, peer_a, peer_b))."""
    pkg_name = "bigpkg"
    base = root / nest if nest else root
    pkg = base / pkg_name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    per_module = (
        FUNCS_PER_MODULE * LINES_PER_FUNC
        + LINES_PER_MODULE_OVERHEAD
        + LINES_PER_FUNC * 2
    )
    modules = max(8, target_lines // per_module)

    lines = 0
    peers_by_index: dict[int, tuple[int, int]] = {}
    for i in range(modules):
        peers = ((i + 1) % modules, (i + 7) % modules)
        peers_by_index[i] = peers
        src = _module_source(pkg_name, i, peers)
        (pkg / f"mod_{i:05d}.py").write_text(src, encoding="utf-8")
        lines += src.count("\n")

    subprocess.run(["git", "init", "-q", str(root)], capture_output=True, timeout=120)

    # Each probe carries the two peers its module actually calls, so verification
    # can demand those exact edges. Accepting any entry_* target passes on a wrong
    # edge, which is the failure this whole harness exists to refuse.
    step = max(1, modules // PROBE_COUNT)
    probes = [(i, *peers_by_index[i]) for i in range(0, modules, step)][:PROBE_COUNT]
    return modules, lines, probes


def cli(binary: Path, *args: str, timeout: float) -> tuple[str, float]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [str(binary), "cli", *args], capture_output=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return f"__timeout__ after {timeout}s", time.monotonic() - start
    elapsed = time.monotonic() - start
    if proc.returncode:
        tail = proc.stderr.decode(errors="replace").strip()[-500:]
        return f"__error__ exit {proc.returncode}: {tail}", elapsed
    return proc.stdout.decode(errors="replace"), elapsed


def _json(raw: str) -> dict:
    return json.loads(raw[raw.find("{") : raw.rfind("}") + 1])


def cross_module_edges(
    store: Path, probes: list[tuple[int, int, int]]
) -> tuple[int, int, list[str], str | None]:
    """Verify each probe's two exact peer edges.

    Returns (probes fully satisfied, probes checked, missing edge descriptions,
    error). Both peers must be present: a probe module calls exactly entry_<a> and
    entry_<b>, so demanding those names is the difference between proving the
    resolver worked and proving it produced some edge.
    """
    if not store.exists():
        return 0, len(probes), [], f"no store at {store}"
    conn = sqlite3.connect(str(store))
    try:
        satisfied = 0
        missing: list[str] = []
        for index, peer_a, peer_b in probes:
            caller = f"entry_{index:05d}"
            absent = [
                f"{caller} -> entry_{peer:05d}"
                for peer in (peer_a, peer_b)
                if not conn.execute(
                    """SELECT 1 FROM edges e
                       JOIN nodes s ON s.id = e.source_id
                       JOIN nodes t ON t.id = e.target_id
                       WHERE e.type = 'CALLS' AND s.name = ? AND t.name = ?
                       LIMIT 1""",
                    (caller, f"entry_{peer:05d}"),
                ).fetchone()
            ]
            if absent:
                missing.extend(absent)
            else:
                satisfied += 1
        return satisfied, len(probes), missing, None
    except sqlite3.Error as exc:
        return 0, len(probes), [], f"store not readable: {exc}"
    finally:
        conn.close()


def _delete_and_confirm(binary: Path, project: str) -> str:
    for attempt in range(4):
        cli(binary, "delete_project", "--project", project, timeout=300.0)
        time.sleep(1.0)
        listing, _ = cli(binary, "list_projects", timeout=120.0)
        if listing.startswith("__"):
            return f"could not verify: {listing}"
        if project not in listing:
            time.sleep(0.75)
            again, _ = cli(binary, "list_projects", timeout=120.0)
            if project not in again:
                return "deleted" if attempt == 0 else f"deleted after {attempt + 1}"
    return "STILL PRESENT, remove by hand"


def drop(binary: Path, project: str) -> str:
    """Delete under the gate, same as every other store mutation.

    A delete landing while a poller is inside index_repository is undone when that
    index writes the project back, which is why the gate covers deletes too.
    """
    from marm_mcp_server.core.graph_index_lock import GraphIndexBusy

    try:
        return asyncio.run(
            gated(f"cga_scale_cleanup:{project}", _delete_and_confirm, binary, project)
        )
    except GraphIndexBusy as exc:
        return f"gate busy ({exc}), remove {project} by hand"


def report_query_latency(
    binary: Path, project: str, probes: list[tuple[int, int, int]]
) -> None:
    """Time queries over one persistent stdio child, which is MARM's real path.

    A fresh `cli` invocation per query spawns and tears down a daemon each time,
    which measures process startup rather than the query: three different calls all
    came back at 5.0s. MARM holds one child open for the process lifetime, so this
    reuses that client and reports first-call and warm timings separately.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "marm-mcp-server"))
    try:
        from marm_graph.core.cbm_client import CbmClient
    except ImportError as exc:
        print(f"\nquery latency: skipped, marm_graph not importable ({exc})")
        return

    client = CbmClient([str(binary)])
    calls = [
        ("search_graph", {"query": "entry_00000", "project": project}),
        (
            "trace_path",
            {
                "function_name": f"entry_{probes[len(probes) // 2][0]:05d}",
                "project": project,
                "direction": "inbound",
                "depth": 2,
            },
        ),
        ("get_architecture", {"project": project, "aspects": ["overview"]}),
    ]
    print("\nquery latency (persistent stdio child, as MARM uses it):")
    try:
        t0 = time.monotonic()
        client.start()
        print(f"  {'child startup':22} {time.monotonic() - t0:6.3f}s")
        for name, params in calls:
            timings = []
            status = "ok"
            for _ in range(3):
                t1 = time.monotonic()
                try:
                    client.call_tool(name, params, timeout=300.0)
                except Exception as exc:
                    status = f"error: {type(exc).__name__}: {exc}"[:120]
                    break
                timings.append(time.monotonic() - t1)
            if timings:
                print(
                    f"  {name:22} first={timings[0]:6.3f}s  "
                    f"best={min(timings):6.3f}s  {status}"
                )
            else:
                print(f"  {name:22} {status}")
    except Exception as exc:
        print(f"  client failed: {type(exc).__name__}: {exc}")
    finally:
        client.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", required=True, type=Path)
    ap.add_argument("--target-lines", type=int, default=1_000_000)
    ap.add_argument("--mode", default="moderate", choices=["fast", "moderate", "full"])
    ap.add_argument(
        "--nest",
        default="src",
        help="subdirectory for the package; empty string puts it at the repo root",
    )
    ap.add_argument("--index-timeout", type=float, default=3600.0)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    if not args.binary.exists():
        print(f"binary not found: {args.binary}")
        return 2

    # Warm-up. Each CLI invocation spawns a temporary daemon, and that startup
    # cost lands in whichever call pays it first. The query timings below still
    # include it, so read them as upper bounds rather than server-side latency.
    cli(args.binary, "list_projects", timeout=180.0)
    print(f"engine: {args.binary}")
    print(f"mode: {args.mode}   nest: {args.nest or '<repo root>'}")

    work = Path(tempfile.mkdtemp(prefix="cga-scale-"))
    repo = work / "bigrepo"
    print("\ngenerating ...")
    t0 = time.monotonic()
    modules, lines, probes = generate(repo, args.target_lines, args.nest)
    gen_s = time.monotonic() - t0
    src_bytes = sum(f.stat().st_size for f in repo.rglob("*.py"))
    print(
        f"  {modules:,} modules   {lines:,} lines   "
        f"{src_bytes / 1e6:.0f} MB source   in {gen_s:.0f}s"
    )

    project = None
    try:
        print("\nindexing (cold) ...")
        # Gated. AGENTS.md: every code-index call takes the graph gate, and this
        # writes the shared project list a running MARM is reading.
        raw, index_s = asyncio.run(
            gated(
                f"cga_scale_index:{repo.name}",
                cli,
                args.binary,
                "index_repository",
                "--repo-path",
                str(repo),
                "--mode",
                args.mode,
                timeout=args.index_timeout,
            )
        )
        if raw.startswith("__"):
            print(f"  INDEX FAILED after {index_s:.0f}s")
            print(f"  {raw}")
            return 1

        d = _json(raw)
        project = d.get("project")
        nodes, edges = d.get("nodes", 0), d.get("edges", 0)
        store = STORE_DIR / f"{project}.db"
        store_mb = store.stat().st_size / 1e6 if store.exists() else 0.0

        print(f"  indexed in {index_s:.1f}s")
        print(f"  nodes={nodes:,}  edges={edges:,}  skipped={d.get('skipped_count')}")
        print(f"  store={store_mb:,.0f} MB")

        # Correctness first, and no performance number before it passes. A rate
        # earned by skipping resolution is the exact result this harness exists to
        # refuse: engine 0.9.0 indexed this tree twice as fast as 0.10.5 while
        # resolving none of these edges.
        satisfied, total, missing, err = cross_module_edges(store, probes)
        print("\ncorrectness at scale:")
        if err:
            print(f"  cannot verify: {err}")
        else:
            print(f"  probes with both peer call edges: {satisfied}/{total}")
            for line in missing[:10]:
                print(f"    MISSING {line}")
            if len(missing) > 10:
                print(f"    ... and {len(missing) - 10} more")

        if err or satisfied < total:
            print(
                "\nRESOLVER DEGRADED AT SCALE. Throughput and latency are withheld:\n"
                "  a rate measured on a graph missing its cross-module edges is not a\n"
                "  performance result. Fix resolution, then re-run for a usable number."
            )
            return 1

        print(f"\nrate={lines / index_s:,.0f} lines/s   {nodes / index_s:,.0f} nodes/s")
        report_query_latency(args.binary, project, probes)
        return 0
    finally:
        if project and not args.keep:
            print(f"\ncleanup: {drop(args.binary, project)}")
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"\nkept: {repo}")
            if project:
                print(f"kept: graph project {project}")


if __name__ == "__main__":
    sys.exit(main())
