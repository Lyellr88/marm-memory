"""Stage what the analyst verified, and apply only what MARM can prove.

A result reaches memory only through `marm_distill apply`: by a reviewer, or
under Automated Guardrails when the operator allows it and the result's claim
kind is one MARM checks mechanically. Nothing here asks the model for
anything, and the model never applies anything: what is staged is the
verified answer's own results, never a rewrite of them.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog

from ...core import runtime_flags
from ...core.distill import Candidate, resolve
from ...core.distill import _normalise as _distill_normalise
from .. import distill as distill_service
from .brief import Brief
from .ops import Item
from .packet import EvidencePacket, SymbolItem
from .verify import named_call, verify
from .verify_citations import _LINE_REF, _claims, extract_citations
from .verify_terms import _DOCSTRING, prose_blocks

logger = structlog.get_logger(__name__)

AUTO_APPLY_ENV = "MARM_ANALYST_AUTO_APPLY"
_SECRET = re.compile(
    r"(?i:(?:api[_-]?key|secret|password|token)\s*[:=])"
    r"|-----BEGIN"
    # Credentials that need no label: provider token formats, a bearer
    # value, a JWT, and a URL carrying a password.
    r"|\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\bAIza[0-9A-Za-z_-]{35}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"
    r"|(?i:\bbearer\s+)[A-Za-z0-9._~+/=-]{16,}"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"|\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@"
)

#: Claim kinds whose truth MARM can check without judging prose. Only these
#: may be applied without a reviewer.
MECHANICAL = ("call_edge", "quoted_span", "identifier_in_range", "verbatim_statement")
_MAX_STAGED = 5

# A bracket of packet handles only: `[S1]`, `[S1, S2]`, `[M1; S2]`.
_HANDLES = re.compile(r"\s*\[\s*[SM]\d+(?:\s*[,;]\s*[SM]\d+)*\s*\]", re.IGNORECASE)
_CALL_EDGE = re.compile(r"^`[^`\n]+` calls `[^`\n]+`$")
_IN_RANGE = re.compile(r"^`[^`\n]+` is defined in \S+:\d+-\d+$")


def _without_handles(line: str) -> str:
    """A handle means something only inside its packet; a memory outlives it."""
    text = _HANDLES.sub("", line)
    return re.sub(r"\s+([.,;:!?])", r"\1", text).strip()


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


@dataclass(frozen=True)
class Conclusion:
    """One verified result, in the form it would be stored."""

    content: str
    evidence: str
    claim_kind: str
    source: str


def _call_edge(a: SymbolItem, b: SymbolItem, source: str) -> Conclusion:
    # Written by MARM from the edge, so the stored words are the proof.
    return Conclusion(
        content=f"`{a.qualified_name}` calls `{b.qualified_name}`",
        evidence=f"call edge {a.qualified_name} -> {b.qualified_name}",
        claim_kind="call_edge",
        source=source,
    )


_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_COMMENT_LINE = re.compile(r"^\s*(?:#|//|/\*|\*)")
# A list item or heading starts its own block, as a blank line does.
_BLOCK_START = re.compile(r"^\s*(?:[-*\u2022#>]+\s+|\d+[.)]\s+)")
_HEADING = re.compile(r"^\s*#+\s")


def _sentences(text: str) -> list[str]:
    joined = " ".join(text.split())
    return [u.rstrip(".").strip() for u in _SENTENCE.split(joined) if u.strip()]


def _source_sentences(text: str) -> list[str]:
    """Whole sentences of a transcript, joined across line wraps."""
    blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        if not line.strip() or _BLOCK_START.match(line):
            blocks.append([])
        if line.strip():
            blocks[-1].append(line)
        if _HEADING.match(line):
            blocks.append([])
    return [
        u for b in blocks if b for u in _SENTENCE.split(" ".join(" ".join(b).split()))
    ]


def _statements(handles: list[str], packet: EvidencePacket) -> list[str]:
    """Whole statements in the cited evidence.

    Prose is split only at sentence ends, so a comment that wraps (`# must
    never` / `# write the row directly`) stays one sentence with its negation.
    Code counts line by line, with its comments and docstrings removed first
    so a line of prose cannot pass as a line of code.
    """
    out: list[str] = []
    for h in handles:
        sym = packet.symbol(h)
        if sym:
            for block in prose_blocks(sym.source):
                out += _sentences(block)
            code = _DOCSTRING.sub("", sym.source)
            out += [
                line.strip()
                for line in code.splitlines()
                if line.strip() and not _COMMENT_LINE.match(line)
            ]
        mem = packet.memory(h)
        if mem:
            out += _sentences(mem.content)
    return out


def _cited_texts(handles: list[str], packet: EvidencePacket) -> list[str]:
    out = []
    for h in handles:
        sym = packet.symbol(h)
        if sym and sym.source:
            out.append(sym.source)
        mem = packet.memory(h)
        if mem:
            out.append(mem.content)
    return out


def _classify(
    text: str,
    handles: list[str],
    packet: EvidencePacket,
    source: str,
    quote: str | None = None,
) -> Conclusion:
    """The strongest claim kind MARM can check for a verified result."""
    content = _without_handles(text).rstrip(".")
    cited = _cited_texts(handles, packet)
    want = _norm(content.strip("`\"' "))
    # A whole statement only: a fragment can drop the `never` that governs it.
    for unit in _statements(handles, packet):
        if want and _norm(unit) == want:
            kind = "quoted_span" if quote and _norm(quote) == want else None
            return Conclusion(content, unit, kind or "verbatim_statement", source)
    call = named_call(content, packet)
    if call and not call[2]:
        a, b, _ = call
        if (a.qualified_name, b.qualified_name) in packet.edges:
            return _call_edge(a, b, source)
    for path, line in _LINE_REF.findall(content):
        for h in handles:
            sym = packet.symbol(h)
            if (
                sym
                and sym.file_path.endswith(path)
                and sym.start_line <= int(line) <= max(sym.end_line, sym.start_line)
                and re.search(rf"\b{re.escape(sym.name)}\b", content)
            ):
                where = f"{sym.file_path}:{sym.start_line}-{sym.end_line}"
                return Conclusion(
                    f"`{sym.qualified_name}` is defined in {where}",
                    where,
                    "identifier_in_range",
                    source,
                )
    return Conclusion(content, (cited[0] if cited else "")[:500], "paraphrase", source)


def _from_item(item: Item, packet: EvidencePacket) -> Conclusion | None:
    if item.state != "verified" or item.op not in ("summary", "facts", "relations"):
        return None
    if item.op == "relations":
        if item.kind != "calls":
            # "M1 describes S1" says nothing durable about the code.
            return None
        a, b = packet.symbol(item.source or ""), packet.symbol(item.target or "")
        if a is None or b is None:
            return None
        return _call_edge(a, b, item.id)
    return _classify(item.text, list(item.cites), packet, item.id, item.quote)


def conclusions(brief: Brief) -> list[Conclusion]:
    """The verified answer's own results, most provable first."""
    found: list[Conclusion] = []
    if brief.operations:
        for item in brief.items:
            c = _from_item(item, brief.packet)
            if c:
                found.append(c)
    elif brief.answer:
        for n, claim in enumerate(_claims(brief.answer), start=1):
            if verify(claim, brief.packet).state != "verified":
                continue
            handles = [c.handle for c in extract_citations(claim, brief.packet)[0]]
            found.append(_classify(claim, handles, brief.packet, f"C{n}"))
    rank = {kind: i for i, kind in enumerate((*MECHANICAL, "paraphrase"))}
    unique: dict[str, Conclusion] = {}
    for c in sorted(found, key=lambda c: rank[c.claim_kind]):
        if len(c.content) >= 12:
            unique.setdefault(_norm(c.content), c)
    return list(unique.values())[:_MAX_STAGED]


