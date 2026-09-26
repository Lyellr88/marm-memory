"""Narrow operations over one packet, each with a fixed structured contract.

Every profile runs the same operations with the same schemas and the same
checks. A profile only decides whether they share one model call; each
result is parsed and verified on its own either way.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from .. import local_llm
from .packet import EvidencePacket, render_packet
from .profile import Profile, Run
from .verify import check_item

Handle = Annotated[str, StringConstraints(pattern=r"^[SMsm][0-9]{1,3}$")]
Cites = Annotated[list[Handle], Field(min_length=1, max_length=4)]

_TEXT = 240
_SHORT = 160


class _Item(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class SummaryItem(_Item):
    text: str = Field(min_length=1, max_length=_TEXT)
    cites: Cites


class FactItem(_Item):
    text: str = Field(min_length=1, max_length=_TEXT)
    cites: Cites
    quote: str = Field(min_length=1, max_length=_TEXT)


class RelationItem(_Item):
    kind: Literal["calls", "memory_about"]
    source: Handle = Field(alias="from")
    target: Handle = Field(alias="to")
    text: str = Field(min_length=1, max_length=_SHORT)


class GapItem(_Item):
    text: str = Field(min_length=1, max_length=_SHORT)


class NextStepItem(_Item):
    action: Literal["read", "compare", "verify", "ask"]
    cites: Cites
    text: str = Field(min_length=1, max_length=_SHORT)


@dataclass(frozen=True)
class Operation:
    name: str
    key: str
    prefix: str
    item: type[_Item]
    limit: int
    instruction: str
    example: str


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "summary",
        "summary",
        "A",
        SummaryItem,
        3,
        "Answer the question in at most 3 short statements, each citing the "
        "handles that support it.",
        '{"summary": [{"text": "...", "cites": ["S1"]}]}',
    ),
    Operation(
        "facts",
        "facts",
        "F",
        FactItem,
        5,
        "List at most 5 facts from the packet that bear on the question. For "
        "each, copy `quote` character for character from the source or memory "
        "of one handle it cites.",
        '{"facts": [{"text": "...", "cites": ["S1"], "quote": "..."}]}',
    ),
    Operation(
        "relations",
        "relations",
        "R",
        RelationItem,
        5,
        'List at most 5 relationships that bear on the question: kind "calls" '
        'when symbol `from` calls symbol `to` (see Calls), kind "memory_about" '
        "when memory `from` describes symbol `to`.",
        '{"relations": [{"kind": "calls", "from": "S1", "to": "S2", "text": "..."}]}',
    ),
    Operation(
        "gaps",
        "missing",
        "G",
        GapItem,
        3,
        "List at most 3 things the question needs that the packet does not "
        "show. Describe what is missing; cite nothing.",
        '{"missing": [{"text": "..."}]}',
    ),
    Operation(
        "next_steps",
        "next_steps",
        "N",
        NextStepItem,
        3,
        "Propose at most 3 low-risk next steps for a reader checking the "
        "answer, each one of read, compare, verify or ask, citing the handles "
        "involved. Never propose changing, running or deleting anything.",
        '{"next_steps": [{"action": "read", "cites": ["S1"], "text": "..."}]}',
    ),
)

BY_NAME = {op.name: op for op in OPERATIONS}

_RULES = """\
You read one evidence packet about a codebase and answer ONLY from it.
Cite packet handles exactly as listed: S1 for a symbol, M1 for a recorded \
memory. Never cite a handle the packet does not list. Leave out anything the \
packet does not support; an empty list is a correct answer.
Reply with JSON only."""


def _inline(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve `$ref`s, which not every local grammar converter follows."""
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    inlined: dict[str, Any] = walk(schema)
    return inlined


def _list_schema(op: Operation) -> dict[str, Any]:
    item = _inline(op.item.model_json_schema(by_alias=True))
    item["additionalProperties"] = False
    return {"type": "array", "items": item, "maxItems": op.limit}


