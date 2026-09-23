#!/usr/bin/env python3
"""Ask real questions through a running server and report how each was judged.

Calibrate the verifier against real answers, never against examples written to
pass it. For every `rejected` and `uncertain` result, read the answer and decide
whether the verifier was right; fix a check that is wrong, never a threshold.

Usage:
    python scripts/calibrate-analyst.py --project <graph project> \\
        --questions questions.txt [--base-url http://127.0.0.1:8001] [--out results.jsonl]
"""

import argparse
import collections
import json
import time
import urllib.request


def ask(base_url: str, project: str, question: str, timeout: float) -> dict:
    body = json.dumps({"task": question, "project": project, "answer": True}).encode()
    req = urllib.request.Request(
        f"{base_url}/marm_code_context",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8001")
    ap.add_argument("--out", default=None, help="write one JSON line per answer")
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args()

    with open(args.questions, encoding="utf-8") as handle:
        questions = [line.strip() for line in handle if line.strip()]
    states: collections.Counter[str] = collections.Counter()
    out = open(args.out, "w", encoding="utf-8") if args.out else None
    for question in questions:
        started = time.monotonic()
        try:
            result = ask(args.base_url, args.project, question, args.timeout)
        except OSError as exc:
            result = {"answer_status": "error", "answer_hint": str(exc)}
        verification = result.get("answer_verification") or {}
        state = verification.get("state") or result.get("answer_status", "unknown")
        states[state] += 1
        row = {
            "q": question,
            "state": state,
            "status": result.get("answer_status"),
            "score": verification.get("score"),
            "coverage": verification.get("citation_coverage"),
            "span": verification.get("source_span_support"),
            "consistency": verification.get("graph_memory_consistency"),
            "failures": verification.get("hard_failures", [])
            + verification.get("failures", []),
            "unresolved": result.get("answer_unresolved"),
            "answer": result.get("answer"),
            "hint": result.get("answer_hint"),
            "seconds": round(time.monotonic() - started, 1),
        }
        print(
            json.dumps(
                {k: row[k] for k in ("q", "state", "score", "failures", "seconds")}
            ),
            flush=True,
        )
        if out:
            out.write(json.dumps(row) + "\n")
            out.flush()
    if out:
        out.close()
    print(dict(states))


if __name__ == "__main__":
    main()
