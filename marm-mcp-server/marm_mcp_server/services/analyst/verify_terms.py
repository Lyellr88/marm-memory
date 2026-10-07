from __future__ import annotations

import re

from ..code_context.terms import content_terms
from .packet import EvidencePacket
from .verify_citations import _BRACKET, _CODE_SPAN, _LINE_REF, _SENTENCE_END

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
