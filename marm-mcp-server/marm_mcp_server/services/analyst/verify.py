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

from ..code_context.terms import content_terms
from .packet import EvidencePacket, SymbolItem

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
# Only an abstention's own clause is exempt, never the claim joined to it.
# Only contrast words split without a comma: a bare "and" or "while" is more
# often inside the abstention ("no evidence that a and b share a lock").
_CLAUSE = re.compile(
    r";\s+|,\s+(?=(?:but|and|while|although|though|whereas|yet)\b)"
    r"|\s+(?=(?:but|although|though|whereas)\b)",
    re.I,
)
# A quoted statement is reported, not claimed: `M1 says "a does not call b"`.
_QUOTED = re.compile(r"\"[^\"\n]*\"|\u201c[^\u201d\n]*\u201d")


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
    # `cache[row_id]` is code, not a citation. `[`name`]` still is: its
    # bracket opens before the backtick.
    spans = [m.span() for m in _CODE_SPAN.finditer(text)]
    for match in _BRACKET.finditer(text):
        if any(a < match.start() < b for a, b in spans):
            continue
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
        parts = [
            clause
            for sentence in _SENTENCE_END.split(line)
            for clause in (
                _CLAUSE.split(sentence) if _ABSTAIN.search(sentence) else [sentence]
            )
        ]
        for part in parts:
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
        # The packet shows each symbol as `path:start-end`, so quoting that back
        # quotes the packet.
        + [f"{s.file_path}:{s.start_line}-{s.end_line}" for s in packet.symbols]
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


#: Words that describe code, or the evidence itself, rather than assert what
#: the code does. A claim may use them without its evidence spelling them out.
_GENERIC = frozenset(
    """
    according agree agrees evidence argument arguments attribute before after begin
    begins call called caller callee calls check checks class code constant
    defined
    defines definition describe describes each end ends entry every field file
    first function
    helper instance line lines list located loop method module name named
    object parameter parameters recorded return returns say says show shows
    start starts
    across along also among either instead neither per upon via within
    without
    source state states symbol then value values variable when while wrapper
    """.split()
)
#: Distinctive words a claim may leave unsupported. Zero: one unsupported
#: verb is enough to turn a cited claim false.
_TERM_SLACK = 0
_OPPOSITE = "the cited evidence says the opposite"
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


_SUFFIXES = ("ings", "ing", "ies", "es", "ed", "s", "d")


def _forms(word: str) -> set[str]:
    """Every stem a word could have. Crude on purpose: `writes` and
    `write_row`, `bindings` and `bind` must meet, and a single-stem rule
    cannot tell `writes` (write) from `passes` (pass)."""
    w = word.casefold()
    out = {w}
    for suffix in _SUFFIXES:
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            stem = w[: -len(suffix)]
            out.add(stem)
            if suffix in ("ing", "ed"):
                # writing -> write, initialized -> initialize
                out.add(stem + "e")
    return out


def _stems(text: str) -> set[str]:
    out: set[str] = set()
    for word in _WORD.findall(text):
        out |= _forms(word)
        for part in _CAMEL.split(word):
            out |= _forms(part)
    return out


def cited_text(handles: list[str] | tuple[str, ...], packet: EvidencePacket) -> str:
    """What the cited items say. Citing a memory licenses calling it one."""
    parts: list[str] = []
    for h in handles:
        sym = packet.symbol(h)
        if sym:
            parts += [sym.source, sym.qualified_name, sym.file_path]
        mem = packet.memory(h)
        if mem:
            parts += [mem.content, "memory"]
    return "\n".join(parts)


