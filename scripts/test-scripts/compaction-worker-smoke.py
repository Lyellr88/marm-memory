#!/usr/bin/env python3
"""HTTP smoke/stress test for compaction worker + write queue behavior."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = ROOT / "marm-mcp-server"


@dataclass
class HttpResult:
    status_code: int
    latency_ms: float
    body: dict | None = None
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise HTTP writes, write queue, and the compaction staging/apply "
            "pipeline against an isolated DB."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--auth-key", default="", help="Optional Bearer token.")
    parser.add_argument("--timeout-s", type=float, default=15.0)
    parser.add_argument("--spawn-server", action="store_true")
    parser.add_argument("--spawn-port", type=int, default=18021)
    parser.add_argument(
        "--db-path",
        default="",
        help=(
            "SQLite DB path for an already-running server. Required when not "
            "using --spawn-server."
        ),
    )
    parser.add_argument(
        "--server-preset",
        choices=["none", "swarm", "swarm-max", "trusted"],
        default="swarm",
    )
    parser.add_argument("--server-rate-limit-rpm", type=int, default=None)
    parser.add_argument("--queue-disabled", action="store_true")
    parser.add_argument("--max-queue-size", type=int, default=100)
    parser.add_argument("--http-writes", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=12)
    parser.add_argument("--cluster-size", type=int, default=3)
    parser.add_argument("--candidate-count", type=int, default=1)
    parser.add_argument("--session-prefix", default="smoke-compaction")
    parser.add_argument(
        "--skip-http-load",
        action="store_true",
        help="Skip /marm_context_log load phase and only test compaction tools.",
    )
    parser.add_argument(
        "--skip-stale-check",
        action="store_true",
        help="Skip stale candidate negative-path check.",
    )
    parser.add_argument(
        "--skip-cross-session-check",
        action="store_true",
        help="Skip cross-session isolation negative-path check.",
    )
    parser.add_argument(
        "--enable-auto-apply",
        action="store_true",
        help=(
            "Enable COMPACTION_AUTO_APPLY_ENABLED on spawned server and run the "
            "scheduler smoke path. Adds roughly one scheduler interval to runtime."
        ),
    )
    parser.add_argument(
        "--auto-apply-interval-minutes",
        type=int,
        default=1,
        help="COMPACTION_AUTO_APPLY_INTERVAL_MINUTES when --enable-auto-apply is set.",
    )
    parser.add_argument(
        "--auto-apply-wait-s",
        type=float,
        default=75.0,
        help="Seconds to wait for scheduler auto-apply when enabled.",
    )
    parser.add_argument(
        "--no-double-apply",
        action="store_true",
        help="Do not concurrently apply the first candidate twice.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "scripts" / "out" / "compaction-worker"),
    )
    parser.add_argument("--out-prefix", default="compaction-worker-smoke")
    parser.add_argument("--no-write-artifacts", action="store_true")
    parser.add_argument("--include-raw-http-results", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    return parser.parse_args()


def _json_request(
    method: str,
    url: str,
    payload: dict | None,
    auth_key: str,
    timeout_s: float,
) -> HttpResult:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return HttpResult(-1, 0.0, {"error": f"Unsupported URL scheme: {parsed.scheme}"})
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            body = json.loads(raw) if raw else None
            return HttpResult(resp.status, (time.perf_counter() - start) * 1000, body)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = None
        return HttpResult(
            exc.code,
            (time.perf_counter() - start) * 1000,
            body,
            raw or str(exc),
        )
    except Exception as exc:
        return HttpResult(-1, (time.perf_counter() - start) * 1000, None, str(exc))


def wait_for_health(base_url: str, timeout_s: float = 35.0) -> None:
    deadline = time.time() + timeout_s
    url = f"{base_url.rstrip('/')}/health"
    while time.time() < deadline:
        result = _json_request("GET", url, None, "", 1.5)
        if result.status_code == 200:
            return
        time.sleep(0.25)
    raise RuntimeError(f"Server did not become healthy in time: {url}")


def spawn_server(
    args: argparse.Namespace,
) -> tuple[subprocess.Popen, str, Path, Path, Path, Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="marm-compaction-smoke-"))
    db_path = temp_dir / "memory.db"
    analytics_path = temp_dir / "analytics.db"

    env = os.environ.copy()
    env["SERVER_HOST"] = "127.0.0.1"
    env["SERVER_PORT"] = str(args.spawn_port)
    env["MARM_DB_PATH"] = str(db_path)
    env["MARM_ANALYTICS_DB_PATH"] = str(analytics_path)
    env["WRITE_QUEUE_ENABLED"] = "0" if args.queue_disabled else "1"
    env["MAX_QUEUE_SIZE"] = str(args.max_queue_size)
    env["COMPACTION_ENABLED"] = "1"
    env["COMPACTION_AUTO_APPLY_ENABLED"] = "1" if args.enable_auto_apply else "0"
    env["COMPACTION_AUTO_APPLY_INTERVAL_MINUTES"] = str(
        args.auto_apply_interval_minutes
    )
    env.pop("MARM_API_KEY", None)
    stdout_log_path = temp_dir / "server-stdout.log"
    stderr_log_path = temp_dir / "server-stderr.log"

    cmd = [sys.executable, "-m", "marm_mcp_server"]
    if args.server_preset != "none":
        cmd.append(f"--{args.server_preset}")
    if args.server_rate_limit_rpm is not None:
        cmd.extend(["--rate-limit-rpm", str(args.server_rate_limit_rpm)])

    with stdout_log_path.open("wb") as stdout_fh, stderr_log_path.open(
        "wb"
    ) as stderr_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=str(SERVER_ROOT),
            env=env,
            stdout=stdout_fh,
            stderr=stderr_fh,
        )
    return (
        proc,
        f"http://127.0.0.1:{args.spawn_port}",
        temp_dir,
        db_path,
        stdout_log_path,
        stderr_log_path,
    )


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def post_context_log(
    base_url: str,
    session_name: str,
    index: int,
    auth_key: str,
    timeout_s: float,
) -> HttpResult:
    content = (
        f"compaction worker smoke load event {index}: "
        "same project same decision same implementation context"
    )
    return _json_request(
        "POST",
        f"{base_url.rstrip('/')}/marm_context_log",
        {"session_name": session_name, "content": content},
        auth_key,
        timeout_s,
    )


def run_http_load(args: argparse.Namespace, base_url: str, session_name: str) -> list[HttpResult]:
    results: list[HttpResult] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(
                post_context_log,
                base_url,
                session_name,
                i,
                args.auth_key,
                args.timeout_s,
            )
            for i in range(args.http_writes)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return results


from marm_mcp_server.core.consolidation import compute_content_hash


def compute_candidate_hash(source_memory_ids: list[str]) -> str:
    payload = json.dumps(sorted(source_memory_ids), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def insert_memory(conn: sqlite3.Connection, session_name: str, content: str) -> tuple[str, str]:
    mem_id = str(uuid.uuid4())
    content_hash = compute_content_hash(content)
    timestamp = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn.execute(
        """
        INSERT INTO memories
            (id, session_name, content, embedding, content_hash, timestamp,
             context_type, metadata, compaction_role, compacted_into)
        VALUES (?, ?, ?, NULL, ?, ?, 'general', '{}', NULL, NULL)
        """,
        (mem_id, session_name, content, content_hash, timestamp),
    )
    return mem_id, content_hash


def seed_candidate(
    db_path: Path,
    session_name: str,
    cluster_size: int,
    label: str,
    expires_hours: float = 168.0,
) -> dict:
    now = datetime.now(timezone.utc)
    source_ids: list[str] = []
    snapshot: dict[str, str] = {}
    preview: list[str] = []
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute(
            "INSERT OR REPLACE INTO sessions (session_name, last_accessed) VALUES (?, ?)",
            (session_name, now.isoformat()),
        )
        for i in range(cluster_size):
            content = (
                f"{label} clustered memory {i}: same incident, same fix, "
                "same follow-up details for compaction smoke validation."
            )
            mem_id, content_hash = insert_memory(conn, session_name, content)
            source_ids.append(mem_id)
            snapshot[mem_id] = content_hash
            preview.append(content[:120])

        candidate_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO compaction_staging
                (id, session_name, source_memory_ids, preview, suggested_summary,
                 status, candidate_hash, source_updated_at_snapshot,
                 expires_at, created_at, updated_at, reviewed_at)
            VALUES (?, ?, ?, ?, NULL, 'pending_summary', ?, ?, ?, ?, ?, NULL)
            """,
            (
                candidate_id,
                session_name,
                json.dumps(source_ids),
                json.dumps(preview),
                compute_candidate_hash(source_ids),
                json.dumps(snapshot),
                (now + timedelta(hours=expires_hours)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return {
        "candidate_id": candidate_id,
        "session_name": session_name,
        "source_memory_ids": source_ids,
        "snapshot": snapshot,
    }


def stage_candidate(
    args: argparse.Namespace,
    base_url: str,
    candidate: dict,
    summary: str,
) -> HttpResult:
    return _json_request(
        "POST",
        f"{base_url.rstrip('/')}/marm_compaction",
        {
            "action": "stage",
            "summaries": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "source_memory_ids": candidate["source_memory_ids"],
                    "suggested_summary": summary,
                }
            ]
        },
        args.auth_key,
        args.timeout_s,
    )


