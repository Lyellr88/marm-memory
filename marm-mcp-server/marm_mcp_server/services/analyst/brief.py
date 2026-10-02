"""Run the model inside its profile, over one packet, and judge the result.

The model reads the packet MARM built and nothing else: it cannot ask for
more retrieval. No call starts after the run's deadline, and no call may ask
for more tokens than the profile's cap.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from .. import local_llm
from ..code_context.compose import Context
from .ops import Item, OpResult, run_operations
from .packet import EvidencePacket, build_packet, render_packet
from .profile import Profile, Run
from .verify import (
    Citation,
    Disagreement,
    Verification,
    disagreements,
    extract_citations,
    verify,
)

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

_STATUS = {"verified": "ok", "uncertain": "unverified", "rejected": "rejected"}
#: The only finish that means the model ended the reply itself. A length cap,
#: a deadline, a dropped stream or a missing reason all leave it incomplete.
_FINISHED = ("stop",)
_SUBSTANTIVE = ("summary", "facts", "relations")

_UNAVAILABLE_HINT = (
    "Local generation is off or no local model is reachable, so the ranked "
    "context is the whole answer. Enable it in System > Controls or with "
    "MARM_LLM_ENABLED=1, with an OpenAI-compatible server on loopback."
)
_EMPTY_HINT = (
    "The local model did not return a usable answer within the profile's "
    "limits. The ranked context is unaffected."
)


@dataclass
class Brief:
    packet: EvidencePacket
    profile: Profile
    answer: str | None = None
    verification: Verification | None = None
    citations: list[Citation] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    model_id: str | None = None
    model_info: dict[str, Any] = field(default_factory=dict)
    status: str = "unavailable"
    hint: str | None = None
    truncated: bool = False
    operations: list[OpResult] = field(default_factory=list)
    disagreements: list[Disagreement] = field(default_factory=list)

    @property
    def items(self) -> list[Item]:
        return [i for r in self.operations for i in r.items]

    def _analysis(self) -> dict[str, Any]:
        """What the JSON response and the stream's `done` both carry."""
        out: dict[str, Any] = {
            "profile": self.profile.to_public(),
            "disagreements": [d.to_public() for d in self.disagreements],
        }
        if self.operations:
            out["operations"] = [
                {k: v for k, v in r.to_public().items() if k != "items"}
                for r in self.operations
            ]
            out["items"] = [i.to_public() for i in self.items]
        return out

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
        out.update({f"answer_{k}": v for k, v in self._analysis().items()})
        return out

    def to_done_event(self) -> dict[str, Any]:
        """The SSE `done` payload: #218's keys, plus the same analysis."""
        done: dict[str, Any] = {
            "citations": [c.to_public() for c in self.citations],
            "unresolved": self.unresolved,
            "status": self.status,
            "length": len(self.answer or ""),
            "truncated": self.truncated,
            "packet_id": self.packet.packet_id,
            "model_info": self.model_info,
            **self._analysis(),
        }
        if self.verification is not None:
            done["verification"] = self.verification.to_public()
        if self.hint:
            done["hint"] = self.hint
        return done


def _user(packet: EvidencePacket, task: str) -> str:
    return (
        f"{render_packet(packet)}\n\n---\n\nQuestion: {task}\n\nAnswer, citing handles:"
    )


