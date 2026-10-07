"""Deterministic checks of an answer against the packet it was written from.

The model is a witness; this module is the judge. The score is the MINIMUM of
three checks, so a confident answer cannot average away a claim nothing in the
packet supports. Only contradicting evidence rejects: a cited handle or
identifier the packet does not contain. Missing evidence lowers the score and
leaves the answer uncertain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .packet import EvidencePacket, SymbolItem
from .verify_citations import (
    _ABSTAIN,
    _SENTENCE_END,
    _claims,
    _resolve,
    _span_support,
    extract_citations,
)
from .verify_citations import Citation as Citation
from .verify_terms import (
    _OPPOSITE,
    _TERM_SLACK,
    _denies_link,
    checkable,
    cited_text,
    negated_by_evidence,
    unsupported_terms,
)

VERIFIED_AT = 0.9


_CALL = re.compile(r"\b(calls|invokes|delegates to)\b", re.I)
_NOT_CALL = re.compile(
    r"\b(does not|doesn't|do not|don't|never|not)\s+(directly\s+)?"
    r"(call|calls|invoke|invokes|delegate to|delegates to)\b",
    re.I,
)


# A quoted statement is reported, not claimed: `M1 says "a does not call b"`.
_QUOTED = re.compile(r"\"[^\"\n]*\"|\u201c[^\u201d\n]*\u201d")


@dataclass(frozen=True)
class Verification:
    state: str
    score: float
    citation_coverage: float
    source_span_support: float
    graph_memory_consistency: float
    claims: int
    cited_claims: int
    failures: tuple[str, ...]
    hard_failures: tuple[str, ...]
    abstained: bool

    def to_public(self) -> dict:
        return {
            "state": self.state,
            "score": round(self.score, 4),
            "citation_coverage": round(self.citation_coverage, 4),
            "source_span_support": round(self.source_span_support, 4),
            "graph_memory_consistency": round(self.graph_memory_consistency, 4),
            "claims": self.claims,
            "cited_claims": self.cited_claims,
            "failures": list(self.failures),
            "hard_failures": list(self.hard_failures),
            "abstained": self.abstained,
        }


def named_call(
    text: str, packet: EvidencePacket, handles: tuple[str, ...] = ()
) -> tuple[SymbolItem, SymbolItem, bool] | None:
    """A call claim between two packet symbols named in the text, in order:
    (caller, callee, negated), or None when the text makes no such claim.

    A name several symbols share is resolved by the handles the claim cites or
    names; if they do not settle it, the claim cannot be judged by name.
    """
    text = _QUOTED.sub(" ", text)
    negated = bool(_NOT_CALL.search(text))
    if not (negated or _CALL.search(text)):
        return None
    at: dict[tuple[int, int], list[SymbolItem]] = {}
    for s in sorted(packet.symbols, key=lambda s: -len(s.name)):
        if not s.name:
            continue
        hit = re.search(rf"(?<![\w.]){re.escape(s.name)}\b", text)
        if hit:
            at.setdefault(hit.span(), []).append(s)
    if len(at) < 2:
        return None
    ends: list[SymbolItem] = []
    for span in sorted(at)[:2]:
        candidates = at[span]
        if len(candidates) > 1:
            candidates = [s for s in candidates if s.handle in handles]
        if len(candidates) != 1:
            return None
        ends.append(candidates[0])
    return ends[0], ends[1], negated


def _call_failure(
    text: str, packet: EvidencePacket, handles: tuple[str, ...] = ()
) -> str | None:
    claim = named_call(text, packet, handles)
    if claim is None:
        return None
    a, b, negated = claim
    edge = (a.qualified_name, b.qualified_name) in packet.edges
    if edge and negated:
        return f"call edge {a.handle} -> {b.handle} contradicts the claim"
    if not edge and not negated:
        return f"no call edge {a.handle} -> {b.handle} in the packet"
    return None


def _term_support(
    claims: list[str], packet: EvidencePacket
) -> tuple[int, int, list[str]]:
    checked = supported = 0
    failures: list[str] = []
    for claim in claims:
        cites = extract_citations(claim, packet)[0]
        if not cites:
            continue
        checked += 1
        missing = unsupported_terms(
            claim, cited_text([c.handle for c in cites], packet)
        )
        handles = [c.handle for c in cites]
        if not checkable(claim):
            failures.append("claim has nothing a check could fail")
        elif negated_by_evidence(claim, handles, packet):
            failures.append(_OPPOSITE)
        elif len(missing) <= _TERM_SLACK:
            supported += 1
        else:
            failures.append(
                "claim words not in the cited evidence: " + ", ".join(missing[:5])
            )
    return checked, supported, failures


def _consistency(claims: list[str], packet: EvidencePacket) -> tuple[float, list[str]]:
    checked = consistent = 0
    failures: list[str] = []
    for claim in claims:
        cites, _ = extract_citations(claim, packet)
        syms = [c for c in cites if c.kind == "symbol"]
        mems = [c for c in cites if c.kind == "memory"]
        asserted = _QUOTED.sub(" ", claim)
        negated = bool(_NOT_CALL.search(asserted))
        if len(syms) >= 2 and (negated or _CALL.search(asserted)):
            checked += 1
            a, b = syms[0].qualified_name or "", syms[1].qualified_name or ""
            edge = (a, b) in packet.edges
            if edge != negated:
                consistent += 1
            elif negated:
                failures.append(
                    f"call edge {syms[0].handle} -> {syms[1].handle} "
                    "contradicts the claim"
                )
            else:
                failures.append(f"no call edge {syms[0].handle} -> {syms[1].handle}")
        for m in mems:
            mem = packet.memory(m.handle)
            for s in syms:
                checked += 1
                name = (s.qualified_name or "").split(".")[-1]
                # A whole word: a memory about `apply` saying "claims" is not
                # a memory about `claim`.
                mentions = bool(
                    mem
                    and name
                    and re.search(rf"\b{re.escape(name)}\b", mem.content, re.I)
                )
                if (m.handle, s.qualified_name) in packet.links or mentions:
                    consistent += 1
                else:
                    failures.append(f"{m.handle} is not about {s.handle}")
    return (1.0 if checked == 0 else consistent / checked), failures


def verify(text: str, packet: EvidencePacket) -> Verification:
    _, unresolved = extract_citations(text, packet)
    hard = tuple(f"reference not in packet: [{u}]" for u in unresolved)

    claims = _claims(text)
    substantive = [c for c in claims if not _ABSTAIN.search(c)]
    abstained = bool(claims) and not substantive
    cited = [c for c in substantive if extract_citations(c, packet)[0]]
    coverage = (len(cited) / len(substantive)) if substantive else 0.0

    support, span_failures = _span_support(text, packet)
    checked, backed, term_failures = _term_support(substantive, packet)
    if checked:
        support = min(support, backed / checked)
    span_failures += term_failures
    consistency, graph_failures = _consistency(substantive, packet)
    score = min(coverage, support, consistency)

    if hard:
        state = "rejected"
    elif substantive and not abstained and score >= VERIFIED_AT:
        state = "verified"
    else:
        state = "uncertain"

    failures = tuple(span_failures + graph_failures) + (
        ("uncited claims",) if substantive and coverage < 1.0 else ()
    )
    return Verification(
        state=state,
        score=score,
        citation_coverage=coverage,
        source_span_support=support,
        graph_memory_consistency=consistency,
        claims=len(substantive),
        cited_claims=len(cited),
        failures=failures,
        hard_failures=hard,
        abstained=abstained,
    )


def _evidence_text(handle: str, packet: EvidencePacket) -> str:
    sym = packet.symbol(handle)
    if sym:
        return sym.source
    mem = packet.memory(handle)
    return mem.content if mem else ""


@dataclass(frozen=True)
class ItemCheck:
    """One structured result judged on its own.

    `support` names the evidence that decided a verified state: `quote` (a
    verbatim span of a cited item), `edge` (a call edge in the packet), `link`
    (a memory bound to or naming the symbol), or `citation` (cited handles
    resolve and nothing in the text contradicts the packet). Only the first
    three are mechanical facts; `citation` vouches for the references, not
    for the wording.
    """

    state: str
    support: str
    failures: tuple[str, ...]
    hard_failures: tuple[str, ...]


def check_item(
    op: str,
    *,
    text: str,
    packet: EvidencePacket,
    cites: tuple[str, ...] = (),
    quote: str | None = None,
    kind: str | None = None,
    source: str | None = None,
    target: str | None = None,
) -> ItemCheck:
    handles = [*cites, *(h for h in (source, target) if h)]
    hard = [
        f"reference not in packet: [{h}]"
        for h in handles
        if _resolve(h, packet) is None
    ]
    _, unresolved = extract_citations(text, packet)
    hard += [f"reference not in packet: [{u}]" for u in unresolved]
    if hard:
        return ItemCheck("rejected", "none", (), tuple(dict.fromkeys(hard)))

    _, failures = _span_support(text, packet)
    if op == "gaps":
        return ItemCheck("missing", "none", tuple(failures), ())
    if op == "next_steps":
        return ItemCheck("proposal", "citation", tuple(failures), ())

    support = "citation"
    if op in ("summary", "facts", "relations"):
        # A relation's text is a claim too: a real edge proves the call, not
        # the words written beside it.
        claim_handles = cites or tuple(h for h in (source, target) if h)
        missing = unsupported_terms(text, cited_text(claim_handles, packet))
        # A relation's edge is its checkable content, so only its text may be
        # empty; a summary or fact that asserts nothing cannot be verified.
        if op != "relations" and not checkable(text):
            failures.append("claim has nothing a check could fail")
        elif negated_by_evidence(text, claim_handles, packet):
            failures.append(_OPPOSITE)
        elif len(missing) > _TERM_SLACK:
            failures.append(
                "claim words not in the cited evidence: " + ", ".join(missing[:5])
            )
        # A quote proves what the evidence says, not that the graph agrees.
        call = _call_failure(
            text, packet, tuple(h for h in (*claim_handles, source, target) if h)
        )
        if call:
            failures.append(call)
    if op == "facts":
        # Character for character, as the contract promises.
        if quote and any(quote in _evidence_text(h, packet) for h in cites):
            support = "quote"
        else:
            failures.append("quote is not verbatim in the cited evidence")
    elif op == "relations":
        support, failure = _relation(kind, source, target, packet)
        if failure:
            failures.append(failure)
        # Text that negates the link ("never calls") contradicts the relation.
        if _denies_link(text, kind, source, target, packet):
            failures.append("the relation's text denies its own link")
    state = "uncertain" if failures else "verified"
    return ItemCheck(
        state, support if state == "verified" else "none", tuple(failures), ()
    )


def _relation(
    kind: str | None, source: str | None, target: str | None, packet: EvidencePacket
) -> tuple[str, str | None]:
    if kind == "calls":
        a = packet.symbol(source or "")
        b = packet.symbol(target or "")
        if a is None or b is None:
            return "none", "a call relation needs two symbols"
        if (a.qualified_name, b.qualified_name) in packet.edges:
            return "edge", None
        return "none", f"no call edge {a.handle} -> {b.handle} in the packet"
    if kind == "memory_about":
        mem = packet.memory(source or "")
        sym = packet.symbol(target or "")
        if mem is None or sym is None:
            return "none", "a memory relation needs a memory and a symbol"
        name = sym.qualified_name.split(".")[-1]
        if (mem.handle, sym.qualified_name) in packet.links or re.search(
            rf"\b{re.escape(name)}\b", mem.content, re.I
        ):
            return "link", None
        return "none", f"{mem.handle} is not about {sym.handle}"
    return "none", f"unknown relation kind: {kind}"


@dataclass(frozen=True)
class Disagreement:
    """A recorded memory that states a call the packet's graph does not show.

    `contradicted` when the memory denies an edge the graph has; `unconfirmed`
    when it asserts one the packet does not contain, which may only mean the
    edge lies outside the packet.
    """

    memory: str
    source: str
    target: str
    memory_says: str
    graph: str
    severity: str
    sentence: str

    def to_public(self) -> dict:
        return {
            "memory": self.memory,
            "from": self.source,
            "to": self.target,
            "memory_says": self.memory_says,
            "graph": self.graph,
            "severity": self.severity,
            "sentence": self.sentence,
        }


def disagreements(packet: EvidencePacket) -> list[Disagreement]:
    """Code-memory disagreements MARM can find without a model."""
    out: list[Disagreement] = []
    for mem in packet.memories:
        for sentence in _SENTENCE_END.split(mem.content):
            claim = named_call(sentence, packet)
            if claim is None:
                continue
            a, b, negated = claim
            edge = (a.qualified_name, b.qualified_name) in packet.edges
            if edge == negated:
                out.append(
                    Disagreement(
                        memory=mem.handle,
                        source=a.handle,
                        target=b.handle,
                        memory_says="does not call" if negated else "calls",
                        graph="edge" if edge else "no edge",
                        severity="contradicted" if negated else "unconfirmed",
                        sentence=sentence.strip()[:300],
                    )
                )
    return out
