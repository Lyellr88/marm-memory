"""Request models for marm-graph's tool surface.

These Pydantic models define the input schemas the AI sees for the 5 super-tools
(via FastApiMCP) and the shapes the UI-only REST endpoints accept. Responses are
plain dicts (matching marm-mcp-server's convention).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# ── AI-facing super-tools ───────────────────────────────────────────


class GraphIndexRequest(BaseModel):
    """marm_graph_index — index a repo, or check status / list known projects."""

    repo_path: Optional[str] = Field(
        None, description="Path to the repository to index. Omit to list/status only."
    )
    project: Optional[str] = Field(
        None, description="Existing project name for a status check. Omit to auto-resolve."
    )
    mode: Literal["full", "moderate", "fast"] = Field(
        "moderate",
        description="Index depth: full | moderate | fast. moderate is a good default.",
    )
    action: Literal["auto", "index", "status", "list"] = Field(
        "auto",
        description="auto | index | status | list. 'auto' infers from repo_path presence.",
    )


class CodeLookupRequest(BaseModel):
    """marm_code_lookup — one entry point for graph search, code (grep) search, or
    reading a symbol's source. The wrapper routes by `kind` (auto by default)."""

    query: str = Field(
        ..., description="Symbol name, natural-language phrase, code/text pattern, or a qualified_name."
    )
    project: Optional[str] = Field(None, description="Project name. Omit to auto-resolve.")
    kind: Literal["auto", "symbol", "text", "snippet"] = Field(
        "auto",
        description="auto | symbol | text | snippet. auto: qualified_name→snippet, "
        "regex/code pattern→text search, otherwise→graph symbol search.",
    )
    regex: bool = Field(False, description="For text search: treat query as a regex.")
    file_pattern: Optional[str] = Field(
        None, description="Glob to scope search (e.g. *.py)."
    )
    limit: int = Field(20, ge=1, le=200, description="Max results.")


class GraphTraceRequest(BaseModel):
    """marm_graph_trace — trace call paths / data flow through the graph."""

    function_name: str = Field(..., description="Function or method to trace from.")
    project: Optional[str] = Field(None, description="Project name. Omit to auto-resolve.")
    direction: Literal["inbound", "outbound", "both"] = Field(
        "both", description="inbound | outbound | both."
    )
    depth: int = Field(3, ge=1, le=5, description="Max hops (1-5).")
    mode: Literal["calls", "data_flow", "cross_service"] = Field(
        "calls", description="calls | data_flow | cross_service."
    )
    risk_labels: bool = Field(
        True, description="Add CRITICAL/HIGH/MEDIUM/LOW risk tiers by hop distance."
    )


class GraphArchitectureRequest(BaseModel):
    """marm_graph_architecture — high-level overview + schema in one response."""

    project: Optional[str] = Field(None, description="Project name. Omit to auto-resolve.")


class GraphImpactRequest(BaseModel):
    """marm_graph_impact — blast radius of code changes (git diff → affected symbols)."""

    project: Optional[str] = Field(None, description="Project name. Omit to auto-resolve.")
    since: Optional[str] = Field(
        None, description="Git ref or date to compare from (e.g. HEAD~5, v0.5.0)."
    )
    base_branch: str = Field("main", description="Base branch to diff against.")
    depth: int = Field(2, ge=1, le=5, description="Impact propagation depth.")


# ── UI-only REST models ─────────────────────────────────────────────


class DeleteProjectRequest(BaseModel):
    project: str = Field(..., description="Project to delete (irreversible).")
    confirm: bool = Field(
        False, description="Must be true to proceed — guards against accidental deletion."
    )


class QueryGraphRequest(BaseModel):
    project: str
    query: str = Field(..., description="Cypher query (read-only in v0.1).")
    max_rows: int = Field(1000, ge=1, le=100000)


class ManageAdrRequest(BaseModel):
    project: str
    mode: Literal["get", "update", "sections"] = Field(
        "get", description="get | update | sections."
    )
    content: Optional[str] = None
    sections: Optional[list[str]] = None


class IngestTracesRequest(BaseModel):
    project: str
    traces: list[dict]
