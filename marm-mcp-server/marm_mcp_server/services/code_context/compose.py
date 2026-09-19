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
    # How this symbol arrived, when it arrived through the call graph. `label`
    # is the code KIND and must never carry any of this: a trace row's `risk`
    # was previously stored there, so a symbol displayed "CRITICAL" where a
    # reader expects "Function", in the Console and in the agent markdown alike.
    risk: str = ""
    hop: int = 0
    strategy: str = ""
    confidence: float = 0.0


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
    # The ranked call neighbourhood, aggregated to one record per ordered pair.
    # `edges` as PageRank consumes it is a raw duplicated list whose repetition
    # IS the weighting, so this is a separate view rather than the same object.
    graph_edges: list[tuple[str, str, float]] = field(default_factory=list)


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

    # Seeding on the raw sentence lets BM25 score snake_case test names that are
    # mostly English filler. Seeding is lexical: the engine's lookup has no
    # semantic field, and claiming otherwise is what the review caught.
    seeds_rows = await asyncio.to_thread(
        client.search, name, seed_query(task), limit=SEED_LIMIT
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
    traces_unavailable = 0
    # Snapshot BEFORE the loop: a successful trace adds graph-derived symbols to
    # `by_qn`, so measuring it afterwards would report a denominator including
    # symbols that were never candidates for expansion.
    trace_candidates = list(by_qn.values())[:EXPAND_SEEDS]
    for s in trace_candidates:
        # Trace by QUALIFIED name. A bare name that matches more than one symbol
        # -- routine in any real codebase, e.g. two `cpu_clock` methods on
        # different structs -- comes back as status "ambiguous" with no edges,
        # which silently collapses the whole call-graph stage to nothing.
        try:
            payload = await asyncio.to_thread(
                client.trace, name, s.qualified_name, depth=TRACE_DEPTH
            )
            # No bare-name retry. A qualified trace that misses means this
            # symbol's neighbourhood is unknown; retrying with the bare tail can
            # resolve to a DIFFERENT symbol that happens to own that name
            # elsewhere in the project and splice its call graph into the
            # ranking. Skipping loses edges; guessing invents them.
            if payload.get("status") in ("ambiguous", "not_found"):
                continue
            if payload.get("status") == "error":
                # The router reports a failed trace as a STATUS, not an
                # exception, and an errored payload carries no edges -- which is
                # indistinguishable from "this symbol calls nothing". Untreated,
                # a graph outage produced a source-only composition that looked
                # complete. It is unavailability, so it takes that path.
                raise GraphUnavailable(payload.get("message") or "trace failed")
        except GraphUnavailable:
            # One symbol's neighbourhood is missing, not the whole composition,
            # so the remaining seeds still rank -- but the result has to SAY the
            # call graph is partial rather than present a shorter one as whole.
            traces_unavailable += 1
            continue
        edges += _edges_from_trace(payload, s.qualified_name)
        for key in ("callees", "callers"):
            for row in payload.get(key) or []:
                qn = row.get("qualified_name")
                if qn and qn not in by_qn and qn.startswith(name + "."):
                    by_qn[qn] = Symbol(
                        qualified_name=qn,
                        name=row.get("name", ""),
                        # Deliberately empty: the kind comes from the search
                        # backfill below, which can only fill a blank label.
                        label="",
                        file_path="",
                        start_line=0,
                        end_line=0,
                        risk=str(row.get("risk") or ""),
                        hop=int(row.get("hop") or 0),
                        strategy=str(row.get("strategy") or ""),
                        confidence=float(row.get("confidence") or 0.0),
                    )

    if traces_unavailable:
        # The composition still ranks on the seeds it has, but it must not
        # present a partial call graph as a whole one.
        ctx.notes.append(
            f"call graph unavailable for {traces_unavailable} of "
            f"{len(trace_candidates)} expanded symbols"
        )

    ranks = personalised_pagerank(edges, seed_mass) if edges else dict(seed_mass)
    ctx.graph_nodes = len({n for a, b, _ in edges for n in (a, b)})
    aggregated: dict[tuple[str, str], float] = {}
    for a, b, w in edges:
        pair = (a, b)
        aggregated[pair] = max(aggregated.get(pair, 0.0), w)
    ctx.graph_edges = [(a, b, w) for (a, b), w in aggregated.items()]
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
        try:
            rows = await asyncio.to_thread(client.search, name, s.name, limit=3)
        except GraphUnavailable:
            # Every other graph call here degrades rather than failing: the
            # trace loop counts it, binding/recall/memory_links swallow it.
            # This is cosmetic backfill -- a file and line for a symbol the
            # ranking already has -- so an engine that dies after seeding must
            # not turn a usable composition into a failed request.
            break
        for row in rows:
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
        block = dedent_block(text)
        # budget is a CHARACTER budget, and read() limits lines, not characters.
        # Appending a whole 60-line snippet and only then checking `spent` lets a
        # single large symbol overshoot by thousands of characters, so the clamp
        # has to happen before the append rather than between symbols.
        room = budget - spent
        if len(block) > room:
            block = block[:room]
            truncated = True
        s.source, s.truncated = block, truncated
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
    # sentence. Memories are headlines that name things, so a symbol name is a
    # far better probe than a prose question.
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
    # Best six, not first six. `collected` is built probe by probe, so without
    # this a 0.95 memory found by the fourth probe loses its place to a 0.72 one
    # found by the first -- and the caller sees a ranked-looking list that is
    # actually in discovery order.
    collected.sort(key=lambda r: -float(r.get("similarity") or 0.0))
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
