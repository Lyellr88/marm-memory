"""One-call composed code context: ranked symbols, their source, and memory."""

import json
from collections.abc import Iterator

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.code_context import build_code_context, stream_answer

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="", tags=["Code Context"])


class CodeContextRequest(BaseModel):
    task: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="What you are trying to do or understand.",
    )
    project: str | None = Field(
        default=None,
        max_length=512,
        description="Code-graph project name or repo path. Omit to resolve from `cwd`.",
    )
    cwd: str | None = Field(
        default=None,
        max_length=4096,
        description="Directory to resolve the project from.",
    )
    budget: int = Field(
        default=12000,
        ge=500,
        le=100000,
        description="Character budget for the returned source.",
    )
    detail: int = Field(
        default=0,
        ge=0,
        le=3,
        description=(
            "How much to return. 1=markdown only (an agent reads this and "
            "stops); 2=adds symbol and memory metadata; 3=adds source and "
            "memory text as structured fields, which the markdown already "
            "contains. 0 uses the server default (MARM_CODE_CONTEXT_DETAIL)."
        ),
    )
    answer: bool = Field(
        default=False,
        description=(
            "Also answer the task from the composed context using a local "
            "model, with citations to the symbols it used. Off by default: it "
            "is the slow step, and the ranked context is already the answer "
            "for a caller that reads code. `answer_status` is 'ok' only when "
            "the answer's citations resolve to composed symbols and none name "
            "anything else; otherwise 'unverified', with `answer_unresolved`. "
            "'unavailable' rather than a failure when generation is off or no "
            "model is reachable."
        ),
    )
    include_graph: bool = Field(
        default=False,
        description=(
            "Also return the ranked call neighbourhood as `graph_edges`. Off by "
            "default: it is several KB of JSON that only a visualiser reads."
        ),
    )


@router.post("/marm_code_context", operation_id="marm_code_context")
async def marm_code_context(req: CodeContextRequest) -> dict:
    """Composed code context for a task, in ONE call.

    Returns the symbols that matter for `task`, their source read from disk, and
    what memory records about them. Prefer this over a bare symbol search when
    the question is "how does X work", "where is X handled", or "what would
    changing X affect".

    Ranking is personalised PageRank over the call graph seeded from the task,
    so results are central *to this task* rather than globally popular or merely
    matching its words. A lexical search answers "which symbols mention these
    words", which is a different question.

    Edge weight combines the engine's confidence with how each hop resolved:
    confidence alone does not separate them, because the LSP and heuristic
    ranges overlap, and a heuristic name match can bind across module
    boundaries. Unresolved hops are dropped rather than carried as weak
    evidence.
    """
    return await build_code_context(
        task=req.task,
        project=req.project,
        cwd=req.cwd,
        budget=req.budget,
        include_graph=req.include_graph,
        detail=req.detail or None,
        answer=req.answer,
    )


@router.post("/internal/code-context/answer", include_in_schema=False)
def stream_code_context_answer(req: CodeContextRequest) -> StreamingResponse:
    """Server-sent events carrying a grounded answer as it is written.

    Deliberately NOT part of the MCP tool surface, and `include_in_schema` is
    off so it cannot be picked up as one. An agent consumes a whole answer
    before acting on any of it, so streaming to an agent adds framing and buys
    nothing; this exists for the Console, where seconds of blank screen read as
    a hung page rather than a slow one. The tool keeps returning a single JSON
    body.

    The first event is `context`, the composition the answer is written from,
    so a client renders the evidence and the answer from one retrieval.

    A sync generator on purpose: Starlette iterates it in a worker thread, the
    llama.cpp client is blocking, and the composition it does first is
    `asyncio.run` over a coroutine -- all of which are correct off the event
    loop and wrong on it.
    """

    def events() -> Iterator[str]:
        try:
            for name, payload in stream_answer(
                task=req.task,
                project=req.project,
                cwd=req.cwd,
                budget=req.budget,
                include_graph=req.include_graph,
                detail=req.detail or None,
            ):
                yield f"event: {name}\ndata: {json.dumps(payload)}\n\n"
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("code-context answer stream failed")
            yield (
                "event: error\n"
                f"data: {json.dumps({'message': f'answer stream failed: {exc}'})}\n\n"
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            # Without these a proxy or the browser will buffer the stream and
            # deliver it all at once, which is the exact failure this endpoint
            # exists to avoid.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
