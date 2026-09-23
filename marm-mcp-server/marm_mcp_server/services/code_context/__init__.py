"""Composed code context: ranked symbols, their source, and what memory knows.

The pipeline is: seed on content terms, expand callers and callees, rank by
personalised PageRank over that subgraph, read source from disk, join memory,
then cut to a character budget.

Step three is the point. Lexical search answers "which symbols mention these
words", which is not "which symbols matter here" -- a private helper whose name
happens to match will outrank the class everything calls.
"""

import asyncio
import re
from collections.abc import Iterator

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
    "stream_answer",
]


async def build_code_context(
    *,
    task: str,
    project: str | None = None,
    cwd: str | None = None,
    budget: int = 12000,
    include_graph: bool = False,
    detail: int | None = None,
    answer: bool = False,
) -> dict:
    """Run the pipeline and return both the rendered text and its structure.

    `markdown` is what an agent reads. The structured fields are what the
    Console renders, so neither has to re-derive the other.
    """
    backend = LocalBackend()
    try:
        ctx = await build(backend, task, cwd=cwd, project=project, budget=budget)
    except GraphUnavailable as exc:
        return _unavailable_payload(exc)
    payload = serialise(ctx, task, include_graph=include_graph, detail=detail)
    if answer:
        payload.update(await answer_from_context(ctx, task))
    return payload


def _unavailable_payload(exc: GraphUnavailable) -> dict:
    """The response when nothing could be composed.

    Two different failures share this exception: the graph is not running, and
    the graph is running but nothing matches. They need different advice, and
    the message already carries the indexed list in the second case, so the
    caller is told what to do rather than just what failed.
    """
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


# ---------------------------------------------------------------------------
# Grounded answering.
#
# The retrieval half of RAG has been here since `marm_code_context` shipped:
# seed on the task, expand through the call graph, rank by personalised
# PageRank, read the source, join memory. What was missing was the generation
# half, and the reason was that MARM has no model. When a local one is
# reachable, this closes the loop -- and it answers ONLY from the composed
# context, so the ranking is what decides what the answer can be about.

_ANSWER_SYSTEM = """\
You answer questions about a specific codebase, using ONLY the context below.

RULES
1. Use only the provided symbols, their source, and the recorded memories. If \
the context does not contain the answer, say exactly what is missing and stop. \
Never fill a gap from general knowledge of similar projects -- a plausible \
answer about code that is not this code is the worst outcome here.
2. Cite the symbols you used in square brackets inline, spelled exactly as \
the context spells them: [build_code_context]. Cite only names that appear in \
the context above.
3. Be concrete: name files, functions, and line numbers where the context \
gives them.
4. Be brief. Lead with the answer, then the evidence for it.
5. If recorded memory and the source disagree, say so -- that disagreement is \
usually the most useful thing you can report.\
"""

#: Generation is the slow step and the context is already budgeted, so the
#: answer gets its own modest ceiling rather than the model's full window.
_ANSWER_TOKENS = _safe_int("MARM_CODE_CONTEXT_ANSWER_TOKENS", 900)


async def answer_from_context(ctx: "Context", task: str) -> dict:
    """Answer `task` from the composed context, or explain why it could not.

    Returns keys to merge into the response. The absence of a model is a
    reported state rather than an error: every other part of the composition
    is still valid and useful without it, and failing the whole call because an
    optional container is down would be a poor trade.
    """
    from ...services import local_llm

    model = await asyncio.to_thread(local_llm.available)
    if model is None:
        return {
            "answer": None,
            "answer_status": "unavailable",
            "answer_hint": (
                "No local model is reachable, so the ranked context above is "
                "the whole answer. Set MARM_LLM_URL to an OpenAI-compatible "
                "server on loopback to enable grounded answering."
            ),
        }

    grounding = render(ctx)
    text = await asyncio.to_thread(
        local_llm.complete,
        _ANSWER_SYSTEM,
        f"{grounding}\n\n---\n\nQuestion: {task}\n\nAnswer, citing symbols:",
        max_tokens=_ANSWER_TOKENS,
    )
    if not text:
        return {
            "answer": None,
            "answer_status": "failed",
            "answer_hint": (
                "The local model did not return an answer in time. The ranked "
                "context above is unaffected."
            ),
        }

    citations, unresolved = _check_citations(text, ctx)
    status, hint = _grounding(citations, unresolved)
    out = {
        "answer": text,
        "answer_status": status,
        "answer_model": model,
        "answer_citations": citations,
        "answer_unresolved": unresolved,
    }
    if hint:
        out["answer_hint"] = hint
    return out


# `[name]`, `[`name`]` or `[a, b]`, but not the text of a markdown link.
_CITATION = re.compile(r"\[([^\[\]\n]{1,200})\](?!\()")
_CITATION_SEPARATOR = re.compile(r"[,;]")
_IDENTIFIER = re.compile(r"[A-Za-z_][\w.:]*")
# What separates a cited identifier from a bracketed word: an underscore, a
# qualifying separator, or an inner capital. `[optional]` and `[1]` are prose.
_IDENTIFIER_MARK = re.compile(r"[_.:]|[a-z][A-Z]")