def schema(ops: tuple[Operation, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {op.key: _list_schema(op) for op in ops},
        "required": [op.key for op in ops],
        "additionalProperties": False,
    }


#: Characters per token when estimating a reply's worst case. JSON punctuation
#: and quoted code tokenise poorly, so this is deliberately low.
_CHARS_PER_TOKEN = 3


def worst_case_tokens(ops: tuple[Operation, ...]) -> int:
    """Tokens for the largest reply the schemas admit."""
    chars = 0
    for op in ops:
        props = _list_schema(op)["items"]["properties"]
        per_item = 0
        for name, spec in props.items():
            if spec.get("type") == "array":
                per_item += spec.get("maxItems", 1) * 8
            else:
                per_item += spec.get("maxLength", 12)
            per_item += len(name) + 6
        chars += op.limit * per_item + len(op.key) + 8
    return chars // _CHARS_PER_TOKEN + 16


def _system(ops: tuple[Operation, ...]) -> str:
    tasks = "\n".join(f"- {op.key}: {op.instruction}" for op in ops)
    shape = (
        ops[0].example
        if len(ops) == 1
        else "{" + ", ".join(f'"{op.key}": [...]' for op in ops) + "}"
    )
    return f"{_RULES}\n\nTASK\n{tasks}\n\nReply shape: {shape}"


def _user(packet: EvidencePacket, task: str) -> str:
    return f"{render_packet(packet)}\n\n---\n\nQuestion: {task}"


@dataclass(frozen=True)
class Item:
    id: str
    op: str
    text: str
    state: str
    support: str
    cites: tuple[str, ...] = ()
    quote: str | None = None
    kind: str | None = None
    source: str | None = None
    target: str | None = None
    action: str | None = None
    failures: tuple[str, ...] = ()
    hard_failures: tuple[str, ...] = ()

    def to_public(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": self.id,
            "op": self.op,
            "text": self.text,
            "state": self.state,
            "support": self.support,
            "cites": list(self.cites),
            "failures": list(self.failures) + list(self.hard_failures),
        }
        for key in ("quote", "kind", "action"):
            if getattr(self, key) is not None:
                row[key] = getattr(self, key)
        if self.source is not None:
            row["from"], row["to"] = self.source, self.target
        return row


@dataclass
class OpResult:
    op: str
    #: ok | empty | malformed | failed | skipped
    status: str
    items: list[Item] = field(default_factory=list)
    #: Entries that did not fit the contract, and entries past the limit.
    malformed: int = 0
    dropped: int = 0
    finish: str | None = None
    elapsed_ms: int = 0
    output_chars: int = 0

    @property
    def complete(self) -> bool:
        return self.status in {"ok", "empty"} and not self.malformed

    def to_public(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "status": self.status,
            "items": [i.to_public() for i in self.items],
            "malformed": self.malformed,
            "dropped": self.dropped,
            "finish": self.finish,
            "elapsed_ms": self.elapsed_ms,
            "output_chars": self.output_chars,
        }


def _judge(op: Operation, n: int, entry: _Item, packet: EvidencePacket) -> Item:
    data = entry.model_dump()
    cites = tuple(h.upper() for h in data.get("cites") or ())
    source = data.get("source")
    target = data.get("target")
    source = source.upper() if source else None
    target = target.upper() if target else None
    check = check_item(
        op.name,
        text=data["text"],
        packet=packet,
        cites=cites,
        quote=data.get("quote"),
        kind=data.get("kind"),
        source=source,
        target=target,
    )
    return Item(
        id=f"{op.prefix}{n}",
        op=op.name,
        text=data["text"],
        state=check.state,
        support=check.support,
        cites=cites,
        quote=data.get("quote"),
        kind=data.get("kind"),
        source=source,
        target=target,
        action=data.get("action"),
        failures=check.failures,
        hard_failures=check.hard_failures,
    )


def parse(op: Operation, reply: Any, packet: EvidencePacket) -> OpResult:
    """Validate one operation's result; an entry that does not fit is dropped
    and counted, never repaired."""
    if not isinstance(reply, dict) or not isinstance(reply.get(op.key), list):
        return OpResult(op.name, "malformed", malformed=1)
    entries = reply[op.key]
    result = OpResult(op.name, "ok", dropped=max(0, len(entries) - op.limit))
    for entry in entries[: op.limit]:
        try:
            item = op.item.model_validate(entry)
        except ValidationError:
            result.malformed += 1
            continue
        result.items.append(_judge(op, len(result.items) + 1, item, packet))
    if not result.items:
        result.status = "malformed" if result.malformed else "empty"
    return result


def _call(
    ops: tuple[Operation, ...], packet: EvidencePacket, task: str, run: Run
) -> tuple[Any, str | None, int, int]:
    finished: dict[str, Any] = {}
    started = time.monotonic()
    text = local_llm.complete(
        _system(ops),
        _user(packet, task),
        max_tokens=run.profile.max_tokens,
        timeout=run.remaining(),
        schema=schema(ops),
        widen=False,
        finished=finished,
    )
    elapsed = int((time.monotonic() - started) * 1000)
    value = local_llm._first_json_value(text) if text else None
    return value, finished.get("reason"), elapsed, len(text or "")


def _unanswered(
    op: Operation, finish: str | None, elapsed: int, chars: int
) -> OpResult:
    # A reply cut off at the cap is incomplete, not merely badly shaped.
    status = "failed" if finish == "length" or not chars else "malformed"
    return OpResult(
        op.name,
        status,
        finish=finish,
        elapsed_ms=elapsed,
        output_chars=chars,
        malformed=int(status == "malformed"),
    )


def run_operations(
    packet: EvidencePacket, task: str, profile: Profile, run: Run
) -> Iterator[OpResult]:
    """Yield each operation's verified result as it completes.

    No call starts once the run is out of time, and none may take longer than
    what remains of it.
    """
    groups = [OPERATIONS] if profile.batch else [(op,) for op in OPERATIONS]
    for ops in groups:
        stopped = run.stop_reason()
        if stopped:
            for op in ops:
                yield OpResult(op.name, "skipped", finish=stopped)
            continue
        value, finish, elapsed, chars = _call(ops, packet, task, run)
        for op in ops:
            if finish == "length" or not isinstance(value, dict):
                yield _unanswered(op, finish, elapsed, chars)
                continue
            result = parse(op, value, packet)
            result.finish, result.elapsed_ms, result.output_chars = (
                finish,
                elapsed,
                chars,
            )
            yield result


__all__ = [
    "BY_NAME",
    "OPERATIONS",
    "Item",
    "OpResult",
    "Operation",
    "parse",
    "run_operations",
    "schema",
    "worst_case_tokens",
]