def unsupported_terms(text: str, evidence: str) -> list[str]:
    """Distinctive words of a claim that its own evidence never uses.

    A verbatim citation proves the evidence exists, not that it says what the
    claim does: `apply deletes every memory [S1]` cites a real `apply` whose
    source never mentions deleting or memory.
    """
    known = _stems(evidence)
    out: list[str] = []
    for term in content_terms(_CODE_SPAN.sub(" ", _BRACKET.sub(" ", text))):
        for word in _WORD.findall(term.replace("_", " ")):
            forms = _forms(word)
            if len(word) < 3 or forms & _GENERIC:
                continue
            if not forms & known and word not in out:
                out.append(word)
    return out


def checkable(text: str) -> bool:
    """Whether a claim says anything a check could fail: a code span, a line
    reference, or a distinctive word. "No, it does not [S1]" says nothing."""
    if _CODE_SPAN.search(text) or _LINE_REF.search(text):
        return True
    for term in content_terms(_BRACKET.sub(" ", text)):
        for word in _WORD.findall(term.replace("_", " ")):
            if len(word) >= 3 and not _forms(word) & _GENERIC:
                return True
    return False


def named_call(
    text: str, packet: EvidencePacket
) -> tuple[SymbolItem, SymbolItem, bool] | None:
    """A call claim between two packet symbols named in the text, in order:
    (caller, callee, negated), or None when the text makes no such claim."""
    text = _QUOTED.sub(" ", text)
    negated = bool(_NOT_CALL.search(text))
    if not (negated or _CALL.search(text)):
        return None
    found: list[tuple[int, SymbolItem]] = []
    for s in sorted(packet.symbols, key=lambda s: -len(s.name)):
        if not s.name:
            continue
        hit = re.search(rf"(?<![\w.]){re.escape(s.name)}\b", text)
        if hit and all(s is not t for _, t in found):
            found.append((hit.start(), s))
    if len(found) < 2:
        return None
    found.sort(key=lambda p: p[0])
    return found[0][1], found[1][1], negated


def _call_failure(text: str, packet: EvidencePacket) -> str | None:
    claim = named_call(text, packet)
    if claim is None:
        return None
    a, b, negated = claim
    edge = (a.qualified_name, b.qualified_name) in packet.edges
    if edge and negated:
        return f"call edge {a.handle} -> {b.handle} contradicts the claim"
    if not edge and not negated:
        return f"no call edge {a.handle} -> {b.handle} in the packet"
    return None


#: Negation in prose. In code `not` and `None` are an operator and a value,
#: so only comments, docstrings and memory text are read for polarity.
_NEGATOR = re.compile(
    r"(?:not|never|no|cannot|without|nothing|neither|nor|.+n't)", re.I
)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9']*")
#: The words that state each relation kind's link.
_LINK_VERB = {
    "calls": re.compile(
        r"call(?:s|ed|ing)?|invok(?:e|es|ed|ing)|delegat(?:e|es|ed|ing)", re.I
    ),
    "memory_about": re.compile(
        r"about|describ\w*|document\w*|mention\w*|refer\w*", re.I
    ),
}
#: A contrast starts a clause that negates something else; a comma does not,
#: or "never, under any condition, calls" would lose its negator.
_CONTRAST = re.compile(r";|\b(?:but|although|though|whereas|yet)\b", re.I)
#: Closed-class words: they can follow a link verb without naming its object.
_FUNCTION_WORDS = frozenset(
    """
    a an the it its them they this that these those any anything anyone
    something nothing everything one ones itself themselves by to from of in on
    at into onto with for as again ever still yet once twice here there
    """.split()
)


