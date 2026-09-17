"""One-call composed code context: ranked symbols, their source, and memory."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services.code_context import build_code_context

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
    )