def apply_candidate(args: argparse.Namespace, base_url: str, candidate_id: str) -> HttpResult:
    return _json_request(
        "POST",
        f"{base_url.rstrip('/')}/marm_compaction",
        {"action": "apply", "candidate_id": candidate_id},
        args.auth_key,
        args.timeout_s,
    )


def get_candidates(args: argparse.Namespace, base_url: str) -> HttpResult:
    return _json_request(
        "POST",
        f"{base_url.rstrip('/')}/marm_compaction",
        {"action": "candidates"},
        args.auth_key,
        args.timeout_s,
    )


def get_compaction_status(args: argparse.Namespace, base_url: str) -> HttpResult:
    return _json_request(
        "POST",
        f"{base_url.rstrip('/')}/marm_compaction",
        {"action": "status"},
        args.auth_key,
        args.timeout_s,
    )


def verify_applied(db_path: Path, candidate: dict) -> dict:
    source_ids = candidate["source_memory_ids"]
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout = 10000")
        staging = conn.execute(
            "SELECT status FROM compaction_staging WHERE id = ?",
            (candidate["candidate_id"],),
        ).fetchone()
        placeholders = ",".join("?" * len(source_ids))
        source_rows = conn.execute(
            f"SELECT id, compaction_role, compacted_into FROM memories "
            f"WHERE id IN ({placeholders})",
            source_ids,
        ).fetchall()
        summary_ids = sorted({row[2] for row in source_rows if row[2]})
        summary_rows = []
        if summary_ids:
            summary_placeholders = ",".join("?" * len(summary_ids))
            summary_rows = conn.execute(
                f"SELECT id, compaction_role, metadata FROM memories "
                f"WHERE id IN ({summary_placeholders})",
                summary_ids,
            ).fetchall()
    return {
        "staging_status": staging[0] if staging else None,
        "source_count": len(source_rows),
        "sources_marked": sum(1 for row in source_rows if row[1] == "source" and row[2]),
        "summary_ids": summary_ids,
        "summary_count": len(summary_rows),
        "summary_roles": [row[1] for row in summary_rows],
    }


