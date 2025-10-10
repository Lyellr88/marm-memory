"""Pydantic models for MARM MCP Server endpoints."""

from pydantic import BaseModel, Field
from typing import Optional


class SessionRequest(BaseModel):
    session_name: str = Field(..., description="Name of the session")


class LogEntryRequest(BaseModel):
    entry: str = Field(..., description="Log entry in format: YYYY-MM-DD-topic-summary")
    session_name: str = Field(default="main", description="Session name")


class NotebookAddRequest(BaseModel):
    name: str = Field(..., description="Name of the notebook entry")
    data: str = Field(..., description="Content of the notebook entry")


class NotebookUseRequest(BaseModel):
    names: str = Field(..., description="Comma-separated list of notebook entry names")


class ContextBridgeRequest(BaseModel):
    new_topic: str = Field(..., description="New topic for context bridging")
    session_name: str = Field(default="main", description="Session name")


class SmartRecallRequest(BaseModel):
    query: str = Field(..., description="Query to search for in memory")
    session_name: str = Field(default="main", description="Session to search in")
    limit: int = Field(default=5, description="Maximum number of results")
    search_all: bool = Field(default=False, description="Search across all sessions if True")


class ContextualLogRequest(BaseModel):
    content: str = Field(..., description="Content to log with auto-classification")
    session_name: str = Field(default="main", description="Session to log to")