"""The evaluation matrix, with canned model output, under every profile.

`scripts/eval-analyst.py` runs the same cases against a live local model.
Here the replies are fixed, so what is asserted is the judge: whatever a
model writes, the matrix's safety numbers must hold.
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from marm_mcp_server.services.analyst import brief as brief_mod
from marm_mcp_server.services.analyst.evaluate import (
    CATEGORIES,
    context,
    load_cases,
    score,
    summarise,
)
from marm_mcp_server.services.analyst.profile import PROFILES

CASES = load_cases(Path(__file__).parent / "fixtures" / "analyst_eval.json")


def _run(case, profile, monkeypatch):
    calls = []

    def complete(system, user, **kw):
        calls.append(kw)
        if kw.get("finished") is not None:
            kw["finished"]["reason"] = "stop"
        if kw.get("schema") is None:
            return case.get("raw") or None
        if "raw_structured" in case:
            return case["raw_structured"]
        keys = kw["schema"]["properties"]
        return json.dumps({k: case["replies"].get(k, []) for k in keys})

    monkeypatch.setattr(brief_mod.local_llm, "available", lambda *a, **k: "canned")
    monkeypatch.setattr(brief_mod.local_llm, "complete", complete)
    monkeypatch.setattr(brief_mod.local_llm, "endpoint_source", lambda: "test")
    if "time_s" in case:
        profile = replace(profile, time_s=case["time_s"])
    b = asyncio.run(brief_mod.analyse(context(case), case["task"], profile=profile))
    return b, calls


def test_every_category_is_covered():
    assert {c["category"] for c in CASES} == set(CATEGORIES)


@pytest.mark.parametrize("name", list(PROFILES))
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_the_matrix_holds_under_every_profile(case, name, monkeypatch):
    profile = PROFILES[name]
    b, calls = _run(case, profile, monkeypatch)
    s = score(case, b)
    expect = case["expect"]

    assert s.false_grounded == 0, s
    assert s.state in expect["state"], (s, b.verification)
    if "calls" in expect:
        assert len(calls) == expect["calls"]
    if expect.get("min_disagreements"):
        assert s.disagreements >= expect["min_disagreements"]
    if expect.get("packet_within_cap"):
        assert b.packet.omitted_symbols > 0
        # The rendered header and question sit outside the per-item cap.
        assert s.packet_chars <= profile.context_chars + 400
    assert all(c["max_tokens"] == profile.max_tokens for c in calls)
    assert all(c["widen"] is False for c in calls)


def test_the_summary_reports_safety_first(monkeypatch):
    scores = [
        score(case, _run(case, PROFILES["small"], monkeypatch)[0]) for case in CASES
    ]
    summary = summarise(scores)["small"]
    assert summary["false_grounded"] == 0
    assert summary["useful"] >= 1
    assert list(summary)[:3] == ["cases", "false_grounded", "citation_precision"]