async def stage_conclusions(
    memory: Any, brief: Brief, task: str, *, session_name: str, project: str | None
) -> dict[str, Any]:
    if not brief.answer:
        return {"staged": [], "skipped": [{"content": "", "reason": "no answer"}]}
    state = brief.verification.state if brief.verification else brief.status
    if state != "verified":
        # An uncertain answer never becomes verified by being restated.
        reason = f"the answer is {state}, not verified, so nothing is staged"
        return {"staged": [], "skipped": [{"content": "", "reason": reason}]}
    found = conclusions(brief)
    if not found:
        return {
            "staged": [],
            "skipped": [{"content": "", "reason": "nothing durable to propose"}],
        }
    skipped: list[dict[str, str]] = []
    # Resolved as `propose` does: a reviewer applies the staged row as it stands.
    resolutions = await resolve(
        memory,
        [Candidate(content=c.content, score=1.0, reasons=()) for c in found],
        session=None,
        project=project,
    )
    staged: list[str] = []
    now = distill_service._now()
    expires = (now + timedelta(hours=distill_service.TTL_HOURS)).isoformat()
    answer = brief.verification.to_public() if brief.verification else {}
    with memory.get_connection() as conn:
        for c, resolution in zip(found, resolutions):
            if resolution.verdict == "duplicate":
                skipped.append({"content": c.content, "reason": "already recorded"})
                continue
            verification = {
                "state": "verified",
                "claim_kind": c.claim_kind,
                "result": c.source,
                "packet_id": brief.packet.packet_id,
                "answer": answer,
            }
            row_id = str(uuid.uuid4())
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO distill_staging
                    (id, session_name, content, score, reasons, verdict, cosine,
                     neighbour_id, neighbour_content, status, candidate_hash,
                     project, context_type, applied_memory_id, expires_at,
                     created_at, updated_at, reviewed_at, evidence, mode,
                     origin, verification)
                VALUES (?, ?, ?, ?, '[]', ?, ?, ?, ?, 'pending', ?,
                        ?, 'code', NULL, ?, ?, ?, NULL, ?, 'analyst', 'analyst', ?)
                """,
                (
                    row_id,
                    session_name,
                    c.content,
                    1.0,
                    resolution.verdict,
                    resolution.cosine,
                    resolution.neighbour_id,
                    resolution.neighbour_content,
                    distill_service._hash(session_name, c.content, project),
                    project,
                    expires,
                    now.isoformat(),
                    now.isoformat(),
                    c.evidence,
                    json.dumps(verification),
                ),
            )
            if cur.rowcount:
                staged.append(row_id)
            else:
                skipped.append({"content": c.content, "reason": "already proposed"})
    return {"staged": staged, "skipped": skipped}


def auto_apply_allowed() -> bool:
    """A saved switch wins; the environment is only its default."""
    return runtime_flags.get_bool(
        runtime_flags.ANALYST_AUTO_APPLY, os.environ.get(AUTO_APPLY_ENV) == "1"
    )


@dataclass(frozen=True)
class Decision:
    apply: bool
    checks: dict[str, bool]
    reason: str

    def to_public(self) -> dict[str, Any]:
        return {
            "apply": self.apply,
            "status": "applied" if self.apply else "review_required",
            "checks": dict(self.checks),
            "reason": self.reason,
        }


def _provable(kind: str, content: str, evidence: str) -> bool:
    """Re-check the claim kind against what was stored, not what was said."""
    if kind == "call_edge":
        return bool(_CALL_EDGE.match(content)) and evidence.startswith("call edge ")
    if kind == "identifier_in_range":
        return bool(_IN_RANGE.match(content)) and content.endswith(evidence)
    if kind in ("quoted_span", "verbatim_statement"):
        # Equality: the stored evidence is the whole statement, so containment
        # would accept a claim cut out of a sentence that negates it.
        core = _norm(content.strip("`\"' "))
        return bool(core) and core == _norm(evidence.rstrip("."))
    return False


def source_units(text: str | None) -> frozenset[str]:
    """The source's whole sentences, normalised as a distilled span is."""
    return frozenset(
        _norm(_distill_normalise(u).rstrip(".")) for u in _source_sentences(text or "")
    )


