"""Stage what the analyst concluded; never write it.

A conclusion reaches memory only through `marm_distill apply`, the same
reviewed path every other proposal takes.
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

from .. import distill as distill_service
from .. import local_llm
from .brief import Brief, _user
from .budget import Budget
from .verify import extract_citations, verify

logger = structlog.get_logger(__name__)

AUTO_APPLY_ENV = "MARM_ANALYST_AUTO_APPLY"
_SECRET = re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]|-----BEGIN")

CONCLUSIONS_SYSTEM = """\
From your answer below, state at most three durable facts about this codebase \
worth remembering. One line each, starting with "- ", each citing the packet \
handles that support it, e.g. "- apply claims the row before writing [S1] [S2]". \
If nothing is durable, reply with nothing.\
"""

_BULLET = re.compile(r"^\s*[-*]\s+(.+?)\s*$")


def parse_conclusions(text: str) -> list[str]:
    out: list[str] = []
    for line in (text or "").splitlines():
        m = _BULLET.match(line)
        if m:
            out.append(m.group(1))
        if len(out) == 3:
            break
    return out


def _evidence(brief: Brief, line: str) -> str:
    for c in extract_citations(line, brief.packet)[0]:
        if c.kind == "symbol":
            sym = brief.packet.symbol(c.handle)
            if sym and sym.source:
                return sym.source[:500]
    return ""


async def stage_conclusions(
    memory: Any, brief: Brief, task: str, *, session_name: str, project: str | None
) -> dict[str, Any]:
    skipped: list[dict[str, str]] = []
    if not brief.answer:
        return {"staged": [], "skipped": [{"content": "", "reason": "no answer"}]}
    if brief.verification is None or brief.verification.state == "rejected":
        return {"staged": [], "skipped": [{"content": "", "reason": "brief rejected"}]}
    # The answer's own budget: a reasoning model spends a small one thinking.
    reply = await asyncio.to_thread(
        local_llm.complete,
        CONCLUSIONS_SYSTEM,
        f"{_user(brief.packet, task)}\n\nYour answer:\n{brief.answer}",
        max_tokens=Budget.from_env().output_tokens,
    )
    if not reply or not reply.strip():
        reason = "the model wrote no conclusions within its budget"
        return {"staged": [], "skipped": [{"content": "", "reason": reason}]}
    lines = parse_conclusions(reply)
    if not lines:
        return {
            "staged": [],
            "skipped": [{"content": "", "reason": "nothing durable to propose"}],
        }
    staged: list[str] = []
    now = distill_service._now()
    expires = (now + timedelta(hours=distill_service.TTL_HOURS)).isoformat()
    with memory.get_connection() as conn:
        for line in lines:
            v = verify(line, brief.packet)
            if v.state != "verified":
                skipped.append({"content": line, "reason": f"not verified ({v.state})"})
                continue
            row_id = str(uuid.uuid4())
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO distill_staging
                    (id, session_name, content, score, reasons, verdict, cosine,
                     neighbour_id, neighbour_content, status, candidate_hash,
                     project, context_type, applied_memory_id, expires_at,
                     created_at, updated_at, reviewed_at, evidence, mode,
                     origin, verification)
                VALUES (?, ?, ?, ?, '[]', 'new', 0.0, NULL, NULL, 'pending', ?,
                        ?, 'code', NULL, ?, ?, ?, NULL, ?, 'analyst', 'analyst', ?)
                """,
                (
                    row_id,
                    session_name,
                    line,
                    v.score,
                    distill_service._hash(session_name, line, project),
                    project,
                    expires,
                    now.isoformat(),
                    now.isoformat(),
                    _evidence(brief, line),
                    json.dumps(v.to_public()),
                ),
            )
            if cur.rowcount:
                staged.append(row_id)
            else:
                skipped.append({"content": line, "reason": "already proposed"})
    return {"staged": staged, "skipped": skipped}


def auto_apply_allowed() -> bool:
    return os.environ.get(AUTO_APPLY_ENV) == "1"


@dataclass(frozen=True)
class Decision:
    apply: bool
    checks: dict[str, bool]
    reason: str

    def to_public(self) -> dict[str, Any]:
        return {"apply": self.apply, "checks": dict(self.checks), "reason": self.reason}


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def guardrail_decision(
    *,
    content: str,
    verdict: str,
    evidence: str,
    source_text: str | None,
    verification: dict[str, Any] | None,
    origin: str,
) -> Decision:
    headline = content.strip()
    checks = {
        "operator_enabled": auto_apply_allowed(),
        "novel": verdict == "new",
        "headline_shaped": "\n" not in headline and 12 <= len(headline) <= 300,
        "evidence_verbatim": (
            bool(evidence.strip())
            if origin == "analyst"
            else bool(source_text)
            and _norm(evidence or content) in _norm(source_text or "")
        ),
        "no_secret": not _SECRET.search(content),
    }
    if origin == "analyst":
        checks["verified"] = bool(
            verification
            and verification.get("state") == "verified"
            and float(verification.get("score") or 0) == 1.0
        )
    failed = [name for name, ok in checks.items() if not ok]
    if not failed:
        return Decision(True, checks, "all deterministic checks passed")
    if failed == ["operator_enabled"]:
        reason = f"review required: automatic apply is off ({AUTO_APPLY_ENV} is not 1)"
    else:
        reason = f"review required: failed {', '.join(failed)}"
    return Decision(False, checks, reason)


async def auto_apply(
    memory: Any, proposal_ids: list[str], *, source_text: str | None
) -> list[dict[str, Any]]:
    from ...core.distill import Candidate, resolve

    out: list[dict[str, Any]] = []
    for pid in proposal_ids:
        with memory.get_connection() as conn:
            row = conn.execute(
                "SELECT content, verdict, evidence, origin, verification, project "
                "FROM distill_staging WHERE id = ? AND status = 'pending'",
                (pid,),
            ).fetchone()
        if row is None:
            continue
        content, verdict, evidence, origin, verification, project = row
        if origin == "analyst":
            # Staged without the duplicate resolver; novelty needs it.
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
        entry: dict[str, Any] = {
            "proposal_id": pid,
            "applied": False,
            "decision": decision.to_public(),
        }
        if decision.apply:
            result = await distill_service.apply(memory, pid)
            entry["applied"] = result.get("status") == "success"
            if entry["applied"]:
                entry["memory_id"] = result["memory_id"]
        out.append(entry)
    return out
