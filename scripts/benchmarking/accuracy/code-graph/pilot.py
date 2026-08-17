#!/usr/bin/env python3
"""Fresh-index pilot for the code graph accuracy benchmark.

Three probes, one per metric in docs/current/code-graph-accuracy-benchmark.md,
run before any ground-truth labeling is spent:

  C1  inbound reference recall       notebook_dispatch
  C4  route-to-handler exposure      marm_graph_architecture routes[].handler
  C6  cross-service path completion  getMemory (marm-console TypeScript)

Calls MARM's own graph tool functions, so graph_supervisor, tool_router, and the
response shaping are all exercised. It does NOT go over MCP transport, so
registration, schema validation, and serialization are not covered: this is the
service layer an MCP call lands on, not an MCP client.

Only what a caller receives counts as a result. SQLite inspection is diagnosis,
and the two genuinely disagree here, which is the point of C4.

Run from repo root:
    python scripts/benchmarking/accuracy/code-graph/pilot.py --isolate
    python scripts/benchmarking/accuracy/code-graph/pilot.py --json out.json

`--isolate` builds a git worktree at HEAD, indexes that path into its own project,
probes it, and tears both down. That is the reproducible mode and it never touches
the store your running MARM uses. Without it the live store is probed as-is, which
is fine for a quick look but is not a benchmark run: nothing guarantees the store
matches HEAD.

Exit code is non-zero when C1 misses its stop rule, when a probe could not run,
or when cleanup left a graph project or worktree behind. A run that measures
cleanly and then leaks a project has not succeeded.
"""

import argparse
import asyncio
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "marm-mcp-server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from store_cleanup import drop_project, succeeded  # noqa: E402

# C1. Two production callers, verified by hand: endpoints/notebook.py:24 for HTTP
# and server_stdio.py:259 for STDIO. Both are named marm_notebook and differ only
# by module, so the expectation is a qualified-name suffix per caller. A bare-name
# set of one collapsed them and scored recall 1.0 on whichever transport resolved,
# even when the other transport's edge was missing entirely.
#
# The five test callers are excluded because no caller can ask for them: the engine
# filters test files from traces, and GraphTraceRequest exposes no include_tests
# field, so they are unreachable through MARM's public surface at any setting.
C1_SYMBOL = "notebook_dispatch"
C1_EXPECTED_CALLERS = {
    "marm_mcp_server.server_stdio.marm_notebook",
    "marm_mcp_server.endpoints.notebook.marm_notebook",
}

