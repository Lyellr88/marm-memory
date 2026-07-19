"""Pydantic request models for MARM Console's REST API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ConceptBuildPayload(BaseModel):
    session_name: str | None = None
    project: str | None = None
    search_all: bool = False


class ProjectIndexPayload(BaseModel):
    repo_path: str
    mode: str = "moderate"


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


class LogDeletePayload(BaseModel):
    session_name: str
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
