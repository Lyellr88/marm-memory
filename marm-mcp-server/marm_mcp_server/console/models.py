from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConceptBuildPayload(BaseModel):
    session_name: str | None = None
    project: str | None = None
    search_all: bool = False


class ConceptGraphResetPayload(BaseModel):
    confirm: Literal["DELETE_GRAPH"]


class ProjectIndexPayload(BaseModel):
    repo_path: str
    mode: str = "moderate"


class ProjectMemoryBindingPayload(BaseModel):
    memory_project: str = Field(min_length=1, max_length=512)


class ProjectSearchPayload(BaseModel):
    query: str
    kind: str = "auto"
    limit: int = 20


class ProjectTracePayload(BaseModel):
    symbol: str
    direction: str = "both"
    mode: str = "calls"
    depth: int = 3


class ProjectImpactPayload(BaseModel):
    since: str | None = None
    base_branch: str = "main"
    depth: int = 2


class ProjectDeletePayload(BaseModel):
    name: str
    confirm: bool = False


class ProjectAdrPayload(BaseModel):
    content: str = Field(min_length=1, max_length=200000)


class ProjectRuntimeTrace(BaseModel):
    caller: str = Field(min_length=1, max_length=2048)
    callee: str = Field(min_length=1, max_length=2048)
    count: int = Field(ge=1, le=1000000)


class ProjectRuntimeTracesPayload(BaseModel):
    traces: list[ProjectRuntimeTrace] = Field(min_length=1, max_length=500)


class RuntimeAutomationPayload(BaseModel):
    scope: Literal["graph", "concept"]
    enabled: bool


class RuntimeProfilePayload(BaseModel):
    profile: Literal["standard", "swarm", "swarm-max", "trusted"]
    rate_limit_rpm: int | None = None


class CompactionDryRunPayload(BaseModel):
    session_name: str


class MemoryMutationPayload(BaseModel):
    content: str
    session_name: str
    context_type: str | None = "general"
    project: str | None = None
    platform: str | None = None
    metadata: dict | None = None


class MemoryDeletePayload(BaseModel):
    confirm: Literal["DELETE"]


class MemoryBulkDeletePayload(BaseModel):
    memory_ids: list[str]
    confirm: Literal["DELETE"]


class SessionCreatePayload(BaseModel):
    name: str


class SessionDeletePayload(BaseModel):
    confirm: Literal["DELETE"]


class BulkDeletePayload(BaseModel):
    confirm: Literal["DELETE_ALL"]


class SessionBulkDeletePayload(BaseModel):
    session_names: list[str] = Field(min_length=1, max_length=100)
    confirm: Literal["DELETE"]


class LogDeletePayload(BaseModel):
    session_name: str
    confirm: Literal["DELETE"]


class LogDeleteRef(BaseModel):
    id: str
    session_name: str


class LogBulkDeletePayload(BaseModel):
    logs: list[LogDeleteRef] = Field(min_length=1, max_length=100)
    confirm: Literal["DELETE"]


class NotebookMutationPayload(BaseModel):
    name: str
    content: str
    session_name: str = "main"
    project: str | None = None
    platform: str | None = None


class NotebookDeletePayload(BaseModel):
    confirm: Literal["DELETE"]
    session_name: str = "main"
    project: str | None = None
    platform: str | None = None


class NotebookDeleteRef(BaseModel):
    name: str
    session_name: str = "main"
    project: str | None = None
    platform: str | None = None


class NotebookBulkDeletePayload(BaseModel):
    entries: list[NotebookDeleteRef] = Field(min_length=1, max_length=100)
    confirm: Literal["DELETE"]