def _denies_link(
    text: str,
    kind: str | None,
    source: str | None,
    target: str | None,
    packet: EvidencePacket,
) -> bool:
    """Whether the relation's text negates the link it labels.

    A negated link verb denies this relation unless its clause names another
    object and neither endpoint: "does not call it", "is not called by apply"
    deny it; "but does not call retry" denies a different call.
    """
    verb = _LINK_VERB.get(kind or "")
    if verb is None:
        return False
    own: set[str] = set()
    for h in (source, target):
        if not h:
            continue
        own.add(h.casefold())
        sym = packet.symbol(h)
        if sym:
            own |= _stems(sym.name.replace("_", " "))
    for clause in _CONTRAST.split(text):
        tokens = _TOKEN.findall(clause)
        for i, t in enumerate(tokens):
            if not (verb.fullmatch(t) and _negated(tokens, 0, i - 1)):
                continue
            if any(_forms(w) & own for w in tokens):
                return True
            objects = [
                w
                for w in tokens[i + 1 :]
                if w.casefold() not in _FUNCTION_WORDS
                and not w.casefold().endswith("ly")
                and not _forms(w) & _GENERIC
            ]
            if not objects:
                return True
    return False


_COMMENT = re.compile(r"^\s*(?:#|//|/\*|\*)\s?(.*)$")
_DOCSTRING = re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.S)
#: How far before the claim's first word a negator still governs it:
#: "never deletes", "does not ever delete".
_SCOPE = 3


def prose_blocks(source: str) -> list[str]:
    """The natural language in source code, one block per comment or docstring.

    Consecutive comment lines are one block, and so is a docstring, because a
    sentence wraps: `# must never` / `# write the row directly` is one
    sentence whose negation a line split would cut off.
    """
    blocks = [" ".join((a or b).split()) for a, b in _DOCSTRING.findall(source)]
    run: list[str] = []
    for line in source.splitlines():
        m = _COMMENT.match(line)
        if m:
            run.append(m.group(1).strip())
            continue
        if run:
            blocks.append(" ".join(run))
            run = []
    if run:
        blocks.append(" ".join(run))
    return [b for b in blocks if b]


def _prose_units(
    handles: list[str] | tuple[str, ...], packet: EvidencePacket
) -> list[str]:
    """Sentences of natural language in the cited evidence."""
    blocks: list[str] = []
    for h in handles:
        sym = packet.symbol(h)
        if sym:
            blocks += prose_blocks(sym.source)
        mem = packet.memory(h)
        if mem:
            blocks.append(mem.content)
    return [u.strip() for b in blocks for u in _SENTENCE_END.split(b) if u.strip()]


def _negated(tokens: list[str], lo: int, hi: int) -> bool:
    return any(_NEGATOR.fullmatch(t) for t in tokens[max(0, lo) : hi + 1])


def negated_by_evidence(
    text: str, handles: list[str] | tuple[str, ...], packet: EvidencePacket
) -> bool:
    """Whether the prose carrying a claim's words says the opposite.

    `deletes every memory row [S1]` over `# never deletes every memory row`
    has every word supported and the meaning inverted. Only a negator that
    governs those words counts: "marks the row applied so a caller cannot
    write it" negates the writing, not the marking.
    """
    claim = _CODE_SPAN.sub(" ", _BRACKET.sub(" ", text))
    # A comment inside `sweep` does not name `sweep`: the cited symbols are the
    # subject, not words the prose has to repeat.
    subject: set[str] = set()
    for h in handles:
        sym = packet.symbol(h)
        if sym:
            subject |= _stems(sym.qualified_name.replace("_", " "))
    words = [
        w
        for term in content_terms(claim)
        for w in _WORD.findall(term.replace("_", " "))
        if len(w) >= 3 and not _forms(w) & (_GENERIC | subject)
    ]
    if not words:
        return False
    claim_tokens = _TOKEN.findall(claim)
    claim_negated = _negated(claim_tokens, 0, len(claim_tokens) - 1)
    for unit in _prose_units(handles, packet):
        tokens = _TOKEN.findall(unit)
        forms = [_forms(t) for t in tokens]
        spots = []
        for w in words:
            want = _forms(w)
            at = next((i for i, f in enumerate(forms) if f & want), None)
            if at is None:
                break
            spots.append(at)
        else:
            lo, hi = min(spots) - _SCOPE, max(spots)
            if _negated(tokens, lo, hi) != claim_negated:
                return True
    return False


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
        call = _call_failure(text, packet)
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
