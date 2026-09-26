"""Run the model inside its budget, over one packet, and judge the result.

The model never retrieves anything. When follow-ups are allowed it may ask
for one, and MARM runs that retrieval itself and merges the result into the
same packet before the answer is written.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from .. import local_llm
from ..code_context.backend import GraphUnavailable, LocalBackend
from ..code_context.compose import Context, build
from .budget import Budget, Run
from .packet import EvidencePacket, build_packet, render_packet
from .verify import Citation, Verification, extract_citations, verify

SYSTEM = """\
You answer questions about one codebase using ONLY the evidence packet below.

RULES
1. Use only the packet. If it does not contain the answer, say exactly what is \
missing and stop. Never fill a gap from general knowledge of similar projects.
2. Cite every claim in square brackets with the handles the packet gives: [S1] \
for a symbol, [M2] for a recorded memory. Cite only handles that appear in the \
packet.
3. Quote identifiers exactly as the packet spells them, in backticks.
4. Be brief. Lead with the answer, then the evidence.
5. If recorded memory and the source disagree, say so and cite both.\
"""

_FOLLOW_UP = """\
Before answering: is the packet enough to answer the question? Reply with \
exactly READY, or with one line NEED: <what to look up>, naming symbols or \
behaviour. Nothing else.\
"""

_STATUS = {"verified": "ok", "uncertain": "unverified", "rejected": "rejected"}

#: A merged packet may grow past the default cap by what follow-ups added, but
#: never without bound.
_MAX_SYMBOLS = 48

_UNAVAILABLE_HINT = (
    "Local generation is off or no local model is reachable, so the ranked "
    "context is the whole answer. Enable it in System > Controls or with "
    "MARM_LLM_ENABLED=1, with an OpenAI-compatible server on loopback."
)


@dataclass
class Brief:
    packet: EvidencePacket
    answer: str | None = None
    verification: Verification | None = None
    citations: list[Citation] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    model_id: str | None = None
    model_info: dict[str, Any] = field(default_factory=dict)
    status: str = "unavailable"
    hint: str | None = None
    truncated: bool = False
    follow_ups_used: int = 0

    def to_answer_fields(self) -> dict[str, Any]:
        """The keys a `marm_code_context(answer=true)` response carries."""
        out: dict[str, Any] = {"answer": self.answer, "answer_status": self.status}
        if self.hint:
            out["answer_hint"] = self.hint
        if self.status == "unavailable":
            return out
        out["answer_model"] = self.model_id
        out["answer_model_info"] = self.model_info
        out["answer_citations"] = [c.to_public() for c in self.citations]
        out["answer_unresolved"] = self.unresolved
        out["answer_packet"] = self.packet.to_public()
        if self.verification is not None:
            out["answer_verification"] = self.verification.to_public()
        if self.follow_ups_used:
            out["answer_follow_ups"] = self.follow_ups_used
        return out

    def to_done_event(self, length: int) -> dict[str, Any]:
        """The SSE `done` payload: #218's keys, plus the verification."""
        done: dict[str, Any] = {
            "citations": [c.to_public() for c in self.citations],
            "unresolved": self.unresolved,
            "status": self.status,
            "length": length,
            "truncated": self.truncated,
            "packet_id": self.packet.packet_id,
            "model_info": self.model_info,
        }
        if self.verification is not None:
            done["verification"] = self.verification.to_public()
        if self.hint:
            done["hint"] = self.hint
        if self.follow_ups_used:
            done["follow_ups"] = self.follow_ups_used
        return done


def _user(packet: EvidencePacket, task: str) -> str:
    return (
        f"{render_packet(packet)}\n\n---\n\nQuestion: {task}\n\nAnswer, citing handles:"
    )


def _hint(v: Verification, unresolved: list[str]) -> str | None:
    if v.state == "verified":
        return None
    if v.state == "rejected":
        return (
            "The answer cites "
            + ", ".join(unresolved[:5])
            + ", which the evidence packet does not contain, so it is rejected."
        )
    if v.abstained:
        return "The model reported that the evidence does not answer this."
    if not v.cited_claims:
        return (
            "No citation in the answer resolves to the evidence packet, so it is "
            "not grounded in the evidence shown."
        )
    return "Only part of the answer is supported: " + "; ".join(v.failures[:3]) + "."


def _judge(brief: Brief, text: str) -> Brief:
    brief.answer = text
    brief.verification = verify(text, brief.packet)
    brief.citations, brief.unresolved = extract_citations(text, brief.packet)
    brief.status = _STATUS[brief.verification.state]
    brief.hint = _hint(brief.verification, brief.unresolved)
    return brief


def _endpoint_source() -> str | None:
    try:
        return local_llm.endpoint_source()
    except Exception:  # pragma: no cover - reporting must never fail an answer
        return None


def _model_info(
    model: str, max_tokens: int, started: float, run: Run, stopped: str | None
) -> dict[str, Any]:
    return {
        "id": model,
        "endpoint_source": _endpoint_source(),
        "max_tokens": max_tokens,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "stopped": stopped or run.stop_reason(),
    }


def _merge(base: Context, extra: Context) -> Context:
    """Append what a follow-up found, keeping every existing item in place so
    the handles already in the packet keep meaning the same thing."""
    known = {s.qualified_name for s in base.symbols}
    seen = {str(m.get("id") or m.get("content", ""))[:200] for m in base.memories}
    return Context(
        project=base.project,
        task=base.task,
        symbols=base.symbols
        + [s for s in extra.symbols if s.qualified_name not in known],
        memories=base.memories
        + [
            m
            for m in extra.memories
            if str(m.get("id") or m.get("content", ""))[:200] not in seen
        ],
        links=base.links + [ln for ln in extra.links if ln not in base.links],
        notes=base.notes + [n for n in extra.notes if n not in base.notes],
        seed_count=base.seed_count,
        graph_nodes=base.graph_nodes,
        graph_edges=base.graph_edges
        + [e for e in extra.graph_edges if e not in base.graph_edges],
    )


