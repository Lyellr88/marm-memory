"""Personalised PageRank over a seeded symbol subgraph.

Why not just take the search hits in score order: lexical search answers "which
symbols mention these words", which is not the same question as "which symbols
matter for this task". A private helper whose name happens to match the query
outranks the class everything actually calls.

Personalised PageRank fixes that by letting importance flow along call edges from
the symbols the query actually matched -- the approach Aider's repo map uses.
Restart mass stays pinned to the seeds, so the result is "important *relative to
this task*" rather than "globally popular", which is what makes it usable for
context selection.

Stdlib only: the graph here is a two-hop neighbourhood (hundreds of nodes), so a
dense numpy solve would be overkill and a dependency. Sparse power iteration
converges in a few dozen passes.
"""

from __future__ import annotations

from collections import defaultdict


def personalised_pagerank(
    edges: list[tuple[str, str, float]],
    seeds: dict[str, float],
    *,
    damping: float = 0.85,
    iterations: int = 60,
    tolerance: float = 1.0e-8,
) -> dict[str, float]:
    """Rank nodes by importance *as seen from* `seeds`.

    edges: (source, target, weight); weight combines the engine's confidence
    with how the hop was resolved. Confidence alone does not separate them --
    the LSP and heuristic ranges overlap -- so `compose._STRATEGY_TRUST` scales
    it, and an LSP-resolved call outranks a heuristic name match by construction
    rather than by hoping the numbers line up.
    seeds: node -> restart mass (need not be normalised; non-positive entries
    are dropped). An empty or unknown seed set falls back to uniform restart,
    which degrades to ordinary PageRank rather than returning nothing.
    """
    # Seeds only join the node set when the graph actually contains them. A seed
    # that resolved to nothing (a renamed symbol, a typo) would otherwise hold
    # every unit of restart mass and outrank the real code.
    nodes = {n for a, b, _ in edges for n in (a, b)}
    if not nodes:
        nodes = set(seeds)
    if not nodes:
        return {}

    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    out_total: dict[str, float] = defaultdict(float)
    for a, b, w in edges:
        w = max(float(w), 0.0)
        if w == 0.0 or a == b:
            continue
        out[a].append((b, w))
        out_total[a] += w

    restart = {n: v for n, v in seeds.items() if n in nodes and v > 0}
    total = sum(restart.values())
    if total <= 0:
        restart = dict.fromkeys(nodes, 1.0)
        total = float(len(nodes))
    restart = {n: v / total for n, v in restart.items()}

    rank = {n: restart.get(n, 0.0) for n in nodes}
    n_nodes = len(nodes)
    for _ in range(iterations):
        nxt = dict.fromkeys(nodes, 0.0)
        dangling = 0.0
        for n, r in rank.items():
            if out_total.get(n, 0.0) <= 0:
                dangling += r
                continue
            share = damping * r / out_total[n]
            for tgt, w in out[n]:
                nxt[tgt] += share * w
        # Dangling nodes would leak mass out of the system; in a personalised
        # walk it must return to the seeds, not spread uniformly, or the ranking
        # drifts back toward global popularity.
        for n, p in restart.items():
            nxt[n] += damping * dangling * p
        leftover = 1.0 - damping
        for n, p in restart.items():
            nxt[n] += leftover * p
        delta = sum(abs(nxt[n] - rank[n]) for n in nodes)
        rank = nxt
        if delta < tolerance * n_nodes:
            break
    return rank
