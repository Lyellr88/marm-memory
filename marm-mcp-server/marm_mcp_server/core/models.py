"""Pydantic models for MARM MCP Server endpoints."""

from pydantic import BaseModel, Field
from typing import Literal, Optional


class SessionRequest(BaseModel):
    session_name: str = Field(..., description="Name of the session")


class LogEntryRequest(BaseModel):
    entry: str = Field(..., description="Log entry in format: YYYY-MM-DD-topic-summary")
    session_name: Optional[str] = Field(default=None, description="Session name — omit to use the active session set by marm_log_session")


class NotebookRequest(BaseModel):
    action: Literal["add", "use", "show", "status", "clear"] = Field(..., description="Action: add, use, show, status, or clear")
    name: Optional[str] = Field(default=None, description="Entry name (required for action='add')")
    data: Optional[str] = Field(default=None, description="Entry content (required for action='add')")
    names: Optional[str] = Field(default=None, description="Comma-separated entry names (required for action='use')")
    session_name: str = Field(default="main", description="Session scope for active notebook entries")


class SmartRecallRequest(BaseModel):
    query: str = Field(..., description="Query to search for in memory")
    session_name: str = Field(default="main", description="Session to search in")
    limit: int = Field(default=5, description="Maximum number of results")
    search_all: bool = Field(default=False, description="Search across all sessions if True")
    include_logs: bool = Field(default=False, description="Also search log_entries for text matches and include in response")


class ContextLogRequest(BaseModel):
    content: str = Field(..., description="Content to log with auto-classification")
    session_name: str = Field(default="main", description="Session to log to")


class DeleteRequest(BaseModel):
    type: Literal["log", "notebook"] = Field(..., description="What to delete: 'log' or 'notebook'")
    target: str = Field(..., description="Log entry id/topic, log session name, or notebook entry name")
    session_name: Optional[str] = Field(default=None, description="Log session to scope deletion. Omit to delete an entire session.")
