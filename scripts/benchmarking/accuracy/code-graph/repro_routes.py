#!/usr/bin/env python3
"""Executed minimal reproductions for the two route findings.

The drafts in docs/current/upstream/ were written from evidence gathered
against MARM itself, which is not an upstream-quality report: a maintainer needs the
smallest project that shows the behaviour, plus the command output it produces.
This builds exactly that project and runs the two commands against it.

  C4  get_architecture returns routes[].handler empty despite HANDLES edges
  C6  trace_path --mode cross_service never reaches the server handler

Nine lines of Python and eight of TypeScript, one route, one client call. Runs
against the engine CLI so nothing about MARM is in the picture. Prints the
verbatim output to paste into an issue.

C4 reproduces here, on 0.9.0, 0.10.5 and 0.10.6 alike. C6 does not, and the run says
so: no client-side Route node is created, so there is nothing to mismatch and the trace
measures client-call recognition instead of the route-key join. Exit 3 marks that,
because a fixture that looks like it tests C6 while testing something else is worse
than no fixture. C6 is not worth chasing further, having turned out to be already filed
upstream twice over; see docs/current/upstream/engine-fork-scope.md.

    python scripts/benchmarking/accuracy/code-graph/repro_routes.py
    python scripts/benchmarking/accuracy/code-graph/repro_routes.py --keep

Exit: 0 both findings reproduced, 1 cleanup failed, 2 setup or engine failed,
3 C4 reproduced but the C6 precondition was not met, 4 C4 did not reproduce.
"""

import argparse
import asyncio
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store_cleanup import (
    drop_project,
    engine_binary,
    engine_cli,
    gated,
    git_init,
    report_kept,
    succeeded,
)

SERVER_PY = """from fastapi import APIRouter

router = APIRouter()


@router.get("/api/memories/{memory_id}")
async def get_memory(memory_id: str):
    return {"id": memory_id}
"""

# The client must call through a local wrapper that concatenates a base prefix and
# forwards a method variable to fetch. That is the shape the engine recognises, and
# it is the shape that produces the mismatch: the literal path at the wrapper call
# site carries no prefix, and a variable `method` cannot be read statically, so the
# client node is keyed __route__ANY__/memories/{} against the server's
# __route__GET__/api/memories/{}. A bare fetch("/api/memories/:id", {method: "GET"})
# at the call site produces no client route node at all.
CLIENT_TS = """const BASE = "http://localhost:8080";

async function request<T>(method: string, path: string): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, { method });
  return res.json() as Promise<T>;
}

export async function getMemory(id: string) {
  return request<unknown>("GET", `/memories/${id}`);
}

export async function listMemories() {
  return request<unknown>("GET", "/memories");
}
"""


def _build(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "server.py").write_text(SERVER_PY, encoding="utf-8")
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "client.ts").write_text(CLIENT_TS, encoding="utf-8")
    # Project markers, in case the TypeScript side is only analysed inside a
    # recognised project. Without them a lone .ts file produced no client-side
    # route node at all.
    (repo / "package.json").write_text(
        '{"name": "repro", "version": "1.0.0", "type": "module"}\n', encoding="utf-8"
    )
    (repo / "tsconfig.json").write_text(
        '{"compilerOptions": {"target": "ES2020", "module": "ESNext"},'
        ' "include": ["src"]}\n',
        encoding="utf-8",
    )
    git_init(repo)


def _as_json(raw: str) -> dict | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


def _rows(value) -> list[dict]:
    """Flatten one 0.10.5 columnar section into dicts.

    With --format json the engine returns {cols, rows} or {cols, groups}, where a
    group's qn_prefix is the qualified-name stem for every row under it. Older engines
    returned lists of dicts, so both shapes are accepted.
    """
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if not isinstance(value, dict):
        return []
    cols = value.get("cols") or []
    out = []
    for row in value.get("rows") or []:
        out.append(dict(zip(cols, row)))
    for group in value.get("groups") or []:
        prefix = group.get("qn_prefix") or ""
        for row in group.get("rows") or []:
            item = dict(zip(cols, row))
            item["group"] = prefix
            out.append(item)
    return out


def _handles_edges(store: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(str(store))
    try:
        return list(
            conn.execute(
                """SELECT s.name, t.qualified_name FROM edges e
                   JOIN nodes s ON s.id = e.source_id
                   JOIN nodes t ON t.id = e.target_id
                   WHERE e.type = 'HANDLES'"""
            )
        )
    finally:
        conn.close()


def _route_keys(store: Path) -> list[str]:
    if not store.exists():
        return []
    conn = sqlite3.connect(str(store))
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT qualified_name FROM nodes WHERE label='Route' "
                "ORDER BY qualified_name"
            )
        ]
    finally:
        conn.close()


