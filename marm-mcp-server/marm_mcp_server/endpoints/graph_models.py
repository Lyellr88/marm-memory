from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConsoleIndexRequest(BaseModel):
    repo_path: str = Field(..., min_length=1, max_length=4096)
    mode: Literal["full", "moderate", "fast"] = "moderate"


class ConsoleProjectRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)


class ConsoleMemoryBindingRequest(ConsoleProjectRequest):
    memory_project: str = Field(..., min_length=1, max_length=512)


class ConsoleGraphNeighborhoodRequest(ConsoleProjectRequest):
    node_id: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9._/\\@+()\[\] -]+$",
    )


class ConsoleCodeUnitEdgesRequest(ConsoleProjectRequest):
    unit: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        pattern=r"^[A-Za-z0-9._/\\@+()\[\] -]+$",
    )


class ConsoleTraceRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)
    symbol: str = Field(..., min_length=1, max_length=1024)
    direction: Literal["inbound", "outbound", "both"] = "both"
    mode: Literal["calls", "data_flow", "cross_service"] = "calls"
    depth: int = Field(3, ge=1, le=5)


class ConsoleDeleteProjectRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)
    name: str = Field(..., min_length=1, max_length=512)
    confirm: bool = False


class ConsoleAdrUpdateRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1, max_length=200000)


class ConsoleRuntimeTrace(BaseModel):
    caller: str = Field(..., min_length=1, max_length=2048)
    callee: str = Field(..., min_length=1, max_length=2048)
    count: int = Field(..., ge=1, le=1000000)


class ConsoleRuntimeTracesRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=512)
    traces: list[ConsoleRuntimeTrace] = Field(..., min_length=1, max_length=500)


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsoleProjectIndexResponse(_ResponseModel):
    job_id: str


class _ConsoleProjectJobResponse(_ResponseModel):
    job_id: str
    status: str
    project: str | None
    phase: str | None
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class ConsoleProjectJobQueuedResponse(_ConsoleProjectJobResponse):
    status: Literal["queued"]
    project: None
    phase: Literal["queued"]
    error: None
    started_at: None
    finished_at: None


class ConsoleProjectJobRunningResponse(_ConsoleProjectJobResponse):
    status: Literal["running"]
    project: None
    phase: Literal["starting", "indexing"]
    error: None
    started_at: str
    finished_at: None


class ConsoleProjectJobSuccessResponse(_ConsoleProjectJobResponse):
    status: Literal["success"]
    phase: Literal["complete"]
    error: None
    started_at: str


class ConsoleProjectJobErrorResponse(_ConsoleProjectJobResponse):
    status: Literal["error"]
    project: None
    phase: Literal["unavailable", "busy", "failed"]
    error: str
    started_at: str


ConsoleProjectJobResponse = (
    ConsoleProjectJobQueuedResponse
    | ConsoleProjectJobRunningResponse
    | ConsoleProjectJobSuccessResponse
    | ConsoleProjectJobErrorResponse
)