def _packet(ctx: Context, profile: Profile) -> EvidencePacket:
    return build_packet(
        ctx,
        max_symbols=profile.max_symbols,
        max_memories=profile.max_memories,
        max_chars=profile.context_chars,
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


def _endpoint_source() -> str | None:
    try:
        return local_llm.endpoint_source()
    except Exception:  # pragma: no cover - reporting must never fail an answer
        return None


def _model_info(brief: Brief, run: Run, *, calls: int, output_chars: int) -> dict:
    p = brief.profile
    return {
        "id": brief.model_id,
        "endpoint_source": _endpoint_source(),
        "profile": p.name,
        # The cap each call requested. Nothing widens it.
        "max_tokens": p.max_tokens,
        "output_tokens": p.output_tokens,
        "reasoning_tokens": p.reasoning_tokens,
        "time_s": p.time_s,
        "calls": calls,
        "elapsed_ms": run.elapsed_ms(),
        "stopped": run.stop_reason(),
        "output_chars": output_chars,
    }


def _start(ctx: Context, profile: Profile, model: str) -> Brief:
    packet = _packet(ctx, profile)
    brief = Brief(
        packet=packet,
        profile=profile,
        model_id=model,
        disagreements=disagreements(packet),
    )
    return brief


def _judge_text(
    brief: Brief, run: Run, text: str | None, finish: str | None, *, calls: int
) -> Brief:
    """The free-form answer's verdict. A reply cut off by a limit is judged,
    but never verified: its missing end may be what qualified the rest."""
    brief.model_info = _model_info(
        brief, run, calls=calls, output_chars=len(text or "")
    )
    if not text or not text.strip():
        brief.status = "failed"
        brief.hint = _EMPTY_HINT
        return brief
    brief.answer = text
    brief.truncated = finish not in _FINISHED or brief.model_info["stopped"] is not None
    v = verify(text, brief.packet)
    if brief.truncated and v.state == "verified":
        v = replace(
            v,
            state="uncertain",
            failures=(*v.failures, f"the answer did not finish ({finish})"),
        )
    brief.verification = v
    brief.citations, brief.unresolved = extract_citations(text, brief.packet)
    brief.status = _STATUS[v.state]
    brief.hint = _hint(v, brief.unresolved)
    return brief


_MARKS = {"uncertain": " (unverified)", "rejected": " (rejected)"}


def _cites(handles: tuple[str, ...]) -> str:
    return " ".join(f"[{h}]" for h in handles)


def _line(i: Item) -> str:
    if i.op == "facts":
        return f"{i.text} {_cites(i.cites)} (quote: `{i.quote}`)"
    if i.op == "relations":
        return f"{i.text} [{i.source}] [{i.target}]"
    if i.op == "next_steps":
        return f"{i.action}: {i.text} {_cites(i.cites)}"
    if i.op == "gaps":
        return i.text
    return f"{i.text} {_cites(i.cites)}"


_TITLES = (
    ("facts", "Facts"),
    ("relations", "Relations"),
    ("gaps", "Missing from the evidence"),
    ("next_steps", "Next steps"),
)


def _render(results: list[OpResult]) -> str:
    """One readable answer from the structured items, each still cited."""
    by_op = {r.op: r.items for r in results}
    sections = []
    summary = by_op.get("summary", [])
    if summary:
        sections.append(
            "\n".join(f"{_line(i)}{_MARKS.get(i.state, '')}" for i in summary)
        )
    for op, title in _TITLES:
        items = by_op.get(op, [])
        if items:
            body = "\n".join(f"- {_line(i)}{_MARKS.get(i.state, '')}" for i in items)
            sections.append(f"{title}:\n{body}")
    return "\n\n".join(sections)


def _share(pool: list[Item], ok: Callable[[Item], bool]) -> float:
    return 1.0 if not pool else sum(1 for i in pool if ok(i)) / len(pool)


def aggregate(results: list[OpResult]) -> Verification:
    """Every result verified on its own; the whole is only as good as its parts.

    Verified needs at least one substantive item, every substantive item
    verified, and every operation complete. A missing or malformed part leaves
    the answer uncertain rather than a verified subset of what was asked.
    """
    items = [i for r in results for i in r.items]
    substantive = [i for i in items if i.op in _SUBSTANTIVE]
    hard = tuple(dict.fromkeys(f for i in items for f in i.hard_failures))
    incomplete = [r for r in results if not r.complete]

    if substantive:
        coverage = _share(substantive, lambda i: not i.hard_failures)
        verified = _share(substantive, lambda i: i.state == "verified")
    else:
        coverage = verified = 0.0
    support = _share(
        [i for i in substantive if i.op == "facts"], lambda i: i.support == "quote"
    )
    consistency = _share(
        [i for i in substantive if i.op == "relations"],
        lambda i: i.state == "verified",
    )

    if hard:
        state = "rejected"
    elif substantive and verified == 1.0 and not incomplete:
        state = "verified"
    else:
        state = "uncertain"
    failures = [f"{i.id}: {f}" for i in items for f in i.failures]
    for r in incomplete:
        extra = f" ({r.malformed} malformed)" if r.malformed else ""
        failures.append(f"{r.op}: {r.status}{extra}")
    return Verification(
        state=state,
        score=min(coverage, support, consistency, verified),
        citation_coverage=coverage,
        source_span_support=support,
        graph_memory_consistency=consistency,
        claims=len(substantive),
        cited_claims=sum(1 for i in substantive if not i.hard_failures),
        failures=tuple(failures),
        hard_failures=hard,
        abstained=not substantive and any(i.op == "gaps" for i in items),
    )


def _judge_operations(brief: Brief, run: Run, results: list[OpResult]) -> Brief:
    brief.operations = results
    ran = [r for r in results if r.status != "skipped"]
    if brief.profile.batch:
        calls = int(bool(ran))
        chars = max((r.output_chars for r in ran), default=0)
    else:
        calls, chars = len(ran), sum(r.output_chars for r in ran)
    brief.model_info = _model_info(brief, run, calls=calls, output_chars=chars)
    brief.truncated = any(
        r.finish in {"length", "deadline", "cancelled"} for r in results
    )
    brief.verification = aggregate(results)
    if not brief.items:
        brief.status = "failed"
        brief.hint = _EMPTY_HINT
        return brief
    brief.answer = _render(results)
    brief.citations, brief.unresolved = extract_citations(brief.answer, brief.packet)
    brief.status = _STATUS[brief.verification.state]
    brief.hint = _hint(brief.verification, brief.unresolved)
    return brief


def _general(brief: Brief, run: Run, task: str) -> Brief:
    stopped = run.stop_reason()
    if stopped:
        return _judge_text(brief, run, None, stopped, calls=0)
    finished: dict[str, Any] = {}
    text = local_llm.complete(
        SYSTEM,
        _user(brief.packet, task),
        max_tokens=brief.profile.max_tokens,
        timeout=run.remaining(),
        widen=False,
        finished=finished,
        deadline=run.deadline,
    )
    return _judge_text(brief, run, text, finished.get("reason"), calls=1)


def _analyse_sync(
    ctx: Context, task: str, profile: Profile, model: str, run: Run
) -> Brief:
    brief = _start(ctx, profile, model)
    if not profile.structured:
        return _general(brief, run, task)
    results = list(run_operations(brief.packet, task, profile, run))
    return _judge_operations(brief, run, results)


async def analyse(ctx: Context, task: str, *, profile: Profile) -> Brief:
    # Before the probe: finding the model is part of the run's time.
    run = profile.start()
    model = await asyncio.to_thread(local_llm.available)
    if model is None:
        return Brief(
            packet=_packet(ctx, profile), profile=profile, hint=_UNAVAILABLE_HINT
        )
    return await asyncio.to_thread(_analyse_sync, ctx, task, profile, model, run)


def stream_analysis(
    ctx: Context,
    task: str,
    *,
    profile: Profile,
    after: Callable[[Brief], dict] | None = None,
) -> Iterator[tuple[str, dict]]:
    """Yield the answer as it is produced, then the same verdict `analyse` gives.

    `after` sees the judged brief before `done` is sent; its result rides on
    `done` as `analyst`.
    """
    run = profile.start()
    model = local_llm.available()
    if model is None:
        yield (
            "error",
            {"message": "No local model is reachable.", "hint": _UNAVAILABLE_HINT},
        )
        return
    brief = _start(ctx, profile, model)
    packet = brief.packet
    yield ("packet", packet.to_public())
    yield (
        "start",
        {
            "project": packet.project,
            "symbol_count": len(packet.symbols),
            "model": model,
            "packet_id": packet.packet_id,
            "profile": profile.to_public(),
        },
    )
    if profile.structured:
        results: list[OpResult] = []
        for result in run_operations(packet, task, profile, run):
            results.append(result)
            yield ("operation", result.to_public())
        judged = _judge_operations(brief, run, results)
        if judged.answer:
            yield ("delta", {"text": judged.answer})
    else:
        judged = yield from _stream_general(brief, run, task)
    if not judged.answer:
        yield ("error", {"message": judged.hint or _EMPTY_HINT})
        return
    done = judged.to_done_event()
    if after is not None:
        done["analyst"] = after(judged)
    yield ("done", done)


def _stream_general(
    brief: Brief, run: Run, task: str
) -> Generator[tuple[str, dict], None, Brief]:
    stopped = run.stop_reason()
    if stopped:
        return _judge_text(brief, run, None, stopped, calls=0)
    finished: dict[str, Any] = {}
    pieces: list[str] = []
    upstream = local_llm.stream(
        SYSTEM,
        _user(brief.packet, task),
        max_tokens=brief.profile.max_tokens,
        timeout=run.remaining(),
        finished=finished,
        deadline=run.deadline,
    )
    try:
        for piece in upstream:
            if run.stop_reason():
                break
            pieces.append(piece)
            yield ("delta", {"text": piece})
    finally:
        # Closing the model's stream closes its HTTP response, so a reader
        # who leaves stops the generation rather than orphaning it.
        upstream.close()
    return _judge_text(brief, run, "".join(pieces), finished.get("reason"), calls=1)