# C6. The TypeScript client calls GET /api/memories/{memory_id} through a baseURL
# that strips the /api prefix. Completion means the trace reaches Python.
C6_SYMBOL = "getMemory"
C6_PYTHON_HANDLERS = {"get_memory", "read_memory", "get_memory_by_id"}


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd or REPO_ROOT), *args],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_checked(*args: str) -> str:
    """Empty string on success, otherwise the reason. For cleanup that must be seen."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return (
        ""
        if proc.returncode == 0
        else (proc.stderr.strip() or f"exit {proc.returncode}")
    )


def _provenance(isolated: bool, project: str) -> dict:
    try:
        from marm_graph.config import settings as gs

        engine = gs.PINNED_CBM_VERSION
    except Exception:
        engine = "unknown"
    return {
        "commit": _git("rev-parse", "--short", "HEAD"),
        "head_sha": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "engine_version": engine,
        "os": f"{platform.system()} {platform.release()} {platform.version()}",
        "index_mode": "moderate",
        "isolated_index": isolated,
        "project": project,
        "manifest_version": "pilot-2",
    }


class ProbeError(RuntimeError):
    """The graph could not answer. Distinct from the graph answering badly.

    Without this an unavailable backend returns {"status": "error"}, every probe
    then finds no callers and no routes, and the run reports three clean metric
    failures. That reads as evidence of a graph defect when it is evidence of
    nothing at all.
    """


def _checked(res: dict, tool: str) -> dict:
    if res.get("status") == "error":
        raise ProbeError(f"{tool}: {res.get('message') or res}")
    return res


def _names(entries) -> list[str]:
    out = []
    for item in entries or []:
        out.append(str(item.get("name", "")) if isinstance(item, dict) else str(item))
    return out


def _qualified_names(entries) -> list[str]:
    """Qualified name per entry, falling back to the bare name when absent.

    Two callers of notebook_dispatch share the bare name marm_notebook and differ
    only by module, so anything scored on names alone counts them as one.
    """
    out = []
    for item in entries or []:
        if isinstance(item, dict):
            out.append(str(item.get("qualified_name") or item.get("name", "")))
        else:
            out.append(str(item))
    return out


async def _resolve_project(tools, repo_path: Path) -> str | None:
    """Project name for a path, from the engine rather than a guessed key.

    The engine derives its key by mangling the absolute path, so hard-coding it
    only works on the machine it was written on.
    """
    res = await tools.marm_graph_index(action="list")
    want = str(repo_path).replace("\\", "/").rstrip("/").lower()
    for proj in res.get("projects") or []:
        root = str((proj or {}).get("root_path") or "").replace("\\", "/").rstrip("/")
        if root.lower() == want:
            return proj.get("name") or proj.get("project")
    return None


async def probe_c1(tools, project: str) -> dict:
    """Inbound reference recall. The baseline category, and the stop rule.

    Test callers are unreachable here by construction, not by choice: MARM's trace
    request has no include_tests field to pass. The number is what an agent gets
    when it asks "who calls this", which is the only number that matters.
    """
    res = _checked(
        await tools.marm_graph_trace(
            function_name=C1_SYMBOL, project=project, direction="inbound", depth=2
        ),
        "marm_graph_trace",
    )
    qualified = _qualified_names(res.get("callers"))
    # Suffix match: the engine prefixes every qualified name with the mangled
    # project path, which differs per machine and per isolated run.
    found = {
        want
        for want in C1_EXPECTED_CALLERS
        if any(q == want or q.endswith(f".{want}") for q in qualified)
    }
    return {
        "metric": "inbound reference recall",
        "symbol": C1_SYMBOL,
        "caller_count": len(qualified),
        "callers": sorted(set(_names(res.get("callers")))),
        "callers_qualified": sorted(set(qualified)),
        "expected": sorted(C1_EXPECTED_CALLERS),
        "missing_expected": sorted(C1_EXPECTED_CALLERS - found),
        "recall": round(len(found) / len(C1_EXPECTED_CALLERS), 3),
        "pass": not (C1_EXPECTED_CALLERS - found),
    }


async def probe_c4(tools, project: str) -> dict:
    """Route-to-handler exposure, measured on the field that carries it.

    An earlier version asked marm_code_lookup for the route path and called it
    linked when the same result set held both a Route and a Function. That was
    vacuous: BM25 returns whatever matches, and it scored `/tools/graph_index` as
    linked partly on `register_graph_tools`, which handles nothing.

    marm_graph_architecture returns routes[] with method, path, and handler, so
    the handler field is the actual public contract. marm_graph_impact cannot be
    used: it is a git-diff blast radius tool keyed on since/base_branch, not a
    per-symbol query. No trace mode follows HANDLES either.
    """
    res = _checked(
        await tools.marm_graph_architecture(project=project), "marm_graph_architecture"
    )
    routes = [r for r in (res.get("routes") or []) if isinstance(r, dict)]
    filled = [r for r in routes if (r.get("handler") or "").strip()]
    return {
        "metric": "route-to-handler exposure",
        "routes_returned": len(routes),
        "with_handler": len(filled),
        "exposure_rate": round(len(filled) / len(routes), 3) if routes else None,
        "sample": routes[:5],
        "pass": bool(routes) and len(filled) == len(routes),
    }


async def probe_c6(tools, project: str) -> dict:
    """Cross-service path completion."""
    res = _checked(
        await tools.marm_graph_trace(
            function_name=C6_SYMBOL,
            project=project,
            direction="both",
            depth=4,
            mode="cross_service",
        ),
        "marm_graph_trace",
    )
    callees = _names(res.get("callees"))
    reached_route = [c for c in callees if c.startswith("/")]
    reached_python = [c for c in callees if c in C6_PYTHON_HANDLERS]
    return {
        "metric": "cross-service path completion",
        "symbol": C6_SYMBOL,
        "callees": sorted(set(callees)),
        "reached_route": sorted(set(reached_route)),
        "reached_python_handler": sorted(set(reached_python)),
        "completed": bool(reached_python),
        "dead_ends_at_route": bool(reached_route) and not reached_python,
        "pass": bool(reached_python),
    }


async def _probe_all(tools, project: str, isolated: bool) -> dict:
    results = {"provenance": _provenance(isolated, project)}
    for name, fn in (("C1", probe_c1), ("C4", probe_c4), ("C6", probe_c6)):
        try:
            results[name] = await fn(tools, project)
        except ProbeError as exc:
            # Not a metric result. `pass` is left unset so nothing downstream can
            # read an execution failure as a measured miss.
            results[name] = {"execution_error": str(exc)}
        except Exception as exc:
            results[name] = {"execution_error": f"{type(exc).__name__}: {exc}"}
    return results


async def run(isolate: bool) -> dict:
    from marm_mcp_server.services import stdio_graph_tools as tools

    if not isolate:
        print("live store, NOT verified against HEAD. Use --isolate for a real run.\n")
        project = await _resolve_project(tools, REPO_ROOT)
        if project is None:
            return {"error": f"no indexed project for {REPO_ROOT}"}
        results = await _probe_all(tools, project, isolated=False)
        results["cleanup"] = {"ok": True, "issues": [], "note": "nothing to clean"}
        return results

    # A worktree gets its own path, so the engine files it under its own project
    # and its own database. The live store is never opened.
    work = Path(tempfile.mkdtemp(prefix="cga-bench-")) / "tree"
    project = None
    results: dict = {}
    try:
        print(f"worktree at {work}")
        _git("worktree", "add", "--detach", str(work), "HEAD")
        indexed = await tools.marm_graph_index(
            repo_path=str(work), action="index", mode="moderate"
        )
        project = indexed.get("project")
        if not project:
            results = {"error": f"isolated index failed: {indexed}"}
            return results
        print(
            f"indexed {project}: {indexed.get('nodes')} nodes, {indexed.get('edges')} edges\n"
        )
        results = await _probe_all(tools, project, isolated=True)
        return results
    finally:
        # Recorded on the result, not merely printed. A run that measures cleanly
        # and then strands a graph project or a repo checkout in temp has not
        # succeeded, and once C1 starts passing an exit code that ignores this
        # would go green while leaking a project per run.
        issues: list[str] = []
        if project:
            # Order matters. The supervisor's engine child holds the store open,
            # so a delete issued while it is alive leaves the database behind and
            # reports nothing. stop() is terminal, which is fine: this is the last
            # thing the run does.
            from marm_mcp_server.core.graph_supervisor import graph_supervisor

            graph_supervisor.stop()
            status = await drop_project(project)
            print(f"cleanup: {status}")
            if not succeeded(status):
                issues.append(f"project {project}: {status}")
        removed = _git_checked("worktree", "remove", "--force", str(work))
        if removed:
            issues.append(f"worktree {work}: {removed}")
        try:
            shutil.rmtree(work.parent)
        except OSError as exc:
            issues.append(f"temp dir {work.parent}: {exc}")
        # Mutating the object already bound for return, so this reaches the caller
        # whether the body returned normally or raised.
        results["cleanup"] = {"ok": not issues, "issues": issues}


def _report(r: dict) -> bool:
    if "error" in r:
        print(f"ERROR: {r['error']}")
        return False
    p = r["provenance"]
    print(f"commit {p['commit']} ({p['branch']})  engine {p['engine_version']}")
    print(f"isolated: {p['isolated_index']}  project {p['project']}\n")

    def _emit(probe: dict, header: str, body) -> None:
        """One path for all three, so a probe that never ran can never print a
        verdict. Printing FAIL for an unreachable backend is what makes a broken
        engine look like a measured graph defect."""
        print(header)
        if "execution_error" in probe:
            print(f"    DID NOT RUN  {probe['execution_error']}")
            print("    NO RESULT\n")
            return
        for line in body(probe):
            print(f"    {line}")
        print(f"    {'PASS' if probe.get('pass') else 'FAIL'}\n")

    def _c1_body(d: dict):
        yield f"callers returned: {d['caller_count']}  recall {d['recall']}"
        if d["missing_expected"]:
            yield f"MISSING {d['missing_expected']}"

    def _c4_body(d: dict):
        yield (
            f"routes returned: {d['routes_returned']}  "
            f"with handler: {d['with_handler']}  rate {d['exposure_rate']}"
        )

    def _c6_body(d: dict):
        yield f"reached route:   {d['reached_route']}"
        yield f"reached handler: {d['reached_python_handler']}"

    _emit(r["C1"], f"C1  inbound reference recall      {C1_SYMBOL}", _c1_body)
    _emit(r["C4"], "C4  route-to-handler exposure", _c4_body)
    _emit(r["C6"], f"C6  cross-service path completion  {C6_SYMBOL}", _c6_body)

    cleanup = r.get("cleanup") or {}
    if not cleanup.get("ok", True):
        print("CLEANUP FAILED")
        for issue in cleanup.get("issues", []):
            print(f"    {issue}")

    # An execution error is not a pass and not a measured failure. It exits
    # non-zero because the run produced no result, not because a metric missed, and
    # that holds for every probe: C4 and C6 failing their metric is a finding worth
    # recording, but C4 or C6 never running means the run is incomplete. Only C1
    # gates on its metric, per the stop rule.
    all_ran = all("execution_error" not in r[name] for name in ("C1", "C4", "C6"))
    return (
        all_ran
        and bool(r["C1"].get("pass"))
        and (r.get("cleanup") or {}).get("ok", True)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--isolate",
        action="store_true",
        help="index a git worktree into its own project; never touches the live store",
    )
    ap.add_argument("--json", type=Path, help="also write raw results here")
    args = ap.parse_args()

    results = asyncio.run(run(args.isolate))
    run_ok = _report(results)
    if args.json:
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nraw results: {args.json}")
    # Only C1 gates. C4 and C6 are known-failing and are the negative controls:
    # failing the run on them would make a green build impossible until upstream
    # changes, and would hide a C1 regression behind noise.
    return 0 if run_ok else 1


if __name__ == "__main__":
    sys.exit(main())
