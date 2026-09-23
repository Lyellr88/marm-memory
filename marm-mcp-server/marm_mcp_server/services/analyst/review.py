"""Stage what the analyst concluded; never write it.

A conclusion reaches memory only through `marm_distill apply`, the same
reviewed path every other proposal takes.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import timedelta
from typing import Any

from .. import distill as distill_service
from .. import local_llm
from .brief import Brief, _user
from .verify import extract_citations, verify

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
    reply = await asyncio.to_thread(
        local_llm.complete,
        CONCLUSIONS_SYSTEM,
        f"{_user(brief.packet, task)}\n\nYour answer:\n{brief.answer}",
        max_tokens=256,
    )
    staged: list[str] = []
    now = distill_service._now()
    expires = (now + timedelta(hours=distill_service.TTL_HOURS)).isoformat()
    with memory.get_connection() as conn:
        for line in parse_conclusions(reply or ""):
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
