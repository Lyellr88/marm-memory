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

from .packet import EvidencePacket

VERIFIED_AT = 0.9

_HANDLE = re.compile(r"^[SM]\d{1,3}$", re.I)
_IDENTIFIER = re.compile(r"[A-Za-z_][\w.:]*")
# What separates a cited identifier from a bracketed word: an underscore, a
# qualifying separator, or an inner capital. `[optional]` and `[1]` are prose.
_IDENTIFIER_MARK = re.compile(r"[_.:]|[a-z][A-Z]")
# `[a]`, `[`a`]` or `[a, b]`, never the text of a markdown link.
_BRACKET = re.compile(r"\[([^\[\]\n]{1,200})\](?!\()")
_SEPARATOR = re.compile(r"[,;]")
_CODE_SPAN = re.compile(r"`([^`\n]{2,120})`")
_EMPTY_CALL = re.compile(r"[A-Za-z_][\w.]*\(\)")
_LINE_REF = re.compile(r"([\w./-]+\.\w+):(\d+)")
_CALL = re.compile(r"\b(calls|invokes|delegates to)\b", re.I)
_NOT_CALL = re.compile(
    r"\b(does not|doesn't|do not|don't|never|not)\s+(directly\s+)?"
    r"(call|calls|invoke|invokes|delegate to|delegates to)\b",
    re.I,
)
# An abstention is about the evidence or the answerer, never about the code:
# "the packet does not show X" abstains, "it does not include retries" claims.
# One or two qualifiers are allowed ("no direct evidence", "does not clearly
# show"); a qualified abstention still asserts nothing.
_QUALIFIER = r"(?:\w+\s+){0,2}"
_EVIDENCE = r"(?:context|packet|evidence|sources?|excerpts?|provided code)"
_ABSTAIN = re.compile(
    rf"\b({_EVIDENCE}\s+(does not|doesn't)\s+{_QUALIFIER}"
    r"(contain|show|include|say|mention|indicate)"
    rf"|not {_QUALIFIER}(in|present in|shown in) the {_EVIDENCE}"
    rf"|(I|we)\s+(cannot|can't)\s+{_QUALIFIER}(tell|determine|find|see)"
    rf"|no {_QUALIFIER}evidence)\b",
    re.I,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Citation:
    handle: str
    kind: str
    name: str = ""
    qualified_name: str | None = None
    memory_id: str | None = None
    file_path: str | None = None
    start_line: int = 0
    end_line: int = 0

    def to_public(self) -> dict:
        row: dict = {"handle": self.handle, "kind": self.kind, "name": self.name}
        if self.kind == "symbol":
            row.update(
                qualified_name=self.qualified_name,
                file_path=self.file_path,
                start_line=self.start_line,
                end_line=self.end_line,
            )
        else:
            row["memory_id"] = self.memory_id
        return row


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


def _resolve(name: str, packet: EvidencePacket) -> Citation | None:
    if _HANDLE.match(name):
        sym = packet.symbol(name)
        if sym:
            return Citation(
                sym.handle,
                "symbol",
                sym.name,
                sym.qualified_name,
                None,
                sym.file_path,
                sym.start_line,
                sym.end_line,
            )
        mem = packet.memory(name)
        if mem:
            return Citation(mem.handle, "memory", mem.handle, memory_id=mem.memory_id)
        return None
    sym = packet.by_name(name)
    if sym:
        return Citation(
            sym.handle,
            "symbol",
            sym.name,
            sym.qualified_name,
            None,
            sym.file_path,
            sym.start_line,
            sym.end_line,
        )
    return None


def extract_citations(
    text: str, packet: EvidencePacket
) -> tuple[list[Citation], list[str]]:
    """Resolve every cited name; report the identifier-shaped ones that do not.

    Each name in `[a, b]` is judged on its own, so an invented name cannot ride
    along beside a real one.
    """
    resolved: list[Citation] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for match in _BRACKET.finditer(text):
        for part in _SEPARATOR.split(match.group(1)):
            part = part.strip()
            backticked = part.startswith("`")
            name = part.strip("`").split("(")[0].strip()
            if not name:
                continue
            hit = _resolve(name, packet)
            if hit is not None:
                if hit.handle not in seen:
                    seen.add(hit.handle)
                    resolved.append(hit)
                continue
            invented = _HANDLE.match(name) or (
                _IDENTIFIER.fullmatch(name)
                and (backticked or _IDENTIFIER_MARK.search(name))
            )
            if invented and name not in unresolved:
                unresolved.append(name)
    return resolved, unresolved


def _claims(text: str) -> list[str]:
    """Claims to check for citations, one per cited run of sentences.

    A citation closing a line covers the uncited sentences before it on that
    line, the way a bullet or paragraph is cited once at its end. It never
    reaches across lines, and an abstention is never folded into it.
    """
    out: list[str] = []
    for line in text.split("\n"):
        pending: list[str] = []
        for part in _SENTENCE_END.split(line):
            s = part.strip().lstrip("-*# ").strip()
            # A list lead-in ("It works as follows:") announces claims; the
            # items under it make them.
            if s.endswith(":"):
                continue
            # Words with letters in them: `- [ ] todo` is scaffolding, not a claim.
            if sum(1 for w in s.split() if re.search(r"[A-Za-z]", w)) < 3:
                continue
            # Before the citation check: an abstention that cites something
            # would otherwise absorb the uncited claims pending before it.
            if _ABSTAIN.search(s):
                out.append(s)
            elif _BRACKET.search(s):
                out.append(" ".join([*pending, s]))
                pending = []
            else:
                pending.append(s)
        out.extend(pending)
    return out


def _span_support(text: str, packet: EvidencePacket) -> tuple[float, list[str]]:
    corpus = "\n".join(
        [s.source for s in packet.symbols]
        + [s.qualified_name for s in packet.symbols]
        + [s.file_path for s in packet.symbols]
        + [m.content for m in packet.memories]
    )
    checked = supported = 0
    failures: list[str] = []
    for span in _CODE_SPAN.findall(text):
        span = span.strip()
        if _HANDLE.match(span):
            continue
        checked += 1
        # Prose writes a function as `name()`; its source never does once it
        # takes arguments, so an empty call matches any call or definition.
        if span in corpus or (_EMPTY_CALL.fullmatch(span) and span[:-1] in corpus):
            supported += 1
        else:
            failures.append(f"code span not in packet: `{span}`")
    for path, line in _LINE_REF.findall(text):
        checked += 1
        n = int(line)
        if any(
            s.file_path.endswith(path)
            and s.start_line <= n <= max(s.end_line, s.start_line)
            for s in packet.symbols
        ):
            supported += 1
        else:
            failures.append(f"line reference outside the packet: {path}:{n}")
    return (1.0 if checked == 0 else supported / checked), failures


def _consistency(claims: list[str], packet: EvidencePacket) -> tuple[float, list[str]]:
    checked = consistent = 0
    failures: list[str] = []
    for claim in claims:
        cites, _ = extract_citations(claim, packet)
        syms = [c for c in cites if c.kind == "symbol"]
        mems = [c for c in cites if c.kind == "memory"]
        negated = bool(_NOT_CALL.search(claim))
        if len(syms) >= 2 and (negated or _CALL.search(claim)):
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
