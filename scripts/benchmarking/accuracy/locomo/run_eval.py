#!/usr/bin/env python3
"""LoCoMo retrieval benchmark for marm-memory.

No LLM is used anywhere in this script. It measures whether marm-memory's
recall surfaces the gold evidence turns for each LoCoMo question - pure
evidence-ID matching against the server's own JSON responses. Answer
generation and false-premise abstention (LoCoMo category 5) are downstream
LLM behaviors, out of scope for a memory-server benchmark.

Every conversation turn is ingested through `marm_log_entry`, which stores
the turn twice on the server: a log row and a semantic memory (v2.21.0+).
Scoring then reads both lanes of `marm_smart_recall`:
  semantic lane - `results` (embedding + FTS5 hybrid engine, memory ids)
  log lane      - `log_results` (substring match over topics/summaries, entry ids)
plus the union an agent actually sees in one response.

Usage:
    python scripts/benchmarking/accuracy/locomo/run_eval.py --ingest --recall --limit 5
    python scripts/benchmarking/accuracy/locomo/run_eval.py --recall --limit 5   # reuse prior ingest

Requires a running marm-memory HTTP server (default http://127.0.0.1:8001).
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

DATASET_URL = (
    "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
)
HERE = Path(__file__).parent
OUT_DIR = HERE / "out"
DATASET_PATH = OUT_DIR / "locomo10.json"
STATE_PATH = OUT_DIR / "ingest_state.json"
RESULTS_PATH = OUT_DIR / "results.json"

CATEGORY_NAMES = {
    1: "single-hop",
    2: "temporal",
    3: "multi-hop",
    4: "open-domain",
    5: "adversarial",
}

MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}

RETRIES = 3
BACKOFF_SECONDS = 2.0


def server_request(base_url, path, payload, api_key=None):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(payload).encode("utf-8")
    last_error = None
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(
            base_url + path, data=data, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429:
                # default limiter blocks the IP for 30s after a violation;
                # waiting less than that just burns retries (use --trusted
                # on the server to avoid this entirely)
                time.sleep(31)
                continue
            if e.code >= 500:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
                continue
            raise
        except urllib.error.URLError as e:
            last_error = e
            time.sleep(BACKOFF_SECONDS * (2**attempt))
    raise RuntimeError(f"{path} failed after {RETRIES + 1} attempts: {last_error}")


def ensure_dataset():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if DATASET_PATH.exists():
        return
    print(f"Downloading LoCoMo dataset to {DATASET_PATH} ...")
    urllib.request.urlretrieve(DATASET_URL, DATASET_PATH)


def load_dataset():
    with open(DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def session_name_for(sample_id):
    return f"locomo_{sample_id}"


def parse_session_date(date_time_str):
    """LoCoMo session timestamps look like '1:56 pm on 8 May, 2023'.
    Returns YYYY-MM-DD or None if the shape is unrecognized."""
    if not date_time_str:
        return None
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", date_time_str)
    if not m:
        return None
    day, month_name, year = m.groups()
    month = MONTHS.get(month_name.lower())
    if not month:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"


def turn_text(turn):
    """Turn content, with image-share captions folded in so evidence that
    lives in a photo turn is actually ingested."""
    text = (turn.get("text") or "").strip()
    caption = (turn.get("blip_caption") or "").strip()
    if caption:
        return (
            f"{text} [shares photo: {caption}]"
            if text
            else f"[shares photo: {caption}]"
        )
    return text


def build_entry(turn, session_date):
    """Real usage timestamps its logs, so the benchmark does too: the
    documented YYYY-MM-DD-topic-summary entry format carries the LoCoMo
    session date through the supported interface (needed for category 2,
    temporal questions - otherwise every turn lands on today's date)."""
    text = turn_text(turn)
    speaker = turn.get("speaker", "unknown")
    if session_date:
        return f"{session_date}-{speaker}-{text}"
    return f"{speaker}: {text}"


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def ingest(base_url, api_key, limit_samples=None):
    dataset = load_dataset()
    if limit_samples:
        dataset = dataset[:limit_samples]

    # dia_id -> {entry_id, memory_id}, per sample_id
    state = load_state()
    for sample in dataset:
        sample_id = sample["sample_id"]
        sess = session_name_for(sample_id)

        # Re-ingesting an already-ingested conversation would duplicate rows
        # (server-side consolidation is off by default) and orphan the ids in
        # out/ingest_state.json. Skip instead; for a clean run, point the
        # server at a fresh DB and delete out/ingest_state.json.
        if sample_id in state:
            print(f"  skipping {sample_id}: already in {STATE_PATH.name}")
            continue

        conv = sample["conversation"]
        session_keys = sorted(
            (
                k
                for k in conv
                if k.startswith("session_") and not k.endswith("_date_time")
            ),
            key=lambda k: int(k.split("_")[1]),
        )
        dia_to_ids = {}
        turn_count = 0
        for skey in session_keys:
            session_date = parse_session_date(conv.get(f"{skey}_date_time"))
            for turn in conv[skey]:
                resp = server_request(
                    base_url,
                    "/marm_log_entry",
                    {"entry": build_entry(turn, session_date), "session_name": sess},
                    api_key,
                )
                payload = resp.get("result", resp)
                if payload.get("status") != "success":
                    raise RuntimeError(
                        f"marm_log_entry failed for {turn.get('dia_id')}: {payload}"
                    )
                dia_to_ids[turn["dia_id"]] = {
                    "entry_id": payload.get("entry_id"),
                    "memory_id": payload.get("memory_id"),
                }
                turn_count += 1
        state[sample_id] = dia_to_ids
        # Save after every sample so a crash mid-run loses one conversation, not all
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(
            f"  ingested {sample_id}: {turn_count} turns across {len(session_keys)} sessions"
        )

    print(f"Ingest state saved to {STATE_PATH}")


def _blank_bucket():
    return {
        "total": 0,
        "any_hit": 0,
        "all_hit": 0,
        "evidence_recall_sum": 0.0,
        "semantic_any_hit": 0,
        "semantic_all_hit": 0,
        "log_any_hit": 0,
        "log_all_hit": 0,
        "all_hit_impossible": 0,
    }


def recall_and_score(base_url, api_key, limit_k, limit_samples=None):
    if not STATE_PATH.exists():
        print(
            "No out/ingest_state.json found - run with --ingest first.", file=sys.stderr
        )
        sys.exit(1)

    state = load_state()
    dataset = load_dataset()
    if limit_samples:
        dataset = dataset[:limit_samples]

    per_category = defaultdict(_blank_bucket)
    per_question_log = []
    skipped_no_evidence = 0
    truncated_responses = 0
    unresolved_evidence = 0

    for sample in dataset:
        sample_id = sample["sample_id"]
        if sample_id not in state:
            continue
        dia_to_ids = state[sample_id]
        sess = session_name_for(sample_id)

        for qa in sample["qa"]:
            evidence = qa.get("evidence") or []
            category = qa.get("category")
            if not evidence or category is None:
                skipped_no_evidence += 1
                continue

            resp = server_request(
                base_url,
                "/marm_smart_recall",
                {
                    "query": qa["question"],
                    "session_name": sess,
                    "limit": limit_k,
                    "search_all": False,
                    "include_logs": True,
                    "detail": 3,
                },
                api_key,
            )
            payload = resp.get("result", resp)
            if payload.get("_mcp_truncated") or payload.get("_log_results_truncated"):
                truncated_responses += 1

            semantic_ids = {r.get("id") for r in payload.get("results") or []}
            semantic_ids.discard(None)
            log_ids = {r.get("id") for r in payload.get("log_results") or []}
            log_ids.discard(None)

            # Per-evidence-turn coverage, per lane and combined.
            # Evidence dia_ids that never resolved to an ingested turn (rare
            # LoCoMo annotation quirk) count as explicit misses, not silent
            # drops — the denominator stays the full evidence list.
            gold = [dia_to_ids.get(d) for d in evidence]
            unresolved = sum(1 for g in gold if not g)
            gold = [g for g in gold if g]
            unresolved_evidence += unresolved
            if not gold:
                skipped_no_evidence += 1
                continue

            sem_covered = [
                g["memory_id"] in semantic_ids if g["memory_id"] else False
                for g in gold
            ]
            log_covered = [
                g["entry_id"] in log_ids if g["entry_id"] else False for g in gold
            ]
            covered = [sem or log for sem, log in zip(sem_covered, log_covered)]
            covered += [False] * unresolved

            hit_any = any(covered)
            hit_all = all(covered)
            recall_frac = sum(covered) / len(covered)

            bucket = per_category[category]
            bucket["total"] += 1
            bucket["any_hit"] += int(hit_any)
            bucket["all_hit"] += int(hit_all)
            bucket["evidence_recall_sum"] += recall_frac
            bucket["semantic_any_hit"] += int(any(sem_covered))
            bucket["semantic_all_hit"] += int(all(sem_covered))
            bucket["log_any_hit"] += int(any(log_covered))
            bucket["log_all_hit"] += int(all(log_covered))
            if len(covered) > limit_k:
                # all-hit cannot be satisfied when a question has more
                # evidence turns than the recall top-K
                bucket["all_hit_impossible"] += 1

            per_question_log.append(
                {
                    "sample_id": sample_id,
                    "question": qa["question"],
                    "category": category,
                    "evidence": evidence,
                    "hit_any": hit_any,
                    "hit_all": hit_all,
                    "evidence_recall": round(recall_frac, 3),
                    "semantic_hit_any": any(sem_covered),
                    "log_hit_any": any(log_covered),
                    "unresolved_evidence": unresolved,
                }
            )

    report = {
        "limit_k": limit_k,
        "skipped_no_evidence": skipped_no_evidence,
        "truncated_responses": truncated_responses,
        "unresolved_evidence": unresolved_evidence,
        "per_category": {},
        "overall": _blank_bucket(),
    }
    overall = report["overall"]
    for cat in sorted(per_category):
        d = per_category[cat]
        n = d["total"]
        report["per_category"][CATEGORY_NAMES.get(cat, str(cat))] = {
            "total": n,
            "any_hit_rate": round(d["any_hit"] / n, 3) if n else 0,
            "all_hit_rate": round(d["all_hit"] / n, 3) if n else 0,
            "evidence_recall": round(d["evidence_recall_sum"] / n, 3) if n else 0,
            "semantic_any_hit_rate": round(d["semantic_any_hit"] / n, 3) if n else 0,
            "log_any_hit_rate": round(d["log_any_hit"] / n, 3) if n else 0,
            "all_hit_impossible": d["all_hit_impossible"],
        }
        for key in (
            "total",
            "any_hit",
            "all_hit",
            "evidence_recall_sum",
            "semantic_any_hit",
            "semantic_all_hit",
            "log_any_hit",
            "log_all_hit",
            "all_hit_impossible",
        ):
            overall[key] += d[key]

    n = overall["total"]
    summary = {
        "total": n,
        "any_hit_rate": round(overall["any_hit"] / n, 3) if n else 0,
        "all_hit_rate": round(overall["all_hit"] / n, 3) if n else 0,
        "evidence_recall": round(overall["evidence_recall_sum"] / n, 3) if n else 0,
        "semantic_any_hit_rate": round(overall["semantic_any_hit"] / n, 3) if n else 0,
        "log_any_hit_rate": round(overall["log_any_hit"] / n, 3) if n else 0,
        "all_hit_impossible": overall["all_hit_impossible"],
    }
    report["overall"] = summary

    RESULTS_PATH.write_text(
        json.dumps({"report": report, "questions": per_question_log}, indent=2),
        encoding="utf-8",
    )

    print(f"\n=== LoCoMo retrieval results (limit={limit_k}) ===")
    header = f"{'category':<14}{'n':>6}{'any-hit':>10}{'all-hit':>10}{'ev-recall':>11}{'sem-any':>10}{'log-any':>10}"
    print(header)
    rows = [*list(report["per_category"].items()), ("OVERALL", summary)]
    for cat, d in rows:
        print(
            f"{cat:<14}{d['total']:>6}{d['any_hit_rate']:>10.1%}{d['all_hit_rate']:>10.1%}"
            f"{d['evidence_recall']:>11.1%}{d['semantic_any_hit_rate']:>10.1%}{d['log_any_hit_rate']:>10.1%}"
        )
    if skipped_no_evidence:
        print(
            f"\nSkipped {skipped_no_evidence} questions with no evidence annotations."
        )
    if summary["all_hit_impossible"]:
        print(
            f"Note: {summary['all_hit_impossible']} questions have more evidence turns "
            f"than limit_k={limit_k}; all-hit is impossible for those at this K."
        )
    if truncated_responses:
        print(
            f"WARNING: {truncated_responses} responses hit the 1MB MCP limit and were "
            f"truncated - their scores undercount actual recall."
        )
    print(f"\nFull results saved to {RESULTS_PATH}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default=os.environ.get("MARM_BASE_URL", "http://127.0.0.1:8001")
    )
    parser.add_argument("--api-key", default=os.environ.get("MARM_API_KEY"))
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Ingest LoCoMo conversations into marm-memory",
    )
    parser.add_argument(
        "--recall", action="store_true", help="Run recall + score against ingested data"
    )
    parser.add_argument(
        "--limit", type=int, default=5, help="recall limit (top-K) per query, default 5"
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=None,
        help="only process first N LoCoMo conversations",
    )
    args = parser.parse_args()

    if not args.ingest and not args.recall:
        parser.error("pass --ingest and/or --recall")

    ensure_dataset()

    if args.ingest:
        print("=== Ingesting LoCoMo conversations ===")
        t0 = time.time()
        ingest(args.base_url, args.api_key, args.samples)
        print(f"Ingest done in {time.time() - t0:.1f}s")

    if args.recall:
        print("\n=== Running recall + scoring ===")
        t0 = time.time()
        recall_and_score(args.base_url, args.api_key, args.limit, args.samples)
        print(f"Recall done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
