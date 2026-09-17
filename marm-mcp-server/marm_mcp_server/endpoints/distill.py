"""Propose durable memories from raw conversation, and review the proposals."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..core.distill import DEFAULT_LIMIT, DEFAULT_THRESHOLD
from ..core.memory import memory
from ..services import distill as distill_service

router = APIRouter(prefix="", tags=["Distill"])


class DistillRequest(BaseModel):
    action: str = Field(
        default="propose",
        pattern="^(propose|review|apply|discard)$",
        description=(
            "propose: read `text` and stage what looks durable. review: list "
            "proposals awaiting a decision. apply: write one into memory. "
            "discard: reject one, permanently."
        ),
    )
    text: str | None = Field(
        default=None,
        max_length=400000,
        description="Raw conversation to distil. Required for `propose`.",
    )
    session_name: str | None = Field(
        default=None,
        max_length=256,
        description="Session the proposals belong to. Required for `propose`.",
    )
    proposal_id: str | None = Field(
        default=None,
        max_length=64,
        description="Which proposal to act on. Required for `apply`/`discard`.",
    )
    project: str | None = Field(
        default=None, max_length=256, description="Scope name to record on a write."
    )
    context_type: str = Field(
        default="general", max_length=64, description="Memory context type."
    )
    threshold: float = Field(
        default=DEFAULT_THRESHOLD,
        ge=-2.0,
        le=3.0,
        description=(
            "Shape-score floor. Excludes chatter; it is NOT the volume control "
            "-- see `limit`, which is."
        ),
    )
    limit: int = Field(
        default=DEFAULT_LIMIT,
        ge=1,
        le=200,
        description=(
            "Most proposals to return. This is the real control: on real "
            "transcripts the threshold barely changes the count."
        ),
    )
    include_duplicates: bool = Field(
        default=False,
        description="Also stage candidates the store already holds.",
    )
    use_llm: bool = Field(
        default=True,
        description=(
            "Use the local generative model when one is reachable. It writes "
            "self-contained facts, which sentence selection cannot. Set false "
            "to force the selection path. Falls back automatically when no "
            "model is available."
        ),
    )


@router.post("/marm_distill", operation_id="marm_distill")
async def marm_distill(req: DistillRequest) -> dict:
    """Turn raw conversation into reviewed memory proposals.

    Pass a transcript as `text` and this returns the sentences in it that read
    like durable facts, each resolved against what is already stored:
    `new` (nothing close), `duplicate` (already recorded), or `near` (close to
    something stored, and worth a human look).

    It SELECTS sentences rather than writing new ones, because MARM has no
    generative model. A fact spread across three turns, or implied and never
    stated, will not be proposed -- this finds what was said plainly.

    Nothing is written to memory by `propose`. Proposals are staged for review
    and only `apply` writes one, for the same reason `marm_compaction` stages:
    a similarity score is not evidence enough to modify memory unattended.
    """
    if req.action == "propose":
        if not req.text or not req.text.strip():
            return {"status": "error", "error": "propose requires `text`"}
        if not req.session_name:
            return {"status": "error", "error": "propose requires `session_name`"}
        return await distill_service.propose(
            memory,
            req.text,
            session_name=req.session_name,
            project=req.project,
            context_type=req.context_type,
            threshold=req.threshold,
            limit=req.limit,
            include_duplicates=req.include_duplicates,
            use_llm=req.use_llm,
        )

    if req.action == "review":
        return distill_service.review(
            memory, session_name=req.session_name, limit=req.limit
        )

    if not req.proposal_id:
        return {"status": "error", "error": f"{req.action} requires `proposal_id`"}
    if req.action == "apply":
        return await distill_service.apply(memory, req.proposal_id)
    return distill_service.discard(memory, req.proposal_id)
