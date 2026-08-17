#!/usr/bin/env python3
"""Executed minimal reproductions for the two route findings.

The drafts in docs/current/upstream/ were written from evidence gathered against
MARM itself, which is not an upstream-quality report: a maintainer needs the
smallest project that shows the behaviour, plus the command output it produces.
This builds exactly that project and runs the two commands against it.

  C4  get_architecture returns routes[].handler empty despite HANDLES edges
  C6  trace_path --mode cross_service never reaches the server handler

Nine lines of Python and eight of TypeScript, one route, one client call. Runs
against the engine CLI so nothing about MARM is in the picture. Prints the
verbatim output to paste into an issue.

    python scripts/benchmarking/accuracy/code-graph/repro_routes.py
    python scripts/benchmarking/accuracy/code-graph/repro_routes.py --keep
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

SERVER_PY = """from fastapi import APIRouter

router = APIRouter()


@router.get("/api/memories/{memory_id}")
async def get_memory(memory_id: str):
    return {"id": memory_id}
"""

# Literal path strings, matching how a generated API client is usually written.
# An interpolated template (`${BASE}/memories/${id}`) produces no client-side route
# node at all, so it cannot show the key mismatch this is meant to demonstrate.
CLIENT_TS = """export async function getMemory(id: string) {
  const res = await fetch("/api/memories/:id", { method: "GET" });
  return res.json();
}

export async function listMemories() {
  const res = await fetch("/api/memories", { method: "GET" });
  return res.json();
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
    subprocess.run(["git", "init", "-q", str(repo)], capture_output=True, timeout=60)


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


def _run(args, cleanup_failed: list[str]) -> int:
    binary = engine_binary()
    if binary is None or not binary.exists():
        print("engine binary not found; run MARM once to download it")
        return 2

    work = Path(tempfile.mkdtemp(prefix="cga-routes-"))
    repo = work / "repro"
    _build(repo)

    project = None
    try:
        raw = engine_cli(
            binary, "index_repository", "--repo-path", str(repo), "--mode", "moderate"
        )
        indexed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        project = indexed.get("project")
        print(
            f"# indexed: {indexed.get('nodes')} nodes, {indexed.get('edges')} edges\n"
        )

        store = Path.home() / ".cache" / "codebase-memory-mcp" / f"{project}.db"

        print("## C4: get_architecture routes[]")
        arch_raw = engine_cli(binary, "get_architecture", "--project", project)
        arch = json.loads(arch_raw[arch_raw.find("{") : arch_raw.rfind("}") + 1])
        routes = arch.get("routes") or []
        print(json.dumps(routes, indent=2))
        filled = [r for r in routes if (r.get("handler") or "").strip()]
        print(f"\nroutes: {len(routes)}   with non-empty handler: {len(filled)}")

        print("\n## HANDLES edges actually in the store")
        edges = _handles_edges(store) if store.exists() else []
        for src, dst in edges:
            print(f"  {src} -> {dst}")
        print(f"HANDLES edges: {len(edges)}")

        print("\n## C6: trace_path --mode cross_service from getMemory")
        trace_raw = engine_cli(
            binary,
            "trace_path",
            "--function-name",
            "getMemory",
            "--project",
            project,
            "--mode",
            "cross_service",
            "--depth",
            "4",
        )
        trace = json.loads(trace_raw[trace_raw.find("{") : trace_raw.rfind("}") + 1])
        print(json.dumps(trace, indent=2))
        reached = [
            c.get("name")
            for c in (trace.get("callees") or [])
            if isinstance(c, dict) and c.get("name") == "get_memory"
        ]
        print(f"\nreached the Python handler: {bool(reached)}")

        print("\n## Route node keys")
        if store.exists():
            conn = sqlite3.connect(str(store))
            for qname in conn.execute(
                "SELECT qualified_name FROM nodes WHERE label='Route' ORDER BY qualified_name"
            ):
                print(f"  {qname[0]}")
            conn.close()
        return 0
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
