"""Compose one answer to 'what code matters for this task'.

The pipeline, and why each stage earns its round trip:

  1. seed     lexical + semantic search. Answers "which symbols mention this",
              which is a starting point, not an answer.
  2. expand   trace callers and callees around the top seeds. Code relevance
              travels along call edges; a task about `check` is usually also
              about what `check` calls.
  3. rank     personalised PageRank over that subgraph. Turns "mentions the
              words" into "matters for the task" -- the step plain search
              cannot do, because it has no notion of a symbol being central.
  4. read     pull source off disk for the winners.
  5. recall   join MARM's memories and its memory->symbol links. This is the
              part a pure code index structurally cannot do: it carries why the
              code is the way it is, not just what it says.
  6. budget   cut to a character budget, decisive material first.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .backend import GraphUnavailable, LocalBackend
from .project import resolve, short_name
from .rank import personalised_pagerank
from .snippets import dedent_block, read
from .terms import is_distinctive, looks_like_test, seed_query

SEED_LIMIT = 25
EXPAND_SEEDS = 6
TRACE_DEPTH = 2
REVERSE_WEIGHT = 0.5
DEFAULT_BUDGET = 12000
TEST_PENALTY = 0.15
MEMORY_PROBES = 6
MEMORY_LIMIT = 6


@dataclass
class Symbol:
    qualified_name: str
    name: str
    label: str
    file_path: str
    start_line: int
    end_line: int
    score: float = 0.0
    seeded: bool = False
    source: str = ""
    truncated: bool = False


@dataclass
class Context:
    project: dict
    task: str
    symbols: list[Symbol] = field(default_factory=list)
    memories: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    seed_count: int = 0
    graph_nodes: int = 0


def _sym(row: dict) -> Symbol:
    return Symbol(
        qualified_name=row.get("qualified_name", ""),
        name=row.get("name", ""),
        label=row.get("label", ""),
        file_path=row.get("file_path", ""),
        start_line=int(row.get("start_line") or 0),
        end_line=int(row.get("end_line") or 0),
    )


# How much to trust an edge, by how the engine resolved it. `confidence` alone
# does NOT separate these: measured against the live engine, LSP edges scored
# 0.88-0.97 and heuristic edges 0.75-0.90, so a heuristic name match at 0.90
# outweighed a resolved call at 0.88.
#
# That matters because heuristic binding is what invents cross-module edges. On
# this very repo it bound `dict.items()` to a module-level *variable* named
# `items` in an unrelated file, which was enough to make that file the graph's
# top hotspot. A guess must not outrank a resolution.
_STRATEGY_TRUST = {
    "lsp": 1.0,
    "language_rule": 0.8,
    "heuristic": 0.45,
    "unresolved": 0.0,  # dropped: the engine is reporting that it does not know
}
_UNKNOWN_STRATEGY_TRUST = 0.45  # absent evidence is not evidence of resolution


def _edges_from_trace(payload: dict, origin: str) -> list[tuple[str, str, float]]:
    """Turn one trace response into weighted edges.

    Both directions are emitted. Importance has to be able to flow back from a
    callee to its callers, or a widely-used helper never outranks the private
    function that happens to match the query text. The reverse edge is
    deliberately lighter than the forward one.

    Weight is confidence scaled by how the hop was resolved, then divided by
    hop distance. See `_STRATEGY_TRUST` for why the scaling is necessary.
    """
    out: list[tuple[str, str, float]] = []
    for key, forward in (("callees", True), ("callers", False)):
        for row in payload.get(key) or []:
            qn = row.get("qualified_name")
            if not qn or qn == origin:
                continue
            strategy = (row.get("strategy") or "").strip().lower()
            trust = _STRATEGY_TRUST.get(strategy, _UNKNOWN_STRATEGY_TRUST)
            if trust <= 0.0:
                continue
            w = float(row.get("confidence") or 0.5) * trust
            hop = max(int(row.get("hop") or 1), 1)
            w /= hop  # a two-hop relation is weaker evidence than a one-hop one
            a, b = (origin, qn) if forward else (qn, origin)
            out.append((a, b, w))
            out.append((b, a, w * REVERSE_WEIGHT))
    return out


def _apply_test_penalty(symbols: list) -> None:
    """Discount tests in the FINAL ranking, not only in the seed mass.

    Penalising restart mass reduces how much a test radiates into the graph. It
    does nothing about how much a test receives from it, and the output is
    ordered by the resulting score, so a well-connected test still displaced the
    code it exercises. Observed live: "how does the ranking pipeline decide
    which symbols matter" returned two tests above `personalised_pagerank`.

    Discounted rather than dropped. A test docstring is frequently the clearest
    statement of what a function guarantees, and for a task phrased as "why does
    X behave this way" it is often the right answer -- it just should not come
    before the implementation.
    """
    for s in symbols:
        if looks_like_test(s.file_path, s.name):
            s.score *= TEST_PENALTY


def _relevant_memories(
    rows: list[dict], symbols: list[Symbol], project: dict
) -> list[dict]:
    """Keep only memories that demonstrably concern THIS project.

    One MARM server backs every agent on the machine, and a memory written over
    MCP cannot carry a project (`marm_log_entry` takes no project argument), so
    the whole store is one pool and a semantic search will happily return a
    memory about an unrelated repository. Unfiltered, the section reads as
    confident and is about the wrong codebase -- worse than showing nothing.

    The gate is deliberately lexical rather than another embedding pass: a
    memory earns its place by naming something concrete from this result -- a
    symbol on screen, a file in it, or the project itself.

    Anchors are not equal, and treating them as equal leaked. `resolve` is a
    function here and clears `is_distinctive`, so a memory from an unrelated
    repository reading "...licenses to resolve the 4 incompatible license
    failures" was admitted on that one word used as an ordinary verb. `search`,
    `rank` and `compose` are the same shape of trap.

    Two things make an anchor strong enough to admit a memory alone:

    - Shape. `personalised_pagerank`, `rank.py`, `marm-stack` -- anything
      carrying `_ . -`, a digit, or camelCase -- cannot occur in ordinary prose.
    - Provenance. A SEEDED symbol is one whose name actually matched the task,
      so a memory naming it is answering the question that was asked. `helper`
      is a plain word, but when the task was `helper`, a memory about `helper`
      is on topic.

    Everything else is weak: a bare dictionary word attached to a symbol that
    merely got pulled in by call-graph expansion. That is exactly what leaked --
    `resolve` was never seeded, it arrived through the graph, and the memory
    used the word as a verb. A weak anchor needs a second, different weak anchor
    before it counts. Weak evidence is not no evidence; it is just not enough
    on its own.
    """
    import os
    import re

    def strength(original: str) -> bool:
        """True when this token could not plausibly be ordinary English."""
        return bool(
            re.search(r"[_.\-0-9]", original) or re.search(r"[a-z][A-Z]", original)
        )

    anchors: dict[str, bool] = {}
    for sym in symbols:
        if is_distinctive(sym.name):
            key = sym.name.lower()
            # `or sym.seeded`: a symbol that matched the task earns a plain word.
            anchors[key] = anchors.get(key, False) or strength(sym.name) or sym.seeded
        if sym.file_path:
            base = os.path.basename(sym.file_path)
            anchors[base.lower()] = anchors.get(base.lower(), False) or strength(base)
    root = (project.get("root_path") or "").rstrip("/")
    if root:
        base = os.path.basename(root)
        anchors[base.lower()] = strength(base)
    anchors.pop("", None)
    if not anchors:
        return []

    kept = []
    for row in rows:
        text = (row.get("content") or row.get("summary") or "").lower()
        if not text:
            continue
        strong = weak = 0
        for anchor, is_strong in anchors.items():
            if re.search(rf"\b{re.escape(anchor)}\b", text):
                if is_strong:
                    strong += 1
                else:
                    weak += 1
        if strong >= 1 or weak >= 2:
            kept.append(row)
    return kept[:5]


async def build(
    client: "LocalBackend",
    task: str,
    *,
    cwd: str | None = None,
    project: str | None = None,
    budget: int = DEFAULT_BUDGET,
) -> Context:
    projects = await asyncio.to_thread(client.projects)
    chosen = resolve(projects, cwd=cwd, explicit=project)
    if chosen is None:
        known = ", ".join(short_name(p) for p in projects) or "none"
        raise GraphUnavailable(
            f"no indexed project for {project or cwd or 'this directory'}. "
            f"Indexed: {known}. Index one with marm_graph_index(repo_path=...)."
        )

    name, root = chosen["name"], chosen.get("root_path", "")
    ctx = Context(project=chosen, task=task)

    # Seeding on the raw sentence lets BM25 score snake_case test names that
    # are mostly English filler; the semantic side still gets the full task.
    seeds_rows = await asyncio.to_thread(
        client.search, name, seed_query(task), limit=SEED_LIMIT, semantic=task
    )
    ctx.seed_count = len(seeds_rows)
    by_qn: dict[str, Symbol] = {}
    seed_mass: dict[str, float] = {}
    for i, row in enumerate(seeds_rows):
        s = _sym(row)
        if not s.qualified_name:
            continue
        s.seeded = True
        by_qn.setdefault(s.qualified_name, s)
        # Rank order is the only reliable signal here: the engine's `rank` field
        # is a raw BM25 score on one path and a distance on another, so its
        # scale is not comparable across search modes.
        mass = 1.0 / (i + 1)
        if looks_like_test(s.file_path, s.name):
            # Tests are real code but rarely the answer to "how does X work",
            # and their long descriptive names make them lexical magnets.
            mass *= TEST_PENALTY
        seed_mass[s.qualified_name] = mass

    edges: list[tuple[str, str, float]] = []
    for s in list(by_qn.values())[:EXPAND_SEEDS]:
        # Trace by QUALIFIED name. A bare name that matches more than one symbol
        # -- routine in any real codebase, e.g. two `cpu_clock` methods on
        # different structs -- comes back as status "ambiguous" with no edges,
        # which silently collapses the whole call-graph stage to nothing.
        try:
            payload = await asyncio.to_thread(
                client.trace, name, s.qualified_name, depth=TRACE_DEPTH
            )
            if payload.get("status") in ("ambiguous", "not_found"):
                payload = await asyncio.to_thread(
                    client.trace, name, s.name, depth=TRACE_DEPTH
                )
            if payload.get("status") in ("ambiguous", "not_found"):
                continue
        except GraphUnavailable:
            continue
        edges += _edges_from_trace(payload, s.qualified_name)
        for key in ("callees", "callers"):
            for row in payload.get(key) or []:
                qn = row.get("qualified_name")
                if qn and qn not in by_qn and qn.startswith(name + "."):
                    by_qn[qn] = Symbol(
                        qualified_name=qn,
                        name=row.get("name", ""),
                        label=row.get("risk", ""),
                        file_path="",
                        start_line=0,
                        end_line=0,
                    )

    ranks = personalised_pagerank(edges, seed_mass) if edges else dict(seed_mass)
    ctx.graph_nodes = len({n for a, b, _ in edges for n in (a, b)})
    for qn, s in by_qn.items():
        # A seeded symbol keeps a floor: it demonstrably matched the task text,
        # and a symbol absent from the call graph would otherwise score zero and
        # vanish even when it is the obvious answer.
        s.score = max(ranks.get(qn, 0.0), seed_mass.get(qn, 0.0) * 0.1)

    _apply_test_penalty(list(by_qn.values()))
    ordered = sorted(by_qn.values(), key=lambda s: -s.score)

    # Resolve file/line for ranked symbols that arrived via trace without them.
    for s in ordered[:12]:
        if s.file_path or not s.name:
            continue
        for row in await asyncio.to_thread(client.search, name, s.name, limit=3):
            if row.get("qualified_name") == s.qualified_name:
                found = _sym(row)
                s.file_path, s.start_line, s.end_line = (
                    found.file_path,
                    found.start_line,
                    found.end_line,
                )
                s.label = s.label or found.label
                break

    spent = 0
    for s in ordered:
        if not s.file_path or spent >= budget:
            continue
        text, truncated = read(root, s.file_path, s.start_line, s.end_line)
        if not text:
            continue
        s.source, s.truncated = dedent_block(text), truncated
        spent += len(s.source)
        ctx.symbols.append(s)
        if spent >= budget:
            ctx.notes.append("output truncated at the character budget")
            break

    binding = None
    try:
        binding = await asyncio.to_thread(client.binding, name)
    except GraphUnavailable:
        pass
    memory_project = (binding or {}).get("memory_project")

    # Query memory with the SYMBOLS the code stage found, not only the task
    # sentence. Memories are written as short headlines that name things --
    # "Enhanced Styling Initialization Flow Analysis" -- so a symbol name is a
    # far better probe than a prose question. Measured on this store: the task
    # "how does the content script inject CSS" returned nothing, while the
    # symbols it surfaced returned the relevant memories.
    probes: list[str] = []
    for s in ctx.symbols[:MEMORY_PROBES]:
        if is_distinctive(s.name):
            probes.append(s.name)
    task_terms = seed_query(task)
    if task_terms:
        probes.append(task_terms)

    seen_ids: set[str] = set()
    collected: list[dict] = []
    for probe in probes:
        try:
            rows = await client.recall(probe, limit=4, project=memory_project)
        except GraphUnavailable:
            ctx.notes.append("memory recall unavailable")
            break
        for row in rows:
            key = str(row.get("id") or row.get("content", ""))[:200]
            if key and key not in seen_ids:
                seen_ids.add(key)
                collected.append(row)
    # Project scoping is the real filter now that memories carry a project and
    # the project is bound to this graph. The lexical gate stays only as a
    # backstop for an unbound project, where recall still spans the whole store.
    ctx.memories = (
        collected[:MEMORY_LIMIT]
        if memory_project
        else _relevant_memories(collected, ctx.symbols, chosen)
    )

    try:
        wanted = {s.qualified_name for s in ctx.symbols}
        # The API returns `qualified_name`; `graph_qualified_name` is the column
        # name in the concept database. Reading only the latter silently matched
        # nothing, so this section was always empty.
        ctx.links = [
            ln
            for ln in await asyncio.to_thread(client.memory_links, name)
            if (ln.get("qualified_name") or ln.get("graph_qualified_name")) in wanted
        ]
    except GraphUnavailable:
        pass
    return ctx
