"""Score an analysis against a case whose ground truth is known.

The matrix compares safety outcomes, not wording: a false-grounded result is a
verified claim the case says is false, and it should stay near zero under
every profile while usefulness is free to rise with a stronger model.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..code_context.compose import Context, Symbol
from .brief import Brief
from .verify import _claims, extract_citations

CATEGORIES = (
    "supported",
    "unsupported",
    "conflicting",
    "missing-citation",
    "long-context",
    "timeout",
    "malformed",
)


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = json.loads(Path(path).read_text())
    for case in cases:
        if case["category"] not in CATEGORIES:
            raise ValueError(f"{case['id']}: unknown category {case['category']}")
    return cases


def context(case: dict[str, Any]) -> Context:
    symbols = [
        Symbol(qn, name, label, path, start, end, source=source)
        for qn, name, label, path, start, end, source in case["symbols"]
    ]
    for i in range(case.get("filler", 0)):
        # Long-context cases pad the composition with ranked but irrelevant
        # source, to prove the profile's cap holds whatever was composed.
        symbols.append(
            Symbol(
                f"pad.filler_{i}",
                f"filler_{i}",
                "Function",
                f"pad/f{i}.py",
                1,
                80,
                source=f"def filler_{i}(x):\n" + "    x = x + 1\n" * 80,
            )
        )
    return Context(
        project={"name": case.get("project", "eval")},
        task=case["task"],
        symbols=symbols,
        memories=list(case.get("memories", [])),
        graph_edges=[(a, b, 1.0) for a, b in case.get("edges", [])],
    )


@dataclass
class Score:
    case: str
    category: str
    profile: str
    state: str
    status: str
    useful: bool
    verified_claims: int
    # None when the run attempted no citation: nothing to be precise about.
    citation_precision: float | None
    false_grounded: int
    disagreements: int
    latency_ms: int
    packet_chars: int
    output_chars: int
    calls: int
    max_tokens: int
    stopped: str | None

    def to_public(self) -> dict[str, Any]:
        return asdict(self)


def _verified_claims(brief: Brief) -> list[str]:
    """The claims this analysis presents as verified."""
    if brief.operations:
        return [
            i.text
            for i in brief.items
            if i.op in ("summary", "facts", "relations") and i.state == "verified"
        ]
    if brief.verification and brief.verification.state == "verified" and brief.answer:
        return _claims(brief.answer)
    return []


def _precision(brief: Brief) -> float | None:
    if brief.operations:
        cites = [h for i in brief.items for h in (*i.cites, i.source, i.target) if h]
        bad = {f for i in brief.items for f in i.hard_failures}
        return None if not cites else 1 - len(bad) / len(cites)
    if not brief.answer:
        return None
    good, unresolved = extract_citations(brief.answer, brief.packet)
    total = len(good) + len(unresolved)
    return None if not total else len(good) / total


def score(case: dict[str, Any], brief: Brief) -> Score:
    claims = _verified_claims(brief)
    precision = _precision(brief)
    forbidden = [re.compile(p, re.I) for p in case.get("forbidden", [])]
    # Wording is free; a verified claim the case says is false is not.
    false = sum(1 for c in claims if any(f.search(c) for f in forbidden))
    info = brief.model_info
    return Score(
        case=case["id"],
        category=case["category"],
        profile=brief.profile.name,
        state=(
            brief.verification.state
            if brief.verification and brief.status != "failed"
            else brief.status
        ),
        status=brief.status,
        useful=bool(claims),
        verified_claims=len(claims),
        citation_precision=None if precision is None else round(precision, 4),
        false_grounded=false,
        disagreements=len(brief.disagreements),
        latency_ms=int(info.get("elapsed_ms") or 0),
        packet_chars=brief.packet.to_public()["chars"],
        output_chars=int(info.get("output_chars") or 0),
        calls=int(info.get("calls") or 0),
        max_tokens=int(info.get("max_tokens") or brief.profile.max_tokens),
        stopped=info.get("stopped"),
    )


def summarise(scores: list[Score]) -> dict[str, Any]:
    """Per profile: the safety numbers first, then usefulness and cost."""
    out: dict[str, Any] = {}
    for name in sorted({s.profile for s in scores}):
        rows = [s for s in scores if s.profile == name]
        cited = [s.citation_precision for s in rows if s.citation_precision is not None]
        answerable = [s for s in rows if s.category in ("supported", "conflicting")]
        out[name] = {
            "cases": len(rows),
            "false_grounded": sum(s.false_grounded for s in rows),
            "citation_precision": round(sum(cited) / len(cited), 4) if cited else None,
            "uncited": len(rows) - len(cited),
            "useful": sum(1 for s in answerable if s.useful),
            "useful_of": len(answerable),
            "verified": sum(1 for s in rows if s.state == "verified"),
            "median_latency_ms": sorted(s.latency_ms for s in rows)[len(rows) // 2],
            "max_packet_chars": max(s.packet_chars for s in rows),
            "max_output_chars": max(s.output_chars for s in rows),
        }
    return out