def guardrail_decision(
    *,
    content: str,
    verdict: str,
    evidence: str,
    source_text: str | None,
    verification: dict[str, Any] | None,
    origin: str,
    units: frozenset[str] | None = None,
) -> Decision:
    headline = content.strip()
    checks = {
        "operator_enabled": auto_apply_allowed(),
        "novel": verdict == "new",
        "headline_shaped": "\n" not in headline and 12 <= len(headline) <= 300,
        # The evidence is stored with the memory, so it must be clean too.
        "no_secret": not _SECRET.search(content) and not _SECRET.search(evidence),
    }
    kind = (verification or {}).get("claim_kind", "paraphrase")
    if origin == "analyst":
        checks["verified"] = bool(
            verification
            and verification.get("state") == "verified"
            and (verification.get("answer") or {}).get("state") == "verified"
        )
        checks["mechanically_provable"] = kind in MECHANICAL and _provable(
            kind, content, evidence
        )
    else:
        # A whole sentence of the source, never a fragment of one: a fragment
        # can drop the `never` that governs it.
        span = _norm(_distill_normalise(evidence or content).rstrip("."))
        if units is None:
            units = source_units(source_text)
        checks["evidence_verbatim"] = bool(span) and span in units
        # Generated content is prose the model wrote; only its span is
        # verbatim, so a reviewer judges it.
        checks["content_is_span"] = not evidence or _norm(content.rstrip(".")) == span
    failed = [name for name, ok in checks.items() if not ok]
    if not failed:
        return Decision(True, checks, "all deterministic checks passed")
    if failed == ["operator_enabled"]:
        reason = (
            "review required: automatic apply is off "
            f"(the saved switch, or {AUTO_APPLY_ENV}=1 when none is saved)"
        )
    elif "mechanically_provable" in failed:
        reason = f"review required: MARM cannot prove a {kind} claim mechanically"
        rest = [f for f in failed if f != "mechanically_provable"]
        if rest:
            reason += f"; also failed {', '.join(rest)}"
    else:
        reason = f"review required: failed {', '.join(failed)}"
    return Decision(False, checks, reason)


