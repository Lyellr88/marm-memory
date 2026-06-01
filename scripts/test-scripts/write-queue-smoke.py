#!/usr/bin/env python3
"""Smoke/stress test for MARM write queue behavior."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = ROOT / "marm-mcp-server"
sys.path.insert(0, str(SERVER_ROOT))

from marm_mcp_server.core import memory as memory_module  # noqa: E402
from marm_mcp_server.core.memory import MARMMemory  # noqa: E402


@dataclass
class RunResult:
    writes: int
    succeeded: int
    failed: int
    db_count: int
    integrity_ok: bool
    elapsed_s: float
    throughput_wps: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    error_summary: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Hammer MARM write queue with concurrent writes and report throughput/latency. "
            "Uses an isolated temp DB by default."
        )
    )
    parser.add_argument(
        "--writes",
        default="10,25,50,100",
        help="Comma-separated write counts for stepped runs (default: 10,25,50,100).",
    )
    parser.add_argument(
        "--queue-size",
        type=int,
        default=100,
        help="Queue max size to test (default: 100).",
    )
    parser.add_argument(
        "--session-prefix",
        default="smoke-write-queue",
        help="Session name prefix for generated writes.",
    )
    parser.add_argument(
        "--db-path",
        default="",
        help="Optional existing SQLite DB path. If omitted, an isolated temp DB is created.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete inserted rows for smoke test sessions after completion.",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop stepped runs after the first run with any failed writes.",
    )
    parser.add_argument(
        "--no-overflow",
        action="store_true",
        help="Skip the automatic overflow burst (2x queue size) that runs after stepped tests.",
    )
    return parser.parse_args()


async def run_burst(
    memory: MARMMemory, writes: int, session_name: str
) -> RunResult:
    latencies_ms: list[float] = []

    async def _write(index: int) -> tuple[bool, float, str]:
        start = time.perf_counter()
        try:
            await memory.store_memory_queued(
                content=f"smoke write #{index} for queue pressure validation",
                session=session_name,
                queue_enabled=True,
            )
            return True, (time.perf_counter() - start) * 1000, ""
        except Exception as exc:
            return False, (time.perf_counter() - start) * 1000, f"{type(exc).__name__}: {exc}"

    burst_start = time.perf_counter()
    outcomes = await asyncio.gather(*[_write(i) for i in range(writes)])
    elapsed_s = time.perf_counter() - burst_start

    succeeded = 0
    failed = 0
    error_counts: dict[str, int] = {}
    for ok, latency, err in outcomes:
        latencies_ms.append(latency)
        if ok:
            succeeded += 1
        else:
            failed += 1
            if err:
                etype = err.split(":")[0]
                error_counts[etype] = error_counts.get(etype, 0) + 1
    error_summary = [f"{etype} x{count}" for etype, count in error_counts.items()]

    # Verify rows actually landed in SQLite — catches silent write failures
    with memory.get_connection() as conn:
        db_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?",
            (session_name,),
        ).fetchone()[0]
    integrity_ok = db_count == succeeded

    p50_ms = statistics.median(latencies_ms) if latencies_ms else 0.0
    p95_ms = (
        statistics.quantiles(latencies_ms, n=100)[94]
        if len(latencies_ms) >= 20
        else max(latencies_ms, default=0.0)
    )
    max_ms = max(latencies_ms, default=0.0)
    throughput = (succeeded / elapsed_s) if elapsed_s > 0 else 0.0

    return RunResult(
        writes=writes,
        succeeded=succeeded,
        failed=failed,
        db_count=db_count,
        integrity_ok=integrity_ok,
        elapsed_s=elapsed_s,
        throughput_wps=throughput,
        p50_ms=p50_ms,
        p95_ms=p95_ms,
        max_ms=max_ms,
        error_summary=error_summary,
    )


def print_header() -> None:
    print(
        f"{'writes':>6}  {'ok':>4}  {'fail':>4}  {'db':>4}  {'ok?':>4}  "
        f"{'time':>8}  {'writes/s':>10}  {'p50':>9}  {'p95':>9}  {'max':>9}"
    )
    print("-" * 90)


def print_result(result: RunResult, label: str = "") -> None:
    integrity = "YES" if result.integrity_ok else "NO "
    suffix = f"  [{label}]" if label else ""
    print(
        f"{result.writes:>6}  "
        f"{result.succeeded:>4}  "
        f"{result.failed:>4}  "
        f"{result.db_count:>4}  "
        f"{integrity:>4}  "
        f"{result.elapsed_s:>7.3f}s  "
        f"{result.throughput_wps:>10.2f}  "
        f"{result.p50_ms:>8.2f}ms  "
        f"{result.p95_ms:>8.2f}ms  "
        f"{result.max_ms:>8.2f}ms"
        f"{suffix}"
    )
    if result.error_summary:
        print(f"         errors: {', '.join(result.error_summary)}")


def cleanup_sessions(memory: MARMMemory, session_names: list[str]) -> int:
    with memory.get_connection() as conn:
        total = 0
        for session in session_names:
            deleted = conn.execute(
                "DELETE FROM memories WHERE session_name = ?",
                (session,),
            ).rowcount
            conn.execute("DELETE FROM sessions WHERE session_name = ?", (session,))
            total += int(deleted or 0)
    return total


async def async_main() -> int:
    args = parse_args()
    try:
        writes_steps = [int(part.strip()) for part in args.writes.split(",") if part.strip()]
    except ValueError:
        print("Invalid --writes. Provide positive integers, e.g. 10,25,50,100.")
        return 2
    if not writes_steps or any(x <= 0 for x in writes_steps):
        print("Invalid --writes. Provide positive integers, e.g. 10,25,50,100.")
        return 2
    if args.queue_size <= 0:
        print("Invalid --queue-size. Provide a positive integer.")
        return 2

    temp_dir: Path | None = None
    if args.db_path:
        db_path = Path(args.db_path).expanduser().resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        isolated = False
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="marm-write-queue-smoke-"))
        db_path = temp_dir / "memory.db"
        isolated = True

    print(f"DB path:      {db_path}")
    print(f"Isolated DB:  {'yes' if isolated else 'no'}")
    print(f"Queue size:   {args.queue_size}")
    print()

    memory_module.WRITE_QUEUE_ENABLED = True
    memory_module.MAX_QUEUE_SIZE = args.queue_size
    memory = MARMMemory(str(db_path))
    memory._encoder_failed = True

    results: list[RunResult] = []
    session_names: list[str] = []

    print_header()

    try:
        for writes in writes_steps:
            session_name = f"{args.session_prefix}-{writes}-{time.time_ns()}"
            session_names.append(session_name)
            result = await run_burst(memory, writes, session_name)
            results.append(result)
            print_result(result)
            if args.stop_on_failure and (result.failed > 0 or not result.integrity_ok):
                print("Stopping early due to failed writes.")
                break

        # Overflow burst: exercises queue backpressure when more callers than queue slots
        if not args.no_overflow and max(writes_steps) <= args.queue_size:
            overflow_writes = args.queue_size * 2
            print(f"\n--- overflow burst: {overflow_writes} writes against queue size {args.queue_size} ---")
            session_name = f"{args.session_prefix}-overflow-{time.time_ns()}"
            session_names.append(session_name)
            result = await run_burst(memory, overflow_writes, session_name)
            results.append(result)
            print_result(result, label="overflow")

    finally:
        await memory.stop_write_queue()

    print()

    if args.cleanup:
        deleted = cleanup_sessions(memory, session_names)
        print(f"Cleanup: deleted {deleted} memory rows across {len(session_names)} sessions.")

    if isolated and temp_dir is not None:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Removed isolated temp dir: {temp_dir}")

    integrity_failures = [r for r in results if not r.integrity_ok]
    write_failures = [r for r in results if r.failed > 0]

    if integrity_failures:
        print(f"RESULT: FAIL — {len(integrity_failures)} burst(s) had SQLite count != succeeded (data integrity)")
        return 1
    if write_failures:
        print(f"RESULT: FAIL — {len(write_failures)} burst(s) had failed writes")
        return 1

    print("RESULT: PASS (all writes completed and verified in SQLite)")
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