def _check_citations(text: str, ctx: "Context") -> tuple[list[dict], list[str]]:
    """Map the names a model cited onto real symbols, and report the rest.

    Resolution is against the BARE name, because that is what the model can
    see: `format.render` writes `**name** (Kind)` and never the qualified name.

    An identifier-shaped citation that resolves to nothing is returned in the
    second list, never as a citation: the Console renders citations as links
    to source, and an invented one would be a dead link presented as evidence.
    """
    by_name: dict[str, Symbol] = {}
    for symbol in ctx.symbols:
        for key in (symbol.name, symbol.qualified_name):
            if key:
                by_name.setdefault(key.casefold(), symbol)

    seen: set[str] = set()
    out: list[dict] = []
    unresolved: list[str] = []
    for match in _CITATION.finditer(text):
        # Each name in `[a, b]` is its own citation, so an invented one cannot
        # ride along beside a real one.
        for part in _CITATION_SEPARATOR.split(match.group(1)):
            part = part.strip()
            backticked = part.startswith("`")
            name = part.strip("`").split("(")[0].strip()
            if not name:
                continue
            resolved = by_name.get(name.casefold())
            if resolved is None:
                if (
                    _IDENTIFIER.fullmatch(name)
                    and (backticked or _IDENTIFIER_MARK.search(name))
                    and name not in unresolved
                ):
                    unresolved.append(name)
                continue
            if resolved.qualified_name in seen:
                continue
            seen.add(resolved.qualified_name)
            out.append(
                {
                    "name": resolved.name,
                    "qualified_name": resolved.qualified_name,
                    "file_path": resolved.file_path,
                    "start_line": resolved.start_line,
                }
            )
    return out, unresolved


def _grounding(citations: list[dict], unresolved: list[str]) -> tuple[str, str | None]:
    """`ok` only when the answer cites the context and cites nothing else.

    The same verdict on both paths, so the Console cannot call one answer
    grounded that an agent would be told is not.
    """
    if unresolved:
        return "unverified", (
            "The answer cites "
            + ", ".join(unresolved[:5])
            + ", which the composed context does not contain, so it is not "
            "grounded in the evidence shown."
        )
    if not citations:
        return "unverified", (
            "No citation in the answer resolves to a symbol in the composed "
            "context, so it is not grounded in the evidence shown."
        )
    return "ok", None


def stream_answer(
    task: str,
    project: str | None,
    cwd: str | None,
    budget: int,
    *,
    include_graph: bool = False,
    detail: int | None = None,
) -> Iterator[tuple[str, dict]]:
    """Compose ONCE, send that composition, then answer from it as it is written.

    The first event is `context`: the same payload `build_code_context` would
    return, for the caller to render. The answer that follows is written from
    that very composition, so what is displayed and what the answer is grounded
    in cannot be two different retrievals.

    Split from `answer_from_context` rather than sharing it, because the two
    have genuinely different shapes: that one returns a finished dict, this one
    is a generator whose caller is a response body. What they DO share -- the
    system prompt, the token ceiling, the grounding text and the citation
    check -- is imported, not duplicated.

    Yields `(event, payload)` tuples. The citation pass runs on the assembled
    text at the end, because a citation cannot be resolved from a fragment: the
    marker may still be arriving one character at a time.
    """
    from ...services import local_llm

    backend = LocalBackend()
    try:
        ctx = asyncio.run(build(backend, task, cwd=cwd, project=project, budget=budget))
    except GraphUnavailable as exc:
        yield ("context", _unavailable_payload(exc))
        return
    yield ("context", serialise(ctx, task, include_graph=include_graph, detail=detail))

    if local_llm.available() is None:
        yield (
            "error",
            {
                "message": "No local model is reachable.",
                "hint": (
                    "Set MARM_LLM_URL to an OpenAI-compatible server on loopback "
                    "to enable grounded answering. The ranked context is "
                    "unaffected."
                ),
            },
        )
        return

    # The reader gets the shape of the answer before its first word: which
    # project, how many symbols it is grounded in, which model is writing.
    yield (
        "start",
        {
            "project": short_name(ctx.project),
            "symbol_count": len(ctx.symbols),
            "model": local_llm.available(),
        },
    )

    pieces: list[str] = []
    for piece in local_llm.stream(
        _ANSWER_SYSTEM,
        f"{render(ctx)}\n\n---\n\nQuestion: {task}\n\nAnswer, citing symbols:",
        max_tokens=_ANSWER_TOKENS,
    ):
        pieces.append(piece)
        yield ("delta", {"text": piece})

    answer = "".join(pieces)
    if not answer.strip():
        # A reasoning model can spend its whole budget in `reasoning` and emit no
        # content at all. Reporting that as a successful `done` with length 0
        # hands the reader a confident blank, and disagrees with the
        # non-streaming path, which already treats empty content as no answer.
        yield (
            "error",
            {
                "message": (
                    "the model produced no answer text. A reasoning model may "
                    "have spent its budget before writing; raise "
                    "MARM_CODE_CONTEXT_ANSWER_TOKENS. The ranked context is "
                    "unaffected."
                )
            },
        )
        return
    citations, unresolved = _check_citations(answer, ctx)
    status, hint = _grounding(citations, unresolved)
    done: dict = {
        "citations": citations,
        "unresolved": unresolved,
        "status": status,
        "length": len(answer),
    }
    if hint:
        done["hint"] = hint
    yield ("done", done)
