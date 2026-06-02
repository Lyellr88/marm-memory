#!/usr/bin/env python3
"""Primitive local-model swarm harness for MARM HTTP write pressure."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
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
class AgentResult:
    agent_id: int
    round_index: int
    session_name: str
    model_ok: bool
    model_latency_ms: float
    write_status: int
    write_latency_ms: float
    content_chars: int
    generated_content: str = ""
    model_error: str = ""
    write_error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a tiny local Ollama-backed swarm that generates short notes and "
            "writes them to MARM over /marm_context_log."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--auth-key", default="", help="Optional MARM Bearer token.")
    parser.add_argument("--timeout-s", type=float, default=15.0)
    parser.add_argument("--spawn-server", action="store_true")
    parser.add_argument("--spawn-port", type=int, default=18031)
    parser.add_argument(
        "--server-preset",
        choices=["none", "swarm", "swarm-max", "trusted"],
        default="swarm",
    )
    parser.add_argument("--server-rate-limit-rpm", type=int, default=None)
    parser.add_argument("--queue-disabled", action="store_true")
    parser.add_argument("--max-queue-size", type=int, default=100)
    parser.add_argument("--keep-temp", action="store_true")

    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="llama3.2")
    parser.add_argument("--ollama-timeout-s", type=float, default=90.0)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--num-predict", type=int, default=120)
    parser.add_argument(
        "--mock-model",
        action="store_true",
        help="Skip Ollama and generate deterministic local text for queue-only checks.",
    )

    parser.add_argument("--agents", type=int, default=3)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument(
        "--model-concurrency",
        type=int,
        default=1,
        help="Max simultaneous Ollama generations. Keep low on CPU-only systems.",
    )
    parser.add_argument("--write-concurrency", type=int, default=8)
    parser.add_argument(
        "--write-mode",
        choices=["stream", "burst"],
        default="stream",
        help="stream writes after each generation; burst generates all notes first.",
    )
    parser.add_argument(
        "--agent-stagger-ms",
        type=int,
        default=250,
        help="Small start delay per agent to avoid CPU spikes.",
    )
    parser.add_argument("--session-prefix", default="swarm")
    parser.add_argument(
        "--session-mode",
        choices=["per-agent", "shared"],
        default="per-agent",
        help="Use per-agent sessions or one shared session for all writes.",
    )
    parser.add_argument(
        "--enable-compaction-check",
        action="store_true",
        help="After writes, poll marm_compaction(action='candidates') for natural candidates.",
    )
    parser.add_argument(
        "--compaction-grace-minutes",
        type=int,
        default=0,
        help="COMPACTION_ACTIVE_SESSION_GRACE_MINUTES for spawned compaction checks.",
    )
    parser.add_argument(
        "--compaction-min-age-hours",
        type=int,
        default=0,
        help="COMPACTION_MIN_AGE_HOURS for spawned compaction checks.",
    )
    parser.add_argument(
        "--compaction-min-cluster-size",
        type=int,
        default=3,
        help="COMPACTION_MIN_CLUSTER_SIZE for spawned compaction checks.",
    )
    parser.add_argument(
        "--compaction-similarity-threshold",
        type=float,
        default=0.7,
        help="COMPACTION_SIMILARITY_THRESHOLD for spawned compaction checks.",
    )
    parser.add_argument(
        "--compaction-wait-s",
        type=float,
        default=15.0,
        help="Seconds to poll for compaction candidates after writes finish.",
    )
    parser.add_argument(
        "--seed-compaction-embeddings",
        action="store_true",
        help="Seed deterministic embeddings into the isolated DB before scan polling.",
    )
    parser.add_argument(
        "--no-compaction-trigger-fill",
        action="store_true",
        help="Do not add final same-session writes to end on a trigger boundary.",
    )
    parser.add_argument(
        "--scenario",
        default="MARM write queue pressure from a small local agent swarm",
    )
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "scripts" / "out" / "swarm"),
    )
    parser.add_argument("--out-prefix", default="swarm-smoke")
    parser.add_argument("--no-write-artifacts", action="store_true")
    parser.add_argument("--include-raw-results", action="store_true")
    return parser.parse_args()


def _json_request(
    method: str,
    url: str,
    payload: dict | None,
    timeout_s: float,
    auth_key: str = "",
) -> tuple[int, dict | None, str, float]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            body = json.loads(raw) if raw else None
            return resp.status, body, "", (time.perf_counter() - start) * 1000
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = None
        return exc.code, body, raw or str(exc), (time.perf_counter() - start) * 1000
    except Exception as exc:
        return -1, None, str(exc), (time.perf_counter() - start) * 1000


def wait_for_health(base_url: str, timeout_s: float = 35.0) -> None:
    deadline = time.time() + timeout_s
    url = f"{base_url.rstrip('/')}/health"
    while time.time() < deadline:
        status, _, _, _ = _json_request("GET", url, None, 1.5)
        if status == 200:
            return
        time.sleep(0.25)
    raise RuntimeError(f"Server did not become healthy in time: {url}")


def check_ollama(args: argparse.Namespace) -> None:
    if args.mock_model:
        return
    status, _, error, _ = _json_request(
        "GET",
        f"{args.ollama_url.rstrip('/')}/api/tags",
        None,
        min(args.ollama_timeout_s, 10.0),
    )
    if status != 200:
        raise RuntimeError(
            f"Ollama is not reachable at {args.ollama_url} (status={status}, error={error})"
        )


def spawn_server(args: argparse.Namespace) -> tuple[subprocess.Popen, str, Path, Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="marm-swarm-"))
    db_path = temp_dir / "memory.db"
    analytics_path = temp_dir / "analytics.db"

    env = os.environ.copy()
    env["SERVER_HOST"] = "127.0.0.1"
    env["SERVER_PORT"] = str(args.spawn_port)
    env["MARM_DB_PATH"] = str(db_path)
    env["MARM_ANALYTICS_DB_PATH"] = str(analytics_path)
    env["WRITE_QUEUE_ENABLED"] = "0" if args.queue_disabled else "1"
    env["MAX_QUEUE_SIZE"] = str(args.max_queue_size)
    if args.enable_compaction_check:
        env["COMPACTION_ENABLED"] = "1"
        env["COMPACTION_TRIGGER_COUNT"] = str(effective_compaction_trigger_count(args))
        env["COMPACTION_ACTIVE_SESSION_GRACE_MINUTES"] = str(
            args.compaction_grace_minutes
        )
        env["COMPACTION_MIN_AGE_HOURS"] = str(args.compaction_min_age_hours)
        env["COMPACTION_MIN_CLUSTER_SIZE"] = str(args.compaction_min_cluster_size)
        env["COMPACTION_SIMILARITY_THRESHOLD"] = str(
            args.compaction_similarity_threshold
        )
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
    return proc, f"http://127.0.0.1:{args.spawn_port}", temp_dir, db_path


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def build_prompt(args: argparse.Namespace, agent_id: int, round_index: int) -> str:
    return (
        "You are a tiny background memory-writing agent in a local test swarm.\n"
        "Write one concise memory note for MARM. No markdown. No preamble.\n"
        f"Scenario: {args.scenario}\n"
        f"Agent: {agent_id}\n"
        f"Round: {round_index}\n"
        "Include a concrete observation, decision, or next action in 1-3 sentences."
    )


def session_name_for(args: argparse.Namespace, run_id: str, agent_id: int) -> str:
    if args.session_mode == "shared":
        return f"{args.session_prefix}-{run_id}-shared"
    return f"{args.session_prefix}-{run_id}-agent-{agent_id}"


def generate_note(args: argparse.Namespace, agent_id: int, round_index: int) -> tuple[bool, str, str, float]:
    if args.mock_model:
        content = (
            f"Mock agent {agent_id} round {round_index}: observed queue pressure "
            f"for scenario '{args.scenario}' and recorded a concise memory note."
        )
        return True, content, "", 0.0

    payload = {
        "model": args.model,
        "prompt": build_prompt(args, agent_id, round_index),
        "stream": False,
        "options": {
            "temperature": args.temperature,
            "num_predict": args.num_predict,
        },
    }
    status, body, error, latency_ms = _json_request(
        "POST",
        f"{args.ollama_url.rstrip('/')}/api/generate",
        payload,
        args.ollama_timeout_s,
    )
    if status != 200 or not body:
        return False, "", error or f"ollama status {status}", latency_ms
    response = str(body.get("response", "")).strip()
    if not response:
        return False, "", "ollama returned an empty response", latency_ms
    return True, response, "", latency_ms


def write_note(
    args: argparse.Namespace,
    base_url: str,
    session_name: str,
    content: str,
) -> tuple[int, str, float]:
    payload = {"session_name": session_name, "content": content}
    status, _, error, latency_ms = _json_request(
        "POST",
        f"{base_url.rstrip('/')}/marm_context_log",
        payload,
        args.timeout_s,
        args.auth_key,
    )
    return status, error, latency_ms


def run_agent_round_stream(
    args: argparse.Namespace,
    base_url: str,
    run_id: str,
    agent_id: int,
    round_index: int,
    model_sem: threading.Semaphore,
    write_sem: threading.Semaphore,
) -> AgentResult:
    if args.agent_stagger_ms > 0:
        time.sleep((agent_id * args.agent_stagger_ms) / 1000.0)
    session_name = session_name_for(args, run_id, agent_id)
    with model_sem:
        model_ok, note, model_error, model_latency_ms = generate_note(
            args,
            agent_id,
            round_index,
        )
    if not model_ok:
        return AgentResult(
            agent_id,
            round_index,
            session_name,
            False,
            model_latency_ms,
            0,
            0.0,
            0,
            model_error=model_error,
        )

    content = (
        f"[swarm agent={agent_id} round={round_index} run={run_id}] "
        f"{note}"
    )
    with write_sem:
        write_status, write_error, write_latency_ms = write_note(
            args,
            base_url,
            session_name,
            content,
        )
    return AgentResult(
        agent_id,
        round_index,
        session_name,
        True,
        model_latency_ms,
        write_status,
        write_latency_ms,
        len(content),
        generated_content=content,
        write_error=write_error,
    )


def run_stream(args: argparse.Namespace, base_url: str, run_id: str) -> list[AgentResult]:
    model_sem = threading.Semaphore(args.model_concurrency)
    write_sem = threading.Semaphore(args.write_concurrency)
    max_workers = min(args.agents * args.rounds, max(args.agents, args.write_concurrency))
    results: list[AgentResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                run_agent_round_stream,
                args,
                base_url,
                run_id,
                agent_id,
                round_index,
                model_sem,
                write_sem,
            )
            for round_index in range(1, args.rounds + 1)
            for agent_id in range(1, args.agents + 1)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def run_burst(args: argparse.Namespace, base_url: str, run_id: str) -> list[AgentResult]:
    model_sem = threading.Semaphore(args.model_concurrency)
    generated: list[AgentResult] = []

    def generate_only(agent_id: int, round_index: int) -> AgentResult:
        if args.agent_stagger_ms > 0:
            time.sleep((agent_id * args.agent_stagger_ms) / 1000.0)
        session_name = session_name_for(args, run_id, agent_id)
        with model_sem:
            ok, note, error, latency_ms = generate_note(args, agent_id, round_index)
        content = ""
        if ok:
            content = (
                f"[swarm agent={agent_id} round={round_index} run={run_id}] "
                f"{note}"
            )
        return AgentResult(
            agent_id,
            round_index,
            session_name,
            ok,
            latency_ms,
            0,
            0.0,
            len(content),
            generated_content=content,
            model_error=error,
        )

    max_model_workers = min(args.agents * args.rounds, max(args.agents, args.model_concurrency))
    with ThreadPoolExecutor(max_workers=max_model_workers) as pool:
        futures = [
            pool.submit(generate_only, agent_id, round_index)
            for round_index in range(1, args.rounds + 1)
            for agent_id in range(1, args.agents + 1)
        ]
        for future in as_completed(futures):
            generated.append(future.result())

    def write_generated(result: AgentResult) -> AgentResult:
        if not result.model_ok:
            return result
        status, error, latency_ms = write_note(
            args,
            base_url,
            result.session_name,
            result.generated_content,
        )
        result.write_status = status
        result.write_error = error
        result.write_latency_ms = latency_ms
        return result

    results: list[AgentResult] = []
    with ThreadPoolExecutor(max_workers=args.write_concurrency) as pool:
        futures = [pool.submit(write_generated, item) for item in generated]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = int(round((pct / 100.0) * (len(values) - 1)))
    return values[idx]


def summarize(results: list[AgentResult], elapsed_s: float, db_count: int | None) -> dict:
    write_counts = Counter(r.write_status for r in results if r.model_ok)
    model_errors = Counter(r.model_error for r in results if r.model_error)
    write_errors = Counter(r.write_error for r in results if r.write_error)
    model_latencies = [r.model_latency_ms for r in results if r.model_ok]
    successful_write_latencies = [
        r.write_latency_ms for r in results if r.write_status == 200
    ]
    all_write_attempt_latencies = [
        r.write_latency_ms for r in results if r.write_status
    ]
    attempted = len(results)
    model_ok = sum(1 for r in results if r.model_ok)
    write_ok = write_counts.get(200, 0)
    rate_limited = write_counts.get(429, 0)
    hard_write_errors = sum(v for k, v in write_counts.items() if k not in {200, 429})
    db_integrity_ok = None if db_count is None else db_count == write_ok
    return {
        "attempted_agent_rounds": attempted,
        "elapsed_s": elapsed_s,
        "attempted_rounds_per_min": (attempted / elapsed_s) * 60 if elapsed_s else 0.0,
        "successful_writes_per_min": (write_ok / elapsed_s) * 60 if elapsed_s else 0.0,
        "model_ok": model_ok,
        "model_failed": attempted - model_ok,
        "write_ok": write_ok,
        "rate_limited_429": rate_limited,
        "hard_write_errors": hard_write_errors,
        "write_status_counts": dict(sorted(write_counts.items(), key=lambda x: x[0])),
        "model_latency_ms": {
            "p50": percentile(model_latencies, 50),
            "p95": percentile(model_latencies, 95),
            "max": max(model_latencies) if model_latencies else 0.0,
        },
        "write_latency_ms": {
            "p50": percentile(successful_write_latencies, 50),
            "p95": percentile(successful_write_latencies, 95),
            "max": max(successful_write_latencies)
            if successful_write_latencies
            else 0.0,
        },
        "all_write_attempt_latency_ms": {
            "p50": percentile(all_write_attempt_latencies, 50),
            "p95": percentile(all_write_attempt_latencies, 95),
            "max": max(all_write_attempt_latencies)
            if all_write_attempt_latencies
            else 0.0,
        },
        "model_error_counts": dict(model_errors.most_common(5)),
        "write_error_counts": dict(write_errors.most_common(5)),
        "db_count": db_count,
        "db_integrity_ok": db_integrity_ok,
    }


def db_session_count(db_path: Path, session_prefix: str) -> int:
    if not db_path.exists():
        return 0
    with sqlite3.connect(str(db_path)) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM memories WHERE session_name LIKE ?",
                (f"{session_prefix}%",),
            ).fetchone()[0]
        )


def effective_compaction_trigger_count(args: argparse.Namespace) -> int:
    if args.server_preset in ("none", "") and args.server_rate_limit_rpm is None:
        return 5
    return 20


def add_compaction_trigger_fill(
    args: argparse.Namespace,
    base_url: str,
    run_id: str,
    successful_writes: int,
    force_full_trigger: bool = False,
) -> list[AgentResult]:
    if args.no_compaction_trigger_fill:
        return []
    trigger_count = effective_compaction_trigger_count(args)
    remainder = successful_writes % trigger_count
    needed = 0 if remainder == 0 else trigger_count - remainder
    if force_full_trigger and needed == 0:
        needed = trigger_count
    if needed == 0:
        return []

    session_name = session_name_for(args, run_id, 1)
    fill_results: list[AgentResult] = []
    for index in range(needed):
        content = (
            f"[swarm trigger-fill run={run_id} index={index}] "
            "Shared-session compaction trigger fill note for natural scan testing."
        )
        status, error, latency_ms = write_note(args, base_url, session_name, content)
        fill_results.append(
            AgentResult(
                0,
                index + 1,
                session_name,
                True,
                0.0,
                status,
                latency_ms,
                len(content),
                generated_content=content,
                write_error=error,
            )
        )
    return fill_results


def seed_compaction_embeddings(db_path: Path, session_prefix: str) -> int:
    """Seed stable same-vector embeddings for isolated smoke rows without an encoder."""
    vector = struct.pack("<" + "f" * 8, *([1.0] * 8))
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute(
            """
            UPDATE memories
            SET embedding = ?
            WHERE session_name LIKE ?
              AND embedding IS NULL
            """,
            (vector, f"{session_prefix}%"),
        )
        return cursor.rowcount


def poll_compaction_candidates(args: argparse.Namespace, base_url: str) -> dict:
    deadline = time.time() + args.compaction_wait_s
    last_status = 0
    last_error = ""
    last_body: dict | None = None
    while time.time() <= deadline:
        status, body, error, latency_ms = _json_request(
            "POST",
            f"{base_url.rstrip('/')}/marm_compaction",
            {"action": "candidates"},
            args.timeout_s,
            args.auth_key,
        )
        last_status = status
        last_error = error
        last_body = body
        candidates = body.get("candidates", []) if body else []
        if status == 200 and candidates:
            return {
                "status": "found",
                "http_status": status,
                "candidate_count": len(candidates),
                "latency_ms": latency_ms,
                "candidate_ids": [c.get("candidate_id") for c in candidates],
                "sessions": sorted({c.get("session_name") for c in candidates}),
            }
        time.sleep(1.0)

    candidates = last_body.get("candidates", []) if last_body else []
    return {
        "status": "not_found",
        "http_status": last_status,
        "candidate_count": len(candidates),
        "error": last_error,
    }


def write_artifact(args: argparse.Namespace, payload: dict) -> Path:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    path = out_dir / f"{args.out_prefix}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def print_summary(summary: dict) -> int:
    print("\n=== Swarm Smoke Summary ===")
    print(f"attempted_agent_rounds={summary['attempted_agent_rounds']}")
    print(f"elapsed_s={summary['elapsed_s']:.3f}")
    print(f"attempted_rounds_per_min={summary['attempted_rounds_per_min']:.2f}")
    print(f"successful_writes_per_min={summary['successful_writes_per_min']:.2f}")
    print(
        f"model_ok={summary['model_ok']} model_failed={summary['model_failed']} "
        f"write_ok={summary['write_ok']} rate_limited_429={summary['rate_limited_429']} "
        f"hard_write_errors={summary['hard_write_errors']}"
    )
    print(f"write_status_counts={summary['write_status_counts']}")
    print(
        "model_latency_ms:"
        f" p50={summary['model_latency_ms']['p50']:.2f}"
        f" p95={summary['model_latency_ms']['p95']:.2f}"
        f" max={summary['model_latency_ms']['max']:.2f}"
    )
    print(
        "write_latency_ms:"
        f" p50={summary['write_latency_ms']['p50']:.2f}"
        f" p95={summary['write_latency_ms']['p95']:.2f}"
        f" max={summary['write_latency_ms']['max']:.2f}"
        " (200 only)"
    )
    print(
        "all_write_attempt_latency_ms:"
        f" p50={summary['all_write_attempt_latency_ms']['p50']:.2f}"
        f" p95={summary['all_write_attempt_latency_ms']['p95']:.2f}"
        f" max={summary['all_write_attempt_latency_ms']['max']:.2f}"
    )
    if summary["db_integrity_ok"] is not None:
        print(f"db_integrity={'YES' if summary['db_integrity_ok'] else 'NO'}")
    if summary["model_error_counts"]:
        print(f"model_error_counts={summary['model_error_counts']}")
    if summary["write_error_counts"]:
        print(f"write_error_counts={summary['write_error_counts']}")

    failed = (
        summary["model_failed"] > 0
        or summary["hard_write_errors"] > 0
        or (summary["model_ok"] > 0 and summary["write_ok"] == 0)
        or summary["db_integrity_ok"] is False
    )
    print(f"\nRESULT: {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


def validate_args(args: argparse.Namespace) -> int:
    if args.agents <= 0 or args.rounds <= 0:
        print("--agents and --rounds must be positive.")
        return 2
    if args.model_concurrency <= 0 or args.write_concurrency <= 0:
        print("--model-concurrency and --write-concurrency must be positive.")
        return 2
    if args.server_rate_limit_rpm is not None and args.server_rate_limit_rpm < 0:
        print("--server-rate-limit-rpm must be 0 or greater.")
        return 2
    if args.num_predict <= 0:
        print("--num-predict must be positive.")
        return 2
    if args.queue_disabled and not args.spawn_server:
        print("warning: --queue-disabled has no effect without --spawn-server")
    if args.server_preset != "none" and not args.spawn_server:
        print("warning: --server-preset has no effect without --spawn-server")
    if args.server_rate_limit_rpm is not None and not args.spawn_server:
        print("warning: --server-rate-limit-rpm has no effect without --spawn-server")
    if args.enable_compaction_check and not args.spawn_server:
        print("warning: compaction timing overrides require --spawn-server")
    if args.enable_compaction_check and args.session_mode != "shared":
        print("--enable-compaction-check requires --session-mode shared.")
        return 2
    if args.compaction_grace_minutes < 0 or args.compaction_min_age_hours < 0:
        print("--compaction-grace-minutes and --compaction-min-age-hours must be >= 0.")
        return 2
    if args.compaction_min_cluster_size <= 0 or args.compaction_wait_s <= 0:
        print("--compaction-min-cluster-size and --compaction-wait-s must be positive.")
        return 2
    if not 0.0 <= args.compaction_similarity_threshold <= 1.0:
        print("--compaction-similarity-threshold must be between 0.0 and 1.0.")
        return 2
    if args.seed_compaction_embeddings and not args.spawn_server:
        print("--seed-compaction-embeddings requires --spawn-server.")
        return 2
    return 0


def main() -> int:
    args = parse_args()
    validation = validate_args(args)
    if validation:
        return validation

    proc: Optional[subprocess.Popen] = None
    temp_dir: Optional[Path] = None
    db_path: Optional[Path] = None
    base_url = args.base_url
    run_id = str(time.time_ns())
    session_prefix = f"{args.session_prefix}-{run_id}"

    try:
        check_ollama(args)
        if args.spawn_server:
            proc, base_url, temp_dir, db_path = spawn_server(args)
            print(f"Spawned MARM server at {base_url} (isolated DB)")
            wait_for_health(base_url)
        else:
            wait_for_health(base_url, timeout_s=5.0)

        print(
            f"Running {args.agents} agents x {args.rounds} rounds "
            f"(model_concurrency={args.model_concurrency}, "
            f"write_concurrency={args.write_concurrency}, mode={args.write_mode})"
        )
        start = time.perf_counter()
        if args.write_mode == "burst":
            results = run_burst(args, base_url, run_id)
        else:
            results = run_stream(args, base_url, run_id)
        seeded_embeddings = 0
        if args.enable_compaction_check and args.seed_compaction_embeddings and db_path:
            seeded_embeddings = seed_compaction_embeddings(db_path, session_prefix)
            print(f"Seeded {seeded_embeddings} deterministic compaction embeddings.")
        if args.enable_compaction_check:
            ok_writes = sum(1 for item in results if item.write_status == 200)
            fill_results = add_compaction_trigger_fill(
                args,
                base_url,
                run_id,
                ok_writes,
                force_full_trigger=seeded_embeddings > 0,
            )
            if fill_results:
                print(
                    f"Added {len(fill_results)} trigger-fill writes "
                    "to end on a compaction boundary."
                )
                results.extend(fill_results)
        elapsed_s = time.perf_counter() - start

        db_count = db_session_count(db_path, session_prefix) if db_path else None
        summary = summarize(results, elapsed_s, db_count)
        compaction_report = None
        if args.enable_compaction_check:
            compaction_report = poll_compaction_candidates(args, base_url)
            compaction_report["seeded_embeddings"] = seeded_embeddings
            summary["compaction_check"] = compaction_report
            if compaction_report["status"] != "found":
                exit_code = 1
            else:
                exit_code = 0
        else:
            exit_code = 0
        summary_exit_code = print_summary(summary)
        exit_code = max(exit_code, summary_exit_code)
        if compaction_report is not None:
            print(f"compaction_check={compaction_report}")

        if not args.no_write_artifacts:
            payload = {
                "generated_at": datetime.now().isoformat(),
                "result": "PASS" if exit_code == 0 else "FAIL",
                "base_url": base_url,
                "config": {
                    "agents": args.agents,
                    "rounds": args.rounds,
                    "model": args.model,
                    "mock_model": args.mock_model,
                    "ollama_url": args.ollama_url,
                    "model_concurrency": args.model_concurrency,
                    "write_concurrency": args.write_concurrency,
                    "write_mode": args.write_mode,
                    "agent_stagger_ms": args.agent_stagger_ms,
                    "session_mode": args.session_mode,
                    "spawn_server": args.spawn_server,
                    "server_preset": args.server_preset,
                    "server_rate_limit_rpm": args.server_rate_limit_rpm,
                    "queue_disabled": args.queue_disabled,
                    "max_queue_size": args.max_queue_size,
                    "session_prefix": session_prefix,
                    "enable_compaction_check": args.enable_compaction_check,
                    "effective_compaction_trigger_count": (
                        effective_compaction_trigger_count(args)
                    ),
                    "compaction_grace_minutes": args.compaction_grace_minutes,
                    "compaction_min_age_hours": args.compaction_min_age_hours,
                    "compaction_min_cluster_size": args.compaction_min_cluster_size,
                    "compaction_similarity_threshold": (
                        args.compaction_similarity_threshold
                    ),
                    "compaction_wait_s": args.compaction_wait_s,
                    "seed_compaction_embeddings": args.seed_compaction_embeddings,
                },
                "summary": summary,
            }
            if args.include_raw_results:
                payload["results"] = [result.__dict__ for result in results]
            path = write_artifact(args, payload)
            print(f"artifacts_json={path}")

        return exit_code
    finally:
        if proc is not None:
            stop_server(proc)
        if temp_dir is not None:
            if args.keep_temp:
                print(f"kept_temp_dir={temp_dir}")
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
