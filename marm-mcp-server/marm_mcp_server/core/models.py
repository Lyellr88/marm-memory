"""Pydantic models for MARM MCP Server endpoints."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class SessionRequest(BaseModel):
    session_name: str = Field(..., description="Name of the session")


class LogEntryRequest(BaseModel):
    entry: str = Field(..., description="Log entry in format: YYYY-MM-DD-topic-summary")
    session_name: Optional[str] = Field(
        default=None,
        description="Session name — omit to use the active session (auto-restored on startup)",
    )


class NotebookRequest(BaseModel):
    action: Literal["add", "use", "show", "status", "clear"] = Field(
        ..., description="Action: add, use, show, status, or clear"
    )
    name: Optional[str] = Field(
        default=None, description="Entry name (required for action='add')"
    )
    data: Optional[str] = Field(
        default=None, description="Entry content (required for action='add')"
    )
    names: Optional[str] = Field(
        default=None,
        description="Comma-separated entry names (required for action='use')",
    )
    session_name: str = Field(
        default="main", description="Session scope for active notebook entries"
    )


class SmartRecallRequest(BaseModel):
    query: str = Field(..., description="Query to search for in memory")
    session_name: str = Field(default="main", description="Session to search in")
    limit: int = Field(default=5, description="Maximum number of results")
    search_all: bool = Field(
        default=False, description="Search across all sessions if True"
    )
    include_logs: bool = Field(
        default=False,
        description="Also search log_entries for text matches and include in response",
    )
    detail: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Retrieval depth: 1=summary (~200 chars), 2=context (~500 chars), 3=full content",
    )
    exact_mode: Literal["auto", "exact", "semantic"] = Field(
        default="auto",
        description=(
            "Retrieval lane: "
            "'auto' detects syntax-heavy queries (config keys, file paths, CLI commands, "
            "API names, code snippets) and uses the exact/lexical lane automatically; "
            "'exact' always uses deterministic FTS/BM25 ranking with no semantic re-ranking; "
            "'semantic' always uses vector similarity regardless of query shape."
        ),
    )

    project: Optional[str] = Field(
        default=None,
        description="Filter to a specific project name (e.g. 'marm-memory'); omit to search all",
    )

    platform: Optional[str] = Field(
        default=None,
        description="Filter to a specific platform (e.g. 'claude-code', 'cursor'); omit to search all",
    )


class DeleteRequest(BaseModel):
    type: Literal["log", "notebook"] = Field(
        ..., description="What to delete: 'log' or 'notebook'"
    )
    target: str = Field(
        ..., description="Log entry id/topic, log session name, or notebook entry name"
    )
    session_name: Optional[str] = Field(
        default=None,
        description="Log session to scope deletion. Omit to delete an entire session.",
    )


class StagedSummaryItem(BaseModel):
    candidate_id: str = Field(..., description="Compaction staging candidate ID")
    source_memory_ids: Optional[list[str]] = Field(
        default=None,
        description="Source memory IDs — omit to use the staged candidate's IDs automatically; if provided, must match exactly",
    )
    suggested_summary: str = Field(
        ..., description="Agent-generated summary of the source memories"
    )


class StageCompactionSummariesRequest(BaseModel):
    summaries: list[StagedSummaryItem] = Field(
        ..., description="One or more candidate summaries to stage"
    )


class ApplyCompactionRequest(BaseModel):
    candidate_id: str = Field(..., description="Compaction staging candidate ID")
    action: Literal["apply", "discard"] = Field(
        ..., description="apply: commit summary to memories; discard: reject proposal"
    )


class CompactionRequest(BaseModel):
    action: Literal["status", "candidates", "review", "stage", "apply", "discard"] = (
        Field(..., description="Compaction action to run")
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum staged proposals to return for action='review'",
    )
    summaries: Optional[list[StagedSummaryItem]] = Field(
        default=None, description="Required for action='stage'"
    )
    candidate_id: Optional[str] = Field(
        default=None, description="Required for action='apply' or action='discard'"
    )

    @model_validator(mode="after")
    def validate_action_requirements(self):
        if self.action == "stage" and not self.summaries:
            raise ValueError("summaries is required for action='stage'")
        if self.action in ("apply", "discard") and not self.candidate_id:
            raise ValueError(f"candidate_id is required for action='{self.action}'")
        return self


class ConceptBuildRequest(BaseModel):
    run_id: Optional[str] = Field(
        default=None,
        description="Optional caller-provided build-run ID for Console status polling.",
    )
    session_name: Optional[str] = Field(
        default=None,
        description="Scope extraction to this session. Omit with search_all=True for everything.",
    )
    search_all: bool = Field(
        default=False,
        description="Extract across all sessions (row-capped, see CONCEPT_BUILD_ROW_CAP).",
    )
    project: Optional[str] = Field(
        default=None, description="Scope extraction to this project."
    )

    @model_validator(mode="after")
    def validate_scope_requirements(self):
        if not (self.session_name or self.project or self.search_all):
            raise ValueError(
                "session_name, project, or search_all=True is required to scope the build"
            )
        return self


class ConceptRecallRequest(BaseModel):
    query: str = Field(
        ...,
        description="Concept name, or a 'related to X' style ask. Both route from query shape alone.",
    )
    session_name: Optional[str] = Field(
        default=None, description="Scope to this session. Omit to search across all."
    )
    project: Optional[str] = Field(
        default=None,
        description="Scope to this project. Omit to search across all projects.",
    )
    limit: int = Field(
        default=10, ge=1, le=100, description="Max entities/relationships returned."
    )
    depth: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Max hop distance to traverse (1 = direct neighbors only).",
    )
    direction: Literal["outgoing", "incoming", "both"] = Field(
        default="both", description="Traversal direction per hop."
    )
