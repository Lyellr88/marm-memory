"""Base classes for MARM tools - adapted from qwen-code DeclarativeTool pattern"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Generic, TypeVar, Type, Callable
from enum import Enum
from pydantic import BaseModel
import logging
import asyncio

from .tool_error import ToolError, ToolResult, ToolErrorType
from .tool_schema import SchemaGenerator, generate_function_declaration

logger = logging.getLogger(__name__)

# Generic type variables
TParams = TypeVar('TParams', bound=BaseModel)
TResult = TypeVar('TResult')


class ToolKind(Enum):
    """Tool operation kind - determines confirmation requirements"""
    READ = "read"           # Read-only, no confirmation needed
    WRITE = "write"         # Writes data, may need confirmation
    EDIT = "edit"           # Modifies existing data
    DELETE = "delete"       # Deletes data, requires confirmation
    EXECUTE = "execute"     # Executes commands, requires confirmation
    SYSTEM = "system"       # System operations


class ToolState(Enum):
    """Tool execution state"""
    VALIDATING = "validating"
    SCHEDULED = "scheduled"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class BaseToolInvocation(ABC, Generic[TParams, TResult]):
    """
    Base class for tool invocations

    Represents a single execution instance of a tool with specific parameters
    """

    def __init__(self, params: TParams):
        self.params = params
        self.state = ToolState.VALIDATING
        self.result: Optional[TResult] = None
        self.error: Optional[ToolError] = None

    @abstractmethod
    def get_description(self) -> str:
        """
        Get human-readable description of what this invocation will do

        Example: "Searching for: docker setup"
        """
        pass

    @abstractmethod
    async def execute(
        self,
        update_output: Optional[Callable[[str], None]] = None
    ) -> ToolResult:
        """
        Execute the tool with given parameters

        Args:
            update_output: Optional callback for streaming output updates

        Returns:
            ToolResult with llm_content and return_display
        """
        pass

    async def run(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """
        Run the tool invocation with state management

        Args:
            update_output: Optional callback for live output streaming

        Returns:
            ToolResult
        """
        try:
            self.state = ToolState.EXECUTING
            result = await self.execute(update_output)
            self.state = ToolState.SUCCESS
            self.result = result
            return result

        except Exception as e:
            self.state = ToolState.ERROR
            error = ToolError(
                message=str(e),
                type=ToolErrorType.EXECUTION_FAILED,
                suggestion="Check logs for details"
            )
            self.error = error
            logger.exception(f"Tool execution failed: {e}")

            return ToolResult(
                llm_content=f"Error: {str(e)}",
                return_display=f"❌ Execution failed: {str(e)}",
                error=error
            )


class BaseDeclarativeTool(ABC, Generic[TParams]):
    """
    Base class for declarative tools

    Defines tool metadata, schema, and creates invocations
    """

    def __init__(
        self,
        name: str,
        display_name: str,
        description: str,
        kind: ToolKind,
        parameters_model: Type[TParams],
        is_output_markdown: bool = False,
        can_update_output: bool = False
    ):
        """
        Initialize declarative tool

        Args:
            name: Tool identifier (e.g., "marm_smart_recall")
            display_name: Human-readable name
            description: What the tool does (for LLM)
            kind: Tool operation kind
            parameters_model: Pydantic model for parameters
            is_output_markdown: Whether output is markdown formatted
            can_update_output: Whether tool supports streaming output
        """
        self.name = name
        self.display_name = display_name
        self.description = description
        self.kind = kind
        self.parameters_model = parameters_model
        self.is_output_markdown = is_output_markdown
        self.can_update_output = can_update_output

        # Generate JSON Schema from Pydantic model
        self._parameter_schema = SchemaGenerator.from_pydantic(parameters_model)

    @property
    def parameter_schema(self) -> Dict[str, Any]:
        """Get JSON Schema for tool parameters"""
        return self._parameter_schema

    def get_function_declaration(self) -> Dict[str, Any]:
        """
        Get function declaration for LLM function calling API

        Returns:
            Function declaration dict with name, description, parameters
        """
        return generate_function_declaration(
            self.name,
            self.description,
            self.parameter_schema
        )

    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, str]:
        """
        Validate parameters against JSON Schema

        Args:
            params: Parameters dict to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # First: JSON Schema validation
        is_valid, error = SchemaGenerator.validate_params(self.parameter_schema, params)
        if not is_valid:
            return False, error

        # Second: Custom validation (override in subclass)
        custom_error = self.validate_param_values(params)
        if custom_error:
            return False, custom_error

        return True, ""

    def validate_param_values(self, params: Dict[str, Any]) -> Optional[str]:
        """
        Custom validation logic for parameter values

        Override this to add domain-specific validation

        Args:
            params: Parameters dict

        Returns:
            Error message if invalid, None if valid
        """
        return None

    @abstractmethod
    def create_invocation(self, params: TParams) -> BaseToolInvocation[TParams, Any]:
        """
        Create tool invocation instance with validated parameters

        Args:
            params: Validated parameters

        Returns:
            ToolInvocation instance
        """
        pass

    async def invoke(
        self,
        params: Dict[str, Any],
        update_output: Optional[Callable[[str], None]] = None
    ) -> ToolResult:
        """
        Validate parameters and execute tool

        Args:
            params: Parameters dict
            update_output: Optional callback for streaming output

        Returns:
            ToolResult
        """
        # Validate parameters
        is_valid, error_msg = self.validate_params(params)
        if not is_valid:
            error = ToolError(
                message=error_msg,
                type=ToolErrorType.INVALID_TOOL_PARAMS,
                suggestion="Check parameter types and values"
            )
            return ToolResult(
                llm_content=f"Validation error: {error_msg}",
                return_display=f"❌ Invalid parameters: {error_msg}",
                error=error
            )

        try:
            # Parse params using Pydantic model
            validated_params = self.parameters_model(**params)

            # Create and run invocation
            invocation = self.create_invocation(validated_params)
            result = await invocation.run(update_output)

            return result

        except Exception as e:
            logger.exception(f"Tool invocation failed: {e}")
            error = ToolError(
                message=str(e),
                type=ToolErrorType.EXECUTION_FAILED
            )
            return ToolResult(
                llm_content=f"Error: {str(e)}",
                return_display=f"❌ Execution failed: {str(e)}",
                error=error
            )

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name} kind={self.kind.value}>"