def verify_stale(db_path: Path, candidate_id: str) -> str | None:
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout = 10000")
        row = conn.execute(
            "SELECT status FROM compaction_staging WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    return row[0] if row else None


def mutate_source_hash(db_path: Path, source_id: str) -> None:
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute(
            "UPDATE memories SET content_hash = ? WHERE id = ?",
            (f"changed-{time.time_ns()}", source_id),
        )


def status_summary(results: list[HttpResult]) -> dict:
    counts = Counter(r.status_code for r in results)
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def count_session_rows(db_path: Path, session_name: str) -> int:
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?",
            (session_name,),
        ).fetchone()[0]


def run_compaction_flow(args: argparse.Namespace, base_url: str, db_path: Path) -> dict:
    session_name = f"{args.session_prefix}-compact-{time.time_ns()}"
    candidates = [
        seed_candidate(
            db_path,
            session_name,
            args.cluster_size,
            label=f"candidate-{idx}",
        )
        for idx in range(args.candidate_count)
    ]

    candidates_resp = get_candidates(args, base_url)
    visible_ids = {
        c.get("candidate_id")
        for c in (candidates_resp.body or {}).get("candidates", [])
    }
    missing_visible = [
        c["candidate_id"] for c in candidates if c["candidate_id"] not in visible_ids
    ]

    staged_results = []
    for idx, candidate in enumerate(candidates):
        staged_results.append(
            stage_candidate(
                args,
                base_url,
                candidate,
                summary=(
                    f"Compaction smoke summary {idx}: consolidated related "
                    "source memories while preserving traceability."
                ),
            )
        )

    staged_resp = get_compaction_status(args, base_url)
    staged_ids = set((staged_resp.body or {}).get("staged_candidate_ids", []))

    apply_results: list[HttpResult] = []
    if candidates and not args.no_double_apply:
        first_id = candidates[0]["candidate_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(apply_candidate, args, base_url, first_id),
                pool.submit(apply_candidate, args, base_url, first_id),
            ]
            for future in as_completed(futures):
                apply_results.append(future.result())
        remaining = candidates[1:]
    else:
        remaining = candidates

    for candidate in remaining:
        apply_results.append(apply_candidate(args, base_url, candidate["candidate_id"]))

    applied_verifications = [verify_applied(db_path, c) for c in candidates]
    return {
        "session_name": session_name,
        "seeded_candidate_ids": [c["candidate_id"] for c in candidates],
        "candidates_visible": not missing_visible,
        "missing_visible_candidate_ids": missing_visible,
        "stage_status_counts": status_summary(staged_results),
        "staged_visible_ids": sorted(staged_ids),
        "apply_status_counts": status_summary(apply_results),
        "apply_bodies": [r.body for r in apply_results],
        "applied_verifications": applied_verifications,
    }


