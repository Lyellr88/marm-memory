"""Structured error types for MARM tools"""
from enum import Enum
from typing import Optional
from dataclasses import dataclass


class ToolErrorType(Enum):
    """Machine-readable error types for tool execution"""

    # Registration errors
    TOOL_NOT_REGISTERED = "tool_not_registered"
    TOOL_ALREADY_REGISTERED = "tool_already_registered"

    # Validation errors
    INVALID_TOOL_PARAMS = "invalid_tool_params"
    MISSING_REQUIRED_PARAM = "missing_required_param"
    INVALID_PARAM_TYPE = "invalid_param_type"
    INVALID_PARAM_VALUE = "invalid_param_value"

    # Execution errors
    EXECUTION_FAILED = "execution_failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    # Memory/Database errors
    DATABASE_ERROR = "database_error"
    MEMORY_NOT_FOUND = "memory_not_found"
    DUPLICATE_ENTRY = "duplicate_entry"

    # Permission errors
    PERMISSION_DENIED = "permission_denied"
    UNAUTHORIZED = "unauthorized"

    # System errors
    UNHANDLED_EXCEPTION = "unhandled_exception"
    RESOURCE_NOT_AVAILABLE = "resource_not_available"


@dataclass
class ToolError:
    """Structured error information for tool failures"""
    message: str
    type: ToolErrorType
    suggestion: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for serialization"""
        return {
            "message": self.message,
            "type": self.type.value,
            "suggestion": self.suggestion
        }

    def __str__(self):
        """Human-readable error string"""
        error_str = f"{self.type.value}: {self.message}"
        if self.suggestion:
            error_str += f"\nSuggestion: {self.suggestion}"
        return error_str


@dataclass
class ToolResult:
    """
    Dual-purpose tool result

    Attributes:
        llm_content: Content for LLM conversation history (facts/data)
        return_display: User-facing formatted output
        error: Optional error information
    """
    llm_content: str
    return_display: str
    error: Optional[ToolError] = None

    @property
    def success(self) -> bool:
        """Check if execution was successful"""
        return self.error is None

    def to_dict(self):
        """Convert to dictionary for serialization"""
        result = {
            "llm_content": self.llm_content,
            "return_display": self.return_display,
            "success": self.success
        }
        if self.error:
            result["error"] = self.error.to_dict()
        return result