async def auto_apply(
    memory: Any, proposal_ids: list[str], *, source_text: str | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # Once per run and off the event loop: a transcript may be 400,000 chars.
    units = await asyncio.to_thread(source_units, source_text)
    for pid in proposal_ids:
        # One proposal failing must not hide the decisions already made.
        try:
            entry = await _decide(memory, pid, source_text, units)
        except Exception:
            logger.exception("guardrails.decision_failed", proposal_id=pid)
            entry = {"proposal_id": pid, "applied": False, "error": "decision failed"}
        if entry is not None:
            out.append(entry)
    return out


async def _decide(
    memory: Any, pid: str, source_text: str | None, units: frozenset[str]
) -> dict[str, Any] | None:
    with memory.get_connection() as conn:
        row = conn.execute(
            "SELECT content, verdict, evidence, origin, verification, project "
            "FROM distill_staging WHERE id = ? AND status = 'pending'",
            (pid,),
        ).fetchone()
    if row is None:
        return None
    content, verdict, evidence, origin, verification, project = row
    # Novelty at decision time, whatever staged it: another process may
    # have stored the same fact since.
    (resolution,) = await resolve(
        memory,
        [Candidate(content=content, score=1.0, reasons=())],
        session=None,
        project=project,
    )
    verdict = resolution.verdict
    decision = guardrail_decision(
        content=content,
        verdict=verdict,
        evidence=evidence or "",
        source_text=source_text,
        verification=json.loads(verification) if verification else None,
        origin=origin or "distill",
        units=units,
    )
    # Recorded before any write, so an apply that fails still leaves its reason.
    with memory.get_connection() as conn:
        conn.execute(
            "UPDATE distill_staging SET decision = ? WHERE id = ?",
            (json.dumps(decision.to_public()), pid),
        )
    logger.info(
        "guardrails.decision",
        proposal_id=pid,
        apply=decision.apply,
        checks=decision.checks,
    )
    public = decision.to_public()
    entry: dict[str, Any] = {
        "proposal_id": pid,
        "applied": False,
        "decision": public,
    }
    if decision.apply:
        result = await distill_service.apply(memory, pid)
        entry["applied"] = result.get("status") == "success"
        if entry["applied"]:
            entry["memory_id"] = result["memory_id"]
        else:
            # Eligible is not written: the record says what happened.
            error = str(result.get("error") or result.get("message") or "apply failed")
            public["status"] = "apply_failed"
            public["error"] = entry["error"] = error
            with memory.get_connection() as conn:
                conn.execute(
                    "UPDATE distill_staging SET decision = ? WHERE id = ?",
                    (json.dumps(public), pid),
                )
    return entry