def run_stale_flow(args: argparse.Namespace, base_url: str, db_path: Path) -> dict:
    session_name = f"{args.session_prefix}-stale-{time.time_ns()}"
    candidate = seed_candidate(
        db_path,
        session_name,
        args.cluster_size,
        label="stale-candidate",
    )
    stage = stage_candidate(
        args,
        base_url,
        candidate,
        "This summary should not apply after source hash mutation.",
    )
    mutate_source_hash(db_path, candidate["source_memory_ids"][0])
    applied = apply_candidate(args, base_url, candidate["candidate_id"])
    final_status = verify_stale(db_path, candidate["candidate_id"])
    return {
        "candidate_id": candidate["candidate_id"],
        "stage_status_code": stage.status_code,
        "stage_body": stage.body,
        "apply_status_code": applied.status_code,
        "apply_body": applied.body,
        "final_staging_status": final_status,
    }


def seed_cross_session_candidate(
    db_path: Path,
    primary_session: str,
    foreign_session: str,
    cluster_size: int,
) -> dict:
    now = datetime.now(timezone.utc)
    source_ids: list[str] = []
    snapshot: dict[str, str] = {}
    preview: list[str] = []
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout = 10000")
        for session_name in (primary_session, foreign_session):
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_name, last_accessed) "
                "VALUES (?, ?)",
                (session_name, now.isoformat()),
            )
        for i in range(cluster_size):
            session_name = foreign_session if i == cluster_size - 1 else primary_session
            content = (
                f"cross-session isolation memory {i}: this row should not be "
                "compacted across session boundaries."
            )
            mem_id, content_hash = insert_memory(conn, session_name, content)
            source_ids.append(mem_id)
            snapshot[mem_id] = content_hash
            preview.append(content[:120])

        candidate_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO compaction_staging
                (id, session_name, source_memory_ids, preview, suggested_summary,
                 status, candidate_hash, source_updated_at_snapshot,
                 expires_at, created_at, updated_at, reviewed_at)
            VALUES (?, ?, ?, ?, NULL, 'pending_summary', ?, ?, ?, ?, ?, NULL)
            """,
            (
                candidate_id,
                primary_session,
                json.dumps(source_ids),
                json.dumps(preview),
                compute_candidate_hash(source_ids),
                json.dumps(snapshot),
                (now + timedelta(hours=168)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return {
        "candidate_id": candidate_id,
        "session_name": primary_session,
        "foreign_session_name": foreign_session,
        "source_memory_ids": source_ids,
    }


def run_cross_session_flow(args: argparse.Namespace, base_url: str, db_path: Path) -> dict:
    primary_session = f"{args.session_prefix}-cross-a-{time.time_ns()}"
    foreign_session = f"{args.session_prefix}-cross-b-{time.time_ns()}"
    candidate = seed_cross_session_candidate(
        db_path,
        primary_session,
        foreign_session,
        args.cluster_size,
    )
    stage = stage_candidate(
        args,
        base_url,
        candidate,
        "This cross-session candidate should be rejected.",
    )
    final_status = verify_stale(db_path, candidate["candidate_id"])
    return {
        "candidate_id": candidate["candidate_id"],
        "session_name": primary_session,
        "foreign_session_name": foreign_session,
        "stage_status_code": stage.status_code,
        "stage_body": stage.body,
        "final_staging_status": final_status,
    }


def run_auto_apply_flow(args: argparse.Namespace, db_path: Path) -> dict:
    if not args.spawn_server:
        return {
            "enabled": False,
            "skipped_reason": "--enable-auto-apply requires --spawn-server",
        }

    session_name = f"{args.session_prefix}-auto-{time.time_ns()}"
    candidate = seed_candidate(
        db_path,
        session_name,
        args.cluster_size,
        label="auto-apply-candidate",
    )
    summary = "Scheduler auto-apply smoke summary with source traceability."
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute(
            "UPDATE compaction_staging "
            "SET suggested_summary = ?, status = 'summary_staged', updated_at = ? "
            "WHERE id = ?",
            (summary, now, candidate["candidate_id"]),
        )

    deadline = time.time() + args.auto_apply_wait_s
    verification = verify_applied(db_path, candidate)
    while time.time() < deadline and verification["staging_status"] != "applied":
        time.sleep(1.0)
        verification = verify_applied(db_path, candidate)

    return {
        "enabled": True,
        "candidate_id": candidate["candidate_id"],
        "wait_s": args.auto_apply_wait_s,
        "interval_minutes": args.auto_apply_interval_minutes,
        "verification": verification,
    }


def write_artifact(args: argparse.Namespace, payload: dict) -> Path:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    path = out_dir / f"{args.out_prefix}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    args = parse_args()
    if args.cluster_size < 1 or args.candidate_count < 1:
        print("--cluster-size and --candidate-count must be positive.")
        return 2
    if args.http_writes < 0 or args.concurrency <= 0:
        print("--http-writes must be >= 0 and --concurrency must be positive.")
        return 2
    if args.enable_auto_apply and not args.spawn_server:
        print("--enable-auto-apply requires --spawn-server.")
        return 2
    if args.auto_apply_interval_minutes <= 0 or args.auto_apply_wait_s <= 0:
        print("--auto-apply-interval-minutes and --auto-apply-wait-s must be positive.")
        return 2
    if not args.spawn_server and not args.db_path:
        print("--db-path is required when targeting an existing server.")
        return 2

    proc: Optional[subprocess.Popen] = None
    temp_dir: Optional[Path] = None
    stdout_log_path: Optional[Path] = None
    stderr_log_path: Optional[Path] = None
    base_url = args.base_url
    db_path = Path(args.db_path).expanduser().resolve() if args.db_path else None
    exit_code = 0
    started_at = datetime.now().isoformat()

    try:
        if args.spawn_server:
            (
                proc,
                base_url,
                temp_dir,
                db_path,
                stdout_log_path,
                stderr_log_path,
            ) = spawn_server(args)
            print(f"Spawned server at {base_url}")
            print(f"Isolated DB: {db_path}")
            print(f"Server stdout log: {stdout_log_path}")
            print(f"Server stderr log: {stderr_log_path}")
        assert db_path is not None
        wait_for_health(base_url)

        load_report = None
        if not args.skip_http_load and args.http_writes > 0:
            print_section("HTTP write load")
            load_session = f"{args.session_prefix}-load-{time.time_ns()}"
            start = time.perf_counter()
            load_results = run_http_load(args, base_url, load_session)
            elapsed_s = time.perf_counter() - start
            ok_count = sum(1 for r in load_results if r.status_code == 200)
            row_count = count_session_rows(db_path, load_session)
            hard_errors = [
                r for r in load_results if r.status_code not in (200, 429)
            ]
            load_report = {
                "session_name": load_session,
                "elapsed_s": elapsed_s,
                "status_counts": status_summary(load_results),
                "ok_count": ok_count,
                "db_row_count": row_count,
                "db_integrity_ok": row_count == ok_count,
                "hard_error_count": len(hard_errors),
            }
            if args.include_raw_http_results:
                load_report["raw_results"] = [
                    {
                        "status_code": r.status_code,
                        "latency_ms": r.latency_ms,
                        "body": r.body,
                        "error": r.error,
                    }
                    for r in load_results
                ]
            print(json.dumps(load_report, indent=2))
            if load_report["hard_error_count"] or not load_report["db_integrity_ok"]:
                exit_code = 1

        print_section("Compaction stage/apply")
        compaction_report = run_compaction_flow(args, base_url, db_path)
        print(json.dumps(compaction_report, indent=2))
        if not compaction_report["candidates_visible"]:
            exit_code = 1
        if any(v["staging_status"] != "applied" for v in compaction_report["applied_verifications"]):
            exit_code = 1
        if any(v["summary_count"] != 1 for v in compaction_report["applied_verifications"]):
            exit_code = 1
        if any(v["sources_marked"] != args.cluster_size for v in compaction_report["applied_verifications"]):
            exit_code = 1

        stale_report = None
        if not args.skip_stale_check:
            print_section("Stale negative path")
            stale_report = run_stale_flow(args, base_url, db_path)
            print(json.dumps(stale_report, indent=2))
            if stale_report["final_staging_status"] != "stale":
                exit_code = 1

        cross_session_report = None
        if not args.skip_cross_session_check:
            print_section("Cross-session isolation")
            cross_session_report = run_cross_session_flow(args, base_url, db_path)
            print(json.dumps(cross_session_report, indent=2))
            if cross_session_report["final_staging_status"] != "stale":
                exit_code = 1

        auto_apply_report = None
        if args.enable_auto_apply:
            print_section("Auto-apply scheduler")
            auto_apply_report = run_auto_apply_flow(args, db_path)
            print(json.dumps(auto_apply_report, indent=2))
            verification = auto_apply_report.get("verification") or {}
            if verification.get("staging_status") != "applied":
                exit_code = 1

        artifact_payload = {
            "generated_at": datetime.now().isoformat(),
            "started_at": started_at,
            "base_url": base_url,
            "db_path": str(db_path),
            "server_stdout_log": str(stdout_log_path) if stdout_log_path else None,
            "server_stderr_log": str(stderr_log_path) if stderr_log_path else None,
            "config": {
                "spawn_server": args.spawn_server,
                "server_preset": args.server_preset,
                "server_rate_limit_rpm": args.server_rate_limit_rpm,
                "queue_disabled": args.queue_disabled,
                "max_queue_size": args.max_queue_size,
                "http_writes": args.http_writes,
                "concurrency": args.concurrency,
                "cluster_size": args.cluster_size,
                "candidate_count": args.candidate_count,
                "double_apply": not args.no_double_apply,
                "stale_check": not args.skip_stale_check,
                "cross_session_check": not args.skip_cross_session_check,
                "auto_apply_enabled": args.enable_auto_apply,
                "auto_apply_interval_minutes": args.auto_apply_interval_minutes,
                "auto_apply_wait_s": args.auto_apply_wait_s,
            },
            "load": load_report,
            "compaction": compaction_report,
            "stale": stale_report,
            "cross_session": cross_session_report,
            "auto_apply": auto_apply_report,
            "result": "PASS" if exit_code == 0 else "FAIL",
        }
        if not args.no_write_artifacts:
            artifact_path = write_artifact(args, artifact_payload)
            print(f"artifacts_json={artifact_path}")

    finally:
        if proc is not None:
            stop_server(proc)
        if temp_dir is not None and not args.keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"\nRESULT: {'PASS' if exit_code == 0 else 'FAIL'}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