def _run(args, cleanup_failed: list[str]) -> int:
    binary = Path(args.binary) if args.binary else engine_binary()
    if binary is None or not binary.exists():
        print("engine binary not found; run MARM once to download it")
        return 2
    print(f"# engine: {binary}")

    work = Path(tempfile.mkdtemp(prefix="cga-routes-"))
    repo = work / "repro"
    project = None
    try:
        # Inside the cleanup scope: a failed setup used to leave the tree behind.
        try:
            _build(repo)
        except (OSError, RuntimeError) as exc:
            print(f"SETUP FAILED: {exc}")
            return 2

        # Gated: this writes the shared project list a running MARM is reading.
        raw = asyncio.run(
            gated(
                f"cga_routes_index:{repo.name}",
                engine_cli,
                binary,
                "index_repository",
                "--repo-path",
                str(repo),
                "--mode",
                "moderate",
            )
        )
        indexed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        project = indexed.get("project")
        print(
            f"# indexed: {indexed.get('nodes')} nodes, {indexed.get('edges')} edges\n"
        )

        store = Path.home() / ".cache" / "codebase-memory-mcp" / f"{project}.db"

        print("## C4: get_architecture routes[]")
        # 0.10.5 defaults to prefix-grouped text and returns a summary without
        # `routes` unless the aspect is named, so both flags are load-bearing.
        # Raw-JSON args, not flags: the CLI publishes no --format flag for this
        # tool even though the MCP surface accepts the field, and without it the
        # reply is prefix-grouped text. Naming the aspect is also required, since
        # 0.10.5 returns a summary that omits `routes` when aspects is omitted.
        arch_raw = engine_cli(
            binary,
            "get_architecture",
            json.dumps({"project": project, "aspects": ["routes"], "format": "json"}),
        )
        arch = _as_json(arch_raw)
        if arch is None:
            print(f"ENGINE OUTPUT NOT JSON:{chr(10)}{arch_raw}")
            return 2
        routes = _rows(arch.get("routes"))
        print(json.dumps(routes, indent=2))
        filled = [r for r in routes if (r.get("handler") or "").strip()]
        print(f"\nroutes: {len(routes)}   with non-empty handler: {len(filled)}")
        # C4 reproduces only when routes came back AND none carry a handler. No
        # routes at all is an indexing problem, not the finding; handlers populated
        # means it was fixed upstream, which must not read as a successful repro.
        c4_ready = bool(routes) and not filled

        print("\n## HANDLES edges actually in the store")
        edges = _handles_edges(store) if store.exists() else []
        for src, dst in edges:
            print(f"  {src} -> {dst}")
        print(f"HANDLES edges: {len(edges)}")

        print("\n## C6: trace_path --mode cross_service from getMemory")
        trace_args = (
            "trace_path",
            "--function-name",
            "getMemory",
            "--project",
            project,
            "--mode",
            "cross_service",
            "--depth",
            "4",
            "--include-evidence",
            "true",
        )
        # Both encodings: the text is what a maintainer reads in an issue, the
        # JSON is what the assertion below can be trusted against.
        print(engine_cli(binary, *trace_args))
        trace = _as_json(engine_cli(binary, *trace_args, "--format", "json")) or {}
        print(json.dumps(trace, indent=2))
        callees = _rows(trace.get("callees"))
        reached = [c for c in callees if c.get("name") == "get_memory"]
        print(f"{chr(10)}reached the Python handler: {bool(reached)}")

        print("\n## Route node keys")
        route_keys = _route_keys(store)
        for qname in route_keys:
            print(f"  {qname}")

        c6_ready = any("__route__ANY__" in q for q in route_keys)
        print("\n## Reproduction status")
        print(f"  C4 (routes returned, no handler populated): {c4_ready}")
        print(f"  C6 (a client-side route node exists):       {c6_ready}")

        if not c4_ready:
            print(
                "\n"
                "C4 NOT REPRODUCED. Either no routes came back, which is an indexing\n"
                "problem rather than the finding, or a handler was populated, which\n"
                "means the defect was fixed upstream. Re-check the engine version and\n"
                "the issue tracker before filing: an earlier draft in this repo was\n"
                "written against a version that had already fixed it."
            )
        if not c6_ready:
            print(
                "\n"
                "C6 NOT REPRODUCED, and this is expected. Only server-declared routes\n"
                "were indexed, so the trace above measures whether the client call was\n"
                "recognised at all, NOT the __route__ANY__ to __route__GET__ join\n"
                "failure it is meant to show. Two client shapes have been tried here, a\n"
                "bare fetch() at the call site and the request(method, path) wrapper\n"
                "above; neither produces a client route node in a two-file project,\n"
                "while the real project's marm-api.ts produces sixteen. Upstream #1147\n"
                "is the likeliest reason, a template literal over a module constant not\n"
                "being extracted. C6 itself is already filed upstream as #1611 and\n"
                "#678, so C4 above is the only finding this fixture needs to carry."
            )
        if not c4_ready:
            return 4
        return 0 if c6_ready else 3
    finally:
        issues: list[str] = []
        if project and not args.keep:
            status = asyncio.run(drop_project(project))
            print(f"\ncleanup: {status}")
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
        "--binary",
        help="engine executable to run instead of the pinned one, for checking "
        "whether a candidate release still reproduces before an issue is filed",
    )
    ap.add_argument(
        "--keep",
        action="store_true",
        help="keep the generated files AND the indexed graph project (both need removing by hand afterwards)",
    )
    args = ap.parse_args()

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
