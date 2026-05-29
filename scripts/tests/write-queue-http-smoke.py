#!/usr/bin/env python3
"""HTTP smoke/stress test for write queue + rate limiting behavior."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = ROOT / "marm-mcp-server"


@dataclass
class RequestResult:
    status_code: int
    latency_ms: float
    retry_after: Optional[str]
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Hammer /marm_context_log over HTTP to measure queue throughput and rate-limit impact."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8001", help="Server URL base.")
    parser.add_argument("--total-requests", type=int, default=120, help="Total HTTP writes to send.")
    parser.add_argument(
        "--request-steps",
        default="",
        help="Comma-separated stepped totals (e.g. 60,120,240). Overrides --total-requests.",
    )
    parser.add_argument("--concurrency", type=int, default=20, help="Parallel in-flight requests.")
    parser.add_argument("--session-prefix", default="smoke-http-queue", help="Session prefix for test writes.")
    parser.add_argument("--auth-key", default="", help="Optional Bearer token.")
    parser.add_argument("--timeout-s", type=float, default=10.0, help="Per-request timeout seconds.")
    parser.add_argument("--warmup-writes", type=int, default=0, help="Sequential warmup writes before load.")
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "scripts" / "out" / "write-queue-http"),
        help="Directory for JSON artifacts.",
    )
    parser.add_argument("--out-prefix", default="write-queue-http", help="Artifact file prefix.")
    parser.add_argument("--no-write-artifacts", action="store_true", help="Skip writing JSON/CSV artifacts.")
    parser.add_argument(
        "--include-raw-results",
        action="store_true",
        help="Include full per-request results in JSON artifacts (can be very large).",
    )
    parser.add_argument("--spawn-server", action="store_true", help="Start a local server subprocess for the run.")
    parser.add_argument("--spawn-port", type=int, default=18001, help="Port used when --spawn-server is set.")
    parser.add_argument(
        "--queue-disabled",
        action="store_true",
        help="Set WRITE_QUEUE_ENABLED=0 when spawning server. Queue is enabled by default.",
    )
    parser.add_argument(
        "--server-preset",
        choices=["none", "swarm", "swarm-max", "trusted"],
        default="none",
        help="CLI preset passed to spawned server.",
    )
    parser.add_argument(
        "--server-rate-limit-rpm",
        type=int,
        default=None,
        help="Pass --rate-limit-rpm N to a spawned server. 0 disables rate limiting.",
    )
    parser.add_argument("--max-queue-size", type=int, default=100, help="MAX_QUEUE_SIZE when spawning server.")
    parser.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="In stepped mode, stop after first failed step.",
    )
    return parser.parse_args()


def http_get(url: str, timeout_s: float) -> int:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.status


def wait_for_health(base_url: str, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    health_url = f"{base_url.rstrip('/')}/health"
    while time.time() < deadline:
        try:
            status = http_get(health_url, timeout_s=1.5)
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Server did not become healthy in time: {health_url}")


def post_context_log(
    base_url: str,
    session_name: str,
    index: int,
    auth_key: str,
    timeout_s: float,
) -> RequestResult:
    url = f"{base_url.rstrip('/')}/marm_context_log"
    payload = {
        "session_name": session_name,
        "content": f"http smoke write #{index} for queue+rate baseline",
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            latency_ms = (time.perf_counter() - start) * 1000
            return RequestResult(resp.status, latency_ms, resp.headers.get("Retry-After"))
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestResult(exc.code, latency_ms, exc.headers.get("Retry-After"), str(exc))
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestResult(-1, latency_ms, None, str(exc))


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = int(round((pct / 100.0) * (len(values) - 1)))
    return values[idx]


def run_load(args: argparse.Namespace, base_url: str, total_requests: int) -> tuple[list[RequestResult], float, str]:
    session_name = f"{args.session_prefix}-{time.time_ns()}"
    results: list[RequestResult] = []
    if args.warmup_writes > 5:
        print(f"note: {args.warmup_writes} warmup writes will consume rate-limit tokens before the measured run")
    warmup_session = f"{session_name}-warmup"
    for i in range(args.warmup_writes):
        warmup_result = post_context_log(
            base_url=base_url,
            session_name=warmup_session,
            index=-(i + 1),
            auth_key=args.auth_key,
            timeout_s=args.timeout_s,
        )
        print(
            f"warmup[{i + 1}/{args.warmup_writes}] "
            f"status={warmup_result.status_code} latency_ms={warmup_result.latency_ms:.2f}"
        )
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(
                post_context_log,
                base_url=base_url,
                session_name=session_name,
                index=i,
                auth_key=args.auth_key,
                timeout_s=args.timeout_s,
            )
            for i in range(total_requests)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    elapsed_s = time.perf_counter() - start
    return results, elapsed_s, session_name


def print_summary(results: list[RequestResult], elapsed_s: float, db_integrity_ok: bool | None = None) -> int:
    """Print run summary. Returns non-zero if hard errors (not 429s) were present."""
    counts = Counter(r.status_code for r in results)
    error_counts = Counter(r.error for r in results if r.error)
    latencies = [r.latency_ms for r in results]
    ok = counts.get(200, 0)
    rate_limited = counts.get(429, 0)
    errors = sum(v for k, v in counts.items() if k != 200 and k != 429)
    attempted_rpm = (len(results) / elapsed_s) * 60 if elapsed_s > 0 else 0.0
    success_rpm = (ok / elapsed_s) * 60 if elapsed_s > 0 else 0.0

    print("\n=== HTTP Write Queue Smoke Summary ===")
    print(f"total_requests={len(results)} elapsed={elapsed_s:.3f}s")
    print(f"attempted_rpm={attempted_rpm:.2f} success_rpm={success_rpm:.2f}")
    print(f"status_counts={dict(sorted(counts.items(), key=lambda x: x[0]))}")
    print(
        "latency_ms:"
        f" p50={percentile(latencies, 50):.2f}"
        f" p95={percentile(latencies, 95):.2f}"
        f" max={max(latencies) if latencies else 0.0:.2f}"
    )
    print(f"ok={ok} rate_limited_429={rate_limited} errors={errors}")
    if error_counts:
        print("error_breakdown:")
        for msg, count in error_counts.most_common(5):
            print(f"  {count}x {msg}")
    if db_integrity_ok is not None:
        print(f"db_integrity={'YES' if db_integrity_ok else 'NO (SQLite count != ok)'}")

    fail = errors > 0 or db_integrity_ok is False
    print(f"\nRESULT: {'FAIL' if fail else 'PASS'}")
    return 1 if fail else 0


def summarize(results: list[RequestResult], elapsed_s: float) -> dict:
    counts = Counter(r.status_code for r in results)
    latencies = [r.latency_ms for r in results]
    ok = counts.get(200, 0)
    attempted_rpm = (len(results) / elapsed_s) * 60 if elapsed_s > 0 else 0.0
    success_rpm = (ok / elapsed_s) * 60 if elapsed_s > 0 else 0.0
    return {
        "total_requests": len(results),
        "elapsed_s": elapsed_s,
        "attempted_rpm": attempted_rpm,
        "success_rpm": success_rpm,
        "status_counts": dict(sorted(counts.items(), key=lambda x: x[0])),
        "latency_ms": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "max": max(latencies) if latencies else 0.0,
        },
    }


def aggregate_results(results: list[RequestResult]) -> dict:
    status_counts = Counter(r.status_code for r in results)
    error_counts = Counter(r.error for r in results if r.error)
    retry_after_counts = Counter(r.retry_after for r in results if r.retry_after)
    latencies = [r.latency_ms for r in results]
    return {
        "status_counts": dict(sorted(status_counts.items(), key=lambda x: x[0])),
        "error_counts": dict(error_counts),
        "retry_after_counts": dict(retry_after_counts),
        "latency_ms": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "max": max(latencies) if latencies else 0.0,
        },
    }


def write_artifacts(args: argparse.Namespace, payload: dict) -> Path:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    json_path = out_dir / f"{args.out_prefix}-{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return json_path


def spawn_server(args: argparse.Namespace, port: int | None = None) -> tuple[subprocess.Popen, str, Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="marm-http-smoke-"))
    db_path = temp_dir / "memory.db"
    analytics_path = temp_dir / "analytics.db"

    env = os.environ.copy()
    env["SERVER_HOST"] = "127.0.0.1"
    resolved_port = args.spawn_port if port is None else port
    env["SERVER_PORT"] = str(resolved_port)
    env["MARM_DB_PATH"] = str(db_path)
    env["MARM_ANALYTICS_DB_PATH"] = str(analytics_path)
    env["WRITE_QUEUE_ENABLED"] = "0" if args.queue_disabled else "1"
    env["MAX_QUEUE_SIZE"] = str(args.max_queue_size)
    env.pop("MARM_API_KEY", None)

    cmd = [sys.executable, "-m", "marm_mcp_server"]
    if args.server_preset != "none":
        cmd.append(f"--{args.server_preset}")
    if args.server_rate_limit_rpm is not None:
        cmd.extend(["--rate-limit-rpm", str(args.server_rate_limit_rpm)])
    proc = subprocess.Popen(
        cmd,
        cwd=str(SERVER_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{resolved_port}"
    return proc, base_url, temp_dir


def expected_write_queue_enabled(args: argparse.Namespace) -> bool:
    return not args.queue_disabled or args.server_preset in {"swarm", "swarm-max", "trusted"}


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    args = parse_args()
    if args.total_requests <= 0 or args.concurrency <= 0:
        print("total-requests and concurrency must be positive integers.")
        return 2
    if args.queue_disabled and not args.spawn_server:
        print("warning: --queue-disabled has no effect without --spawn-server (cannot change a running server's queue state)")
    if args.server_preset != "none" and not args.spawn_server:
        print("warning: --server-preset has no effect without --spawn-server")
    if args.server_rate_limit_rpm is not None and not args.spawn_server:
        print("warning: --server-rate-limit-rpm has no effect without --spawn-server")
    if args.server_rate_limit_rpm is not None and args.server_rate_limit_rpm < 0:
        print("--server-rate-limit-rpm must be 0 or greater.")
        return 2

    base_url = args.base_url
    exit_code = 0
    steps: list[int] = []
    if args.request_steps.strip():
        try:
            steps = [int(part.strip()) for part in args.request_steps.split(",") if part.strip()]
        except ValueError:
            print("Invalid --request-steps. Example: 60,120,240")
            return 2
        if not steps or any(x <= 0 for x in steps):
            print("Invalid --request-steps. Use positive integers.")
            return 2
    else:
        steps = [args.total_requests]

    if not args.spawn_server:
        wait_for_health(base_url, timeout_s=5.0)
    step_reports: list[dict] = []
    for idx, step_total in enumerate(steps, start=1):
        print(f"\n=== Step {idx}/{len(steps)}: total_requests={step_total} ===")
        proc: Optional[subprocess.Popen] = None
        temp_dir: Optional[Path] = None
        step_base_url = base_url

        try:
            if args.spawn_server:
                step_port = args.spawn_port + idx - 1
                proc, step_base_url, temp_dir = spawn_server(args, port=step_port)
                print(f"Spawned step server at {step_base_url} (isolated DB)")
                wait_for_health(step_base_url)

            results, elapsed_s, session_name = run_load(args, step_base_url, step_total)

            db_integrity_ok: bool | None = None
            if temp_dir is not None:
                import sqlite3

                db_path = temp_dir / "memory.db"
                ok_count = Counter(r.status_code for r in results).get(200, 0)
                if db_path.exists():
                    with sqlite3.connect(str(db_path)) as conn:
                        db_count = conn.execute(
                            "SELECT COUNT(*) FROM memories WHERE session_name = ?",
                            (session_name,),
                        ).fetchone()[0]
                    db_integrity_ok = db_count == ok_count
        finally:
            if proc is not None:
                stop_server(proc)
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

        step_exit_code = print_summary(results, elapsed_s, db_integrity_ok)
        if step_exit_code != 0:
            exit_code = step_exit_code

        summary = summarize(results, elapsed_s)
        step_payload = {
            "step_index": idx,
            "total_steps": len(steps),
            "step_total_requests": step_total,
            "base_url": step_base_url,
            "summary": summary,
            "db_integrity_ok": db_integrity_ok,
            "aggregates": aggregate_results(results),
        }
        if args.include_raw_results:
            step_payload["results"] = [
                {
                    "status_code": r.status_code,
                    "latency_ms": r.latency_ms,
                    "retry_after": r.retry_after,
                    "error": r.error,
                }
                for r in results
            ]
        step_reports.append(step_payload)

        if args.stop_on_fail and step_exit_code != 0:
            print("Stopping stepped run after first failed step.")
            break
    if not args.no_write_artifacts:
        combined_payload = {
            "generated_at": datetime.now().isoformat(),
            "base_url": base_url,
            "config": {
                "total_requests": args.total_requests,
                "request_steps": args.request_steps,
                "resolved_steps": steps,
                "concurrency": args.concurrency,
                "timeout_s": args.timeout_s,
                "warmup_writes": args.warmup_writes,
                "spawn_server": args.spawn_server,
                "spawn_server_per_step": args.spawn_server,
                "spawn_start_port": args.spawn_port,
                "queue_disabled": args.queue_disabled,
                "expected_write_queue_enabled": expected_write_queue_enabled(args),
                "server_preset": args.server_preset,
                "server_rate_limit_rpm": args.server_rate_limit_rpm,
                "max_queue_size": args.max_queue_size,
                "stop_on_fail": args.stop_on_fail,
            },
            "steps": step_reports,
        }
        json_path = write_artifacts(args, combined_payload)
        print(f"artifacts_json={json_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
