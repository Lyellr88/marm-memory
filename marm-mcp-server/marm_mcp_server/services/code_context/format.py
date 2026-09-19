"""Render a Context as the markdown an agent actually reads.

Ordering is the product decision here. Decisive material goes first, because
recall degrades in the middle of a long context regardless of window size: the
orientation line, then what memory knows (the part no code index can supply),
then entry points, then source. The closing note tells the caller what NOT to
fetch next -- an unbounded follow-up is how a context tool becomes a token sink.
"""

from __future__ import annotations

from .compose import Context
from .project import short_name

_EXT = {
    ".py": "python",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".kt": "kotlin",
    ".sh": "bash",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
}


def _lang(path: str) -> str:
    for ext, lang in _EXT.items():
        if path.endswith(ext):
            return lang
    return ""


def _fence_for(source: str) -> str:
    """A fence longer than the longest backtick run inside the source.

    Source that contains a triple-backtick line -- a Markdown example, a docstring
    with a fenced block -- would otherwise close the fence early, and the rest of
    the snippet would be rendered as prose in the agent-facing Markdown.
    """
    longest = 0
    run = 0
    for ch in source:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def render(ctx: Context) -> str:
    out: list[str] = []
    name = short_name(ctx.project)
    out.append(f"## Code context — {name}")
    out.append("")
    out.append(f"**Task:** {ctx.task}")
    out.append(
        f"_{ctx.seed_count} seed symbols, {ctx.graph_nodes} nodes in the call "
        f"neighbourhood, {len(ctx.symbols)} shown (ranked by personalised "
        f"PageRank from the seeds)._"
    )
    out.append("")

    if ctx.memories or ctx.links:
        out.append("### What memory knows")
        for m in ctx.memories:
            text = (m.get("content") or m.get("summary") or "").strip()
            text = " ".join(text.split())
            if text:
                out.append(f"- {text[:300]}")
        for ln in ctx.links:
            # The API returns `qualified_name`; `graph_qualified_name` is the
            # concept database's column name. Accept either.
            qn = ln.get("qualified_name") or ln.get("graph_qualified_name") or ""
            entity = ln.get("entity_name") or qn.split(".")[-1]
            out.append(
                f"- memory concept `{entity}` is recorded against "
                f"`{qn.split('.')[-1]}` in `{ln.get('file_path', '')}`"
            )
        out.append("")

    if ctx.symbols:
        out.append("### Entry points")
        for s in ctx.symbols:
            loc = f"{s.file_path}:{s.start_line}" if s.file_path else "?"
            kind = f" ({s.label})" if s.label else ""
            # Say how a call-graph symbol was reached, not just that it was.
            # `strategy` is load-bearing rather than trivia: heuristic binding
            # is what invents cross-module edges, so a reader who cannot see
            # "heuristic" cannot discount a row that deserves discounting.
            mark = ""
            if not s.seeded:
                detail = [f"{s.hop} hop" if s.hop else "via call graph"]
                if s.strategy:
                    detail.append(
                        f"{s.strategy} {s.confidence:.2f}"
                        if s.confidence
                        else s.strategy
                    )
                if s.risk:
                    detail.append(f"risk {s.risk}")
                mark = "  ·" + " ·".join(detail)
            out.append(f"- **{s.name}**{kind} — `{loc}`{mark}")
        out.append("")

        out.append("### Code")
        for s in ctx.symbols:
            out.append(f"#### {s.name} — `{s.file_path}:{s.start_line}`")
            fence = _fence_for(s.source)
            out.append(f"{fence}{_lang(s.file_path)}")
            out.append(s.source)
            if s.truncated:
                out.append("# ... truncated ...")
            out.append(fence)
            out.append("")

    if not ctx.symbols:
        out.append(
            "_No indexed symbols matched. The repository may not be "
            "indexed yet, or the task wording may not match any symbol "
            "names — try naming a function, type or file._"
        )
        out.append("")

    for n in ctx.notes:
        out.append(f"> note: {n}")
    if ctx.notes:
        out.append("")

    out.append("---")
    out.append(
        "> The ranked neighbourhood above is the relevant surface — **do not "
        "follow up with a broad search on the same terms**, it will return these "
        "same symbols. For a specific call path use a trace from one symbol to "
        "another; for one symbol's full body, read the file at the line above."
    )
    return "\n".join(out)