def _packet(ctx: Context) -> EvidencePacket:
    return build_packet(ctx, max_symbols=min(max(24, len(ctx.symbols)), _MAX_SYMBOLS))


async def _expand(
    ctx: Context,
    task: str,
    run: Run,
    backend: LocalBackend | None,
    project: str | None,
    cwd: str | None,
) -> tuple[Context, int]:
    used = 0
    while used < run.budget.follow_ups and run.stop_reason() is None:
        reply = await asyncio.to_thread(
            local_llm.complete,
            _FOLLOW_UP,
            _user(_packet(ctx), task),
            max_tokens=64,
            timeout=max(run.remaining(), 1.0),
        )
        line = (reply or "").strip().splitlines()[0] if reply and reply.strip() else ""
        if not line.upper().startswith("NEED:"):
            break
        query = line[5:].strip()[:300]
        if not query:
            break
        used += 1
        try:
            extra = await build(
                backend or LocalBackend(),
                query,
                cwd=cwd,
                project=project,
                # Each follow-up draws on half the budget, so two cannot
                # double the evidence the answer is asked to read.
                budget=max(500, run.budget.context_chars // 2),
            )
        except GraphUnavailable:
            break
        ctx = _merge(ctx, extra)
    return ctx, used


async def analyse(
    ctx: Context,
    task: str,
    *,
    budget: Budget,
    backend: LocalBackend | None = None,
    project: str | None = None,
    cwd: str | None = None,
) -> Brief:
    model = await asyncio.to_thread(local_llm.available)
    if model is None:
        return Brief(packet=_packet(ctx), hint=_UNAVAILABLE_HINT)
    run = budget.start()
    ctx, used = await _expand(ctx, task, run, backend, project, cwd)
    packet = _packet(ctx)
    started = time.monotonic()
    text = await asyncio.to_thread(
        local_llm.complete,
        SYSTEM,
        _user(packet, task),
        max_tokens=budget.output_tokens,
        timeout=max(run.remaining(), 1.0),
    )
    brief = Brief(packet=packet, model_id=model, follow_ups_used=used)
    brief.model_info = _model_info(model, budget.output_tokens, started, run, None)
    if not text or not text.strip():
        brief.status = "failed"
        brief.hint = (
            "The local model did not return an answer within its budget. The "
            "ranked context is unaffected."
        )
        return brief
    return _judge(brief, text)


def stream_analysis(
    ctx: Context,
    task: str,
    *,
    budget: Budget,
    render_context: Callable[[Context], dict] | None = None,
    backend: LocalBackend | None = None,
    project: str | None = None,
    cwd: str | None = None,
    after: Callable[[Brief], dict] | None = None,
) -> Iterator[tuple[str, dict]]:
    """Yield the answer as it is written, then its verification.

    `after` sees the judged brief before `done` is sent; its result rides on
    `done` as `analyst`.

    The caller has already sent `context`. A follow-up re-sends it through
    `render_context`, so what is displayed is always the evidence the answer
    was actually written from.
    """
    model = local_llm.available()
    if model is None:
        yield (
            "error",
            {"message": "No local model is reachable.", "hint": _UNAVAILABLE_HINT},
        )
        return
    run = budget.start()
    ctx, used = asyncio.run(_expand(ctx, task, run, backend, project, cwd))
    if used and render_context is not None:
        yield ("context", render_context(ctx))
    packet = _packet(ctx)
    yield ("packet", packet.to_public())
    yield (
        "start",
        {
            "project": packet.project,
            "symbol_count": len(packet.symbols),
            "model": model,
            "packet_id": packet.packet_id,
        },
    )

    prompt = _user(packet, task)
    max_tokens = budget.output_tokens
    finished: dict[str, Any] = {}
    pieces: list[str] = []
    stopped: str | None = None
    started = time.monotonic()
    for attempt in range(2):
        finished.clear()
        pieces = []
        upstream = local_llm.stream(
            SYSTEM,
            prompt,
            max_tokens=max_tokens,
            timeout=max(run.remaining(), 1.0),
            finished=finished,
        )
        try:
            for piece in upstream:
                stopped = run.stop_reason()
                if stopped:
                    break
                pieces.append(piece)
                yield ("delta", {"text": piece})
        finally:
            # Closing the model's stream closes its HTTP response, so a reader
            # who leaves stops the generation rather than orphaning it.
            upstream.close()
        if stopped:
            break
        wider = min(max_tokens * 4, local_llm.MAX_RETRY_TOKENS)
        if attempt or finished.get("reason") != "length" or wider <= max_tokens:
            break
        # The same single wider retry `complete` makes when a reasoning model
        # spends its budget before it finishes; what was sent is withdrawn.
        max_tokens = wider
        yield ("restart", {"reason": "length", "max_tokens": max_tokens})

    answer = "".join(pieces)
    if not answer.strip():
        yield (
            "error",
            {
                "message": (
                    "the model produced no answer text within its budget. A "
                    "reasoning model may have spent it before writing; raise "
                    "MARM_CODE_CONTEXT_ANSWER_TOKENS. The ranked context is "
                    "unaffected."
                )
            },
        )
        return
    brief = Brief(packet=packet, model_id=model, follow_ups_used=used)
    brief.model_info = _model_info(model, max_tokens, started, run, stopped)
    brief.truncated = finished.get("reason") == "length" or bool(stopped)
    judged = _judge(brief, answer)
    done = judged.to_done_event(len(answer))
    if after is not None:
        done["analyst"] = after(judged)
    yield ("done", done)
