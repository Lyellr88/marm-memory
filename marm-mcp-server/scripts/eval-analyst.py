#!/usr/bin/env python3
"""Run the analyst evaluation matrix against a live local model.

The same cases `tests/test_analyst_eval.py` runs with canned replies, answered
here by a real model under a named profile. Compare profiles on safety first:
false-grounded results should stay near zero under every one, while usefulness
may rise with a stronger model.

Usage:
    python scripts/eval-analyst.py --url http://127.0.0.1:1234 --model <id> \\
        --profile small [--profile large ...] [--repeat 2] [--out rows.jsonl]

Limits come from the named profile plus the operator's environment
overrides (MARM_ANALYST_REASONING_TOKENS, MARM_ANALYST_TIME_BUDGET), exactly as
the server resolves them. Nothing is written to MARM. The endpoint must be
loopback, as MARM requires.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from marm_mcp_server.services import local_llm  # noqa: E402
from marm_mcp_server.services.analyst import brief as brief_mod  # noqa: E402
from marm_mcp_server.services.analyst.evaluate import (  # noqa: E402
    context,
    load_cases,
    score,
    summarise,
)
from marm_mcp_server.services.analyst.profile import PROFILES, resolve  # noqa: E402

CASES = HERE.parent / "tests" / "fixtures" / "analyst_eval.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="OpenAI-compatible server")
    ap.add_argument("--model", required=True, help="served model id to name")
    ap.add_argument(
        "--profile", action="append", choices=sorted(PROFILES), required=True
    )
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out", default=None, help="one JSON line per run")
    args = ap.parse_args()

    url = args.url.rstrip("/")
    if not local_llm._is_loopback(url):
        ap.error(f"{url} is not a loopback address")
    # This process only: the operator's saved switch and model choice stay
    # untouched, and every call names the model under test.
    local_llm.enabled = lambda: True
    local_llm.endpoint = lambda: url
    local_llm.available = lambda force=False: args.model

    cases = load_cases(args.cases)
    out = open(args.out, "w", encoding="utf-8") if args.out else None
    scores = []
    for name in args.profile:
        for case in cases:
            for n in range(args.repeat):
                # As the server resolves it: operator overrides apply.
                profile = resolve(name)
                if "time_s" in case:
                    profile = replace(profile, time_s=case["time_s"])
                b = asyncio.run(
                    brief_mod.analyse(context(case), case["task"], profile=profile)
                )
                s = score(case, b)
                scores.append(s)
                row = {
                    **s.to_public(),
                    "run": n,
                    "model": args.model,
                    "operations": [
                        {k: v for k, v in r.to_public().items() if k != "items"}
                        for r in b.operations
                    ],
                    "items": [i.to_public() for i in b.items],
                    "answer": b.answer,
                    "failures": list(b.verification.failures) if b.verification else [],
                }
                print(
                    json.dumps(
                        {
                            k: row[k]
                            for k in (
                                "profile",
                                "case",
                                "state",
                                "verified_claims",
                                "false_grounded",
                                "latency_ms",
                            )
                        }
                    ),
                    flush=True,
                )
                if out:
                    out.write(json.dumps(row) + "\n")
                    out.flush()
    if out:
        out.close()
    print(json.dumps(summarise(scores), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
