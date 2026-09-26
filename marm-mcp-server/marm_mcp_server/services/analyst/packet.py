"""One bounded, content-addressed view of MARM's evidence for one question.

The model sees only this, and every claim it makes is checked against it, so
the handles it cites must be stable within a packet and meaningless outside it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..code_context.compose import Context
from ..code_context.format import _fence_for
from ..code_context.project import short_name


@dataclass(frozen=True)
class SymbolItem:
    handle: str
    qualified_name: str
    name: str
    label: str
    file_path: str
    start_line: int
    end_line: int
    source: str
    truncated: bool


@dataclass(frozen=True)
class MemoryItem:
    handle: str
    memory_id: str
    content: str
    similarity: float


@dataclass(frozen=True)
class EvidencePacket:
    packet_id: str
    project: str
    task: str
    symbols: tuple[SymbolItem, ...]
    memories: tuple[MemoryItem, ...]
    edges: frozenset[tuple[str, str]]
    links: frozenset[tuple[str, str]]
    _by_handle: dict = field(default_factory=dict, compare=False, repr=False)

    def symbol(self, handle: str) -> SymbolItem | None:
        item = self._by_handle.get(handle.upper())
        return item if isinstance(item, SymbolItem) else None

    def memory(self, handle: str) -> MemoryItem | None:
        item = self._by_handle.get(handle.upper())
        return item if isinstance(item, MemoryItem) else None

    def by_name(self, name: str) -> SymbolItem | None:
        key = name.casefold()
        for s in self.symbols:
            if key in (s.name.casefold(), s.qualified_name.casefold()):
                return s
        return None

    def to_public(self) -> dict:
        return {
            "packet_id": self.packet_id,
            "project": self.project,
            "task": self.task,
            "symbols": [
                {
                    "handle": s.handle,
                    "qualified_name": s.qualified_name,
                    "name": s.name,
                    "file_path": s.file_path,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                }
                for s in self.symbols
            ],
            "memories": [
                {"handle": m.handle, "memory_id": m.memory_id, "content": m.content}
                for m in self.memories
            ],
        }


def _digest(
    project: str,
    task: str,
    symbols: list[SymbolItem],
    memories: list[MemoryItem],
    edges: set[tuple[str, str]],
    links: set[tuple[str, str]],
) -> str:
    body = json.dumps(
        {
            "project": project,
            "task": task,
            "symbols": [
                [
                    s.qualified_name,
                    s.name,
                    s.label,
                    s.file_path,
                    s.start_line,
                    s.end_line,
                    s.truncated,
                    s.source,
                ]
                for s in symbols
            ],
            "memories": [[m.memory_id, m.content] for m in memories],
            "edges": sorted(edges),
            "links": sorted(links),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _assemble(
    project: str,
    task: str,
    symbols: list[SymbolItem],
    memories: list[MemoryItem],
    edges: set[tuple[str, str]],
    links: set[tuple[str, str]],
) -> EvidencePacket:
    index: dict = {s.handle: s for s in symbols}
    index.update({m.handle: m for m in memories})
    return EvidencePacket(
        packet_id=_digest(project, task, symbols, memories, edges, links),
        project=project,
        task=task,
        symbols=tuple(symbols),
        memories=tuple(memories),
        edges=frozenset(edges),
        links=frozenset(links),
        _by_handle=index,
    )


def build_packet(
    ctx: Context, *, max_symbols: int = 24, max_memories: int = 8
) -> EvidencePacket:
    symbols = [
        SymbolItem(
            handle=f"S{i}",
            qualified_name=s.qualified_name,
            name=s.name,
            label=s.label,
            file_path=s.file_path,
            start_line=s.start_line,
            end_line=s.end_line,
            source=s.source,
            truncated=s.truncated,
        )
        for i, s in enumerate(ctx.symbols[:max_symbols], start=1)
    ]
    memories = [
        MemoryItem(
            handle=f"M{i}",
            memory_id=str(m.get("id") or ""),
            content=" ".join(str(m.get("content") or "").split()),
            similarity=float(m.get("similarity") or 0.0),
        )
        for i, m in enumerate(ctx.memories[:max_memories], start=1)
    ]
    kept = {s.qualified_name for s in symbols}
    edges = {(a, b) for a, b, _ in ctx.graph_edges if a in kept and b in kept}
    links = set()
    for ln in ctx.links:
        qn = ln.get("qualified_name") or ln.get("graph_qualified_name") or ""
        if qn in kept:
            # A link names a concept, not a memory row; it vouches for every
            # memory in the packet that mentions the linked entity.
            entity = (ln.get("entity_name") or qn.split(".")[-1]).casefold()
            for m in memories:
                if entity and entity in m.content.casefold():
                    links.add((m.handle, qn))
    return _assemble(short_name(ctx.project), ctx.task, symbols, memories, edges, links)


def merge_packets(base: EvidencePacket, extra: EvidencePacket) -> EvidencePacket:
    symbols = list(base.symbols)
    known = {s.qualified_name for s in symbols}
    for s in extra.symbols:
        if s.qualified_name not in known:
            known.add(s.qualified_name)
            symbols.append(
                SymbolItem(**{**s.__dict__, "handle": f"S{len(symbols) + 1}"})
            )
    memories = list(base.memories)
    seen = {m.memory_id for m in memories}
    remap: dict[str, str] = {}
    for m in extra.memories:
        if m.memory_id in seen:
            continue
        seen.add(m.memory_id)
        new = f"M{len(memories) + 1}"
        remap[m.handle] = new
        memories.append(MemoryItem(**{**m.__dict__, "handle": new}))
    edges = set(base.edges) | {
        e for e in extra.edges if e[0] in known and e[1] in known
    }
    links = set(base.links) | {(remap[h], qn) for h, qn in extra.links if h in remap}
    return _assemble(base.project, base.task, symbols, memories, edges, links)


def render_packet(packet: EvidencePacket) -> str:
    out = [f"## Evidence packet {packet.packet_id} — {packet.project}", ""]
    out.append(f"**Question:** {packet.task}")
    out.append("")
    if packet.memories:
        out.append("### Recorded memory")
        for m in packet.memories:
            out.append(f"- [{m.handle}] {m.content[:400]}")
        out.append("")
    if packet.symbols:
        out.append("### Symbols")
        for s in packet.symbols:
            kind = f" ({s.label})" if s.label else ""
            out.append(
                f"- [{s.handle}] {s.name}{kind} — "
                f"`{s.file_path}:{s.start_line}-{s.end_line}`"
            )
        out.append("")
        out.append("### Source")
        for s in packet.symbols:
            out.append(f"#### [{s.handle}] {s.qualified_name}")
            fence = _fence_for(s.source)
            out.append(fence)
            out.append(s.source)
            if s.truncated:
                out.append("# ... truncated ...")
            out.append(fence)
        out.append("")
    if packet.edges:
        out.append("### Calls")
        names = {s.qualified_name: s.handle for s in packet.symbols}
        for a, b in sorted(packet.edges):
            out.append(f"- {names[a]} calls {names[b]}")
    return "\n".join(out)
