"""Composed code context: ranked symbols, their source, and what memory knows.

The pipeline is: seed on content terms, expand callers and callees, rank by
personalised PageRank over that subgraph, read source from disk, join memory,
then cut to a character budget.

Step three is the point. Lexical search answers "which symbols mention these
words", which is not "which symbols matter here" -- a private helper whose name
happens to match will outrank the class everything calls.
"""

from .backend import GraphUnavailable, LocalBackend
from .compose import Context, build
from .format import render
from .project import short_name

__all__ = [
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
    return serialise(ctx, task, include_graph=include_graph)


def serialise(ctx: "Context", task: str, *, include_graph: bool = False) -> dict:
    """Build the public response from a composed Context.

    Split out from build_code_context because this function -- not that one --
    defines the shape every agent receives over both transports, and it is the
    only part that can be asserted without a live graph backend.
    """
    return {
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
        "symbols": [
            {
                "name": s.name,
                "qualified_name": s.qualified_name,
                "label": s.label,
                "file_path": s.file_path,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "score": round(s.score, 6),
                "seeded": s.seeded,
                "truncated": s.truncated,
                "source": s.source,
                # Nested, and None for a purely seeded symbol: these four are
                # jointly present or jointly absent, so four flat zero-valued
                # keys would claim a hop-0 heuristic edge that never existed.
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
            for s in ctx.symbols
        ],
        "memories": ctx.memories,
        "links": ctx.links,
        "graph_nodes": ctx.graph_nodes,
        # Opt-in: at ~37 nodes the edge list is 8-25 KB of JSON, and an agent
        # reads `markdown` and stops. Charging every caller for a view only the
        # Console renders would be paying tokens for nothing.
        **(
            {"graph_edges": [[a, b, round(w, 4)] for a, b, w in ctx.graph_edges]}
            if include_graph
            else {}
        ),
        "notes": ctx.notes,
    }
