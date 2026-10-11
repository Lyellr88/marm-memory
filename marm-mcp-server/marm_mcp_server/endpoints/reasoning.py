from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from ..services.summary import generate_session_summary


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SummarySuccessResponse(_ResponseModel):
    status: Literal["success"]
    session_name: str
    summary: str
    entry_count: int
    total_entries: int


class SummaryTruncatedResponse(SummarySuccessResponse):
    mcp_truncated: Literal[True] = Field(alias="_mcp_truncated")
    truncation_reason: str = Field(alias="_truncation_reason")


class SummaryEmptyResponse(_ResponseModel):
    status: Literal["empty"]
    message: str


class SummaryErrorResponse(_ResponseModel):
    status: Literal["error"]
    message: str


SummaryResponse = (
    SummarySuccessResponse
    | SummaryTruncatedResponse
    | SummaryEmptyResponse
    | SummaryErrorResponse
)


router = APIRouter(prefix="", tags=["Reasoning"])


@router.get(
    "/marm_summary", operation_id="marm_summary", response_model=SummaryResponse
)
async def marm_summary(
    session_name: str = Query(..., description="The name of the session to summarize."),
) -> dict:
    """
    📊 Generate paste-ready context block for new chats

    Equivalent to /summary: [session name] command
    Uses intelligent truncation to stay within MCP 1MB limits.
    """
    return await generate_session_summary(session_name)
