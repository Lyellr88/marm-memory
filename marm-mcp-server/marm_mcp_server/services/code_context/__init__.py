"""Composed code context: ranked symbols, their source, and what memory knows.

The pipeline is: seed on content terms, expand callers and callees, rank by
personalised PageRank over that subgraph, read source from disk, join memory,
then cut to a character budget.

Step three is the point. Lexical search answers "which symbols mention these
words", which is not "which symbols matter here" -- a private helper whose name
happens to match will outrank the class everything calls.
"""

from ...config.env_parsing import _safe_int
from .backend import GraphUnavailable, LocalBackend
from .compose import Context, Symbol, build
from .format import render
from .project import short_name

#: Server-wide floor for how much `marm_code_context` returns, so an operator
#: can quiet every agent at once instead of each caller passing `detail`.
#: 1 is right for an agent: `markdown` already contains the source and the
#: memory text, so returning the structured arrays as well means paying for the
#: same bytes twice. The Console asks for 3 because it lays out the parts.
# Guarded: a typo in an operator-facing variable must not stop the server
# starting. _safe_int warns and falls back, which is the convention the rest
# of the settings layer already uses.
DEFAULT_DETAIL = max(1, min(3, _safe_int("MARM_CODE_CONTEXT_DETAIL", 1)))

__all__ = [
    "DEFAULT_DETAIL",
    "GraphUnavailable",
    "LocalBackend",
    "build",
    "build_code_context",
    "render",
    "serialise",
]


async def build_code_context(
    *,
    task: str,
    project: str | None = None,
    cwd: str | None = None,
    budget: int = 12000,
    include_graph: bool = False,
    detail: int | None = None,
) -> dict:
    """Run the pipeline and return both the rendered text and its structure.

    `markdown` is what an agent reads. The structured fields are what the
    Console renders, so neither has to re-derive the other.
    """
    backend = LocalBackend()
    try:
        ctx = await build(backend, task, cwd=cwd, project=project, budget=budget)
    except GraphUnavailable as exc:
        # Two different failures share this exception: the graph is not running,
        # and the graph is running but nothing matches. They need different
        # advice, and the message already carries the indexed list in the second
        # case, so the caller is told what to do rather than just what failed.
        message = str(exc)
        unmatched = "no indexed project" in message
        return {
            "status": "no_project" if unmatched else "unavailable",
            "message": message,
            "hint": (
                "Call marm_graph_index(action='list') to see indexed projects."
                if unmatched
                else "Index a repository with marm_graph_index(repo_path=...) first."
            ),
        }
    return serialise(ctx, task, include_graph=include_graph, detail=detail)


def serialise(
    ctx: "Context",
    task: str,
    *,
    include_graph: bool = False,
    detail: int | None = None,
) -> dict:
    """Build the public response from a composed Context.

    Split out from build_code_context because this function -- not that one --
    defines the shape every agent receives over both transports, and it is the
    only part that can be asserted without a live graph backend.

    `detail` controls how much of the SAME content is repeated: `markdown`
    already carries the source, so `symbols[].source` at detail 3 is that text
    a second time. An agent reads `markdown` and stops.

      1  markdown and notes. What an agent needs, and nothing twice.
      2  adds symbol and memory metadata -- names, files, lines, scores,
         provenance -- but not the source or memory bodies already in the
         markdown. For deciding where to look without re-reading.
      3  everything, including source and memory text as structured fields.
         What a renderer needs; the Console asks for this.

    `include_graph` stays a separate switch: it is a different axis (a
    visualisation payload nothing else reads), not more of the same content.
    """
    level = DEFAULT_DETAIL if detail is None else max(1, min(3, detail))

    def _symbol(s: "Symbol") -> dict:
        row = {
            "name": s.name,
            "qualified_name": s.qualified_name,
            "label": s.label,
            "file_path": s.file_path,
            "start_line": s.start_line,
            "end_line": s.end_line,
            "score": round(s.score, 6),
            "seeded": s.seeded,
            "truncated": s.truncated,
            # Nested, and None for a purely seeded symbol: these four are
            # jointly present or jointly absent, so four flat zero-valued keys
            # would claim a hop-0 heuristic edge that never existed.
            "provenance": (
                {
                    "hop": s.hop,
                    "strategy": s.strategy,
                    "confidence": round(s.confidence, 4),
                    "risk": s.risk,
                }
                if (s.hop or s.strategy or s.confidence or s.risk)
                else None
            ),
        }
        if level >= 3:
            row["source"] = s.source
        return row

    payload = {
        "status": "success",
        # A fixed three-key shape rather than the engine's row: the engine names
        # a project after its absolute path, so callers that want a label need
        # short_name, and callers that want to re-query need name.
        "project": {
            "name": ctx.project.get("name", ""),
            "short_name": short_name(ctx.project),
            "root_path": ctx.project.get("root_path", ""),
        },
        "task": task,
        "markdown": render(ctx),
        "detail": level,
        "graph_nodes": ctx.graph_nodes,
        "notes": ctx.notes,
    }

    # Counts survive every level. Knowing twenty-one symbols were ranked is the
    # difference between "nothing matched" and "here is a summary of a lot",
    # and it costs two integers.
    payload["symbol_count"] = len(ctx.symbols)
    payload["memory_count"] = len(ctx.memories) + len(ctx.links)

    if level >= 2:
        payload["symbols"] = [_symbol(s) for s in ctx.symbols]
        payload["memories"] = (
            ctx.memories
            if level >= 3
            else [{k: v for k, v in m.items() if k != "content"} for m in ctx.memories]
        )
        payload["links"] = ctx.links

    if include_graph:
        # Opt-in, and a different axis from `detail`: a visualisation payload
        # nothing else reads, not more of the same content.
        payload["graph_edges"] = [[a, b, round(w, 4)] for a, b, w in ctx.graph_edges]

    return payload
