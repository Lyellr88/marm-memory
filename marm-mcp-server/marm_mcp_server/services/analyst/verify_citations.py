from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .packet import EvidencePacket, SymbolItem

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


def _corpus(symbols: list[SymbolItem], memories: list) -> str:
    return "\n".join(
        [s.source for s in symbols]
        + [s.qualified_name for s in symbols]
        + [s.file_path for s in symbols]
        # The packet shows each symbol as `path:start-end`, so quoting that back
        # quotes the packet.
        + [f"{s.file_path}:{s.start_line}-{s.end_line}" for s in symbols]
        + [m.content for m in memories]
    )


def _spans_in(text: str) -> Counter[str]:
    return Counter(
        span.strip()
        for span in _CODE_SPAN.findall(text)
        if not _HANDLE.match(span.strip())
    )


def _span_support(text: str, packet: EvidencePacket) -> tuple[float, list[str]]:
    # A cited claim's spans must be in what it cites, not anywhere in the
    # packet; the rest of the text is held to the packet as a whole.
    groups: list[
        tuple[Counter[str], list[tuple[str, str]], list[SymbolItem], str, str]
    ] = []
    spans_left = _spans_in(text)
    refs_left = Counter(_LINE_REF.findall(text))
    for claim in _claims(text):
        cites = extract_citations(claim, packet)[0]
        if not cites:
            continue
        spans, refs = _spans_in(claim), Counter(_LINE_REF.findall(claim))
        spans_left -= spans
        refs_left -= refs
        symbols = [s for c in cites if (s := packet.symbol(c.handle))]
        memories = [m for c in cites if (m := packet.memory(c.handle))]
        groups.append(
            (
                spans,
                list(refs.elements()),
                symbols,
                _corpus(symbols, memories),
                "the cited evidence",
            )
        )
    groups.append(
        (
            spans_left,
            list(refs_left.elements()),
            list(packet.symbols),
            _corpus(list(packet.symbols), list(packet.memories)),
            "packet",
        )
    )
    checked = supported = 0
    failures: list[str] = []
    for held_spans, held_refs, held_symbols, corpus, where in groups:
        for span in held_spans.elements():
            checked += 1
            # Prose writes a function as `name()`; its source never does once
            # it takes arguments, so an empty call matches any call or definition.
            if span in corpus or (_EMPTY_CALL.fullmatch(span) and span[:-1] in corpus):
                supported += 1
            else:
                failures.append(f"code span not in {where}: `{span}`")
        for path, line in held_refs:
            checked += 1
            n = int(line)
            if any(
                s.file_path.endswith(path)
                and s.start_line <= n <= max(s.end_line, s.start_line)
                for s in held_symbols
            ):
                supported += 1
            else:
                failures.append(f"line reference outside {where}: {path}:{n}")
    return (1.0 if checked == 0 else supported / checked), failures
