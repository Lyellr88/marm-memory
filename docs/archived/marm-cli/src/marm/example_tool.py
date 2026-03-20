"""Example tool demonstrating the MARM tool pattern"""
from pydantic import BaseModel, Field
from typing import Optional, Callable

from .tools import BaseDeclarativeTool, BaseToolInvocation, ToolKind
from .tool_error import ToolResult


class EchoToolParams(BaseModel):
    """Parameters for echo tool"""
    message: str = Field(..., description="Message to echo back")
    repeat: int = Field(default=1, description="Number of times to repeat (1-10)", ge=1, le=10)


class EchoToolInvocation(BaseToolInvocation[EchoToolParams, ToolResult]):
    """Echo tool invocation"""

    def get_description(self) -> str:
        return f"Echoing message {self.params.repeat} time(s)"

    async def execute(self, update_output: Optional[Callable[[str], None]] = None) -> ToolResult:
        """Execute echo - repeat message N times"""

        # Simulate streaming output
        output_lines = []
        for i in range(self.params.repeat):
            line = f"{i+1}. {self.params.message}"
            output_lines.append(line)

            # Stream each line if callback provided
            if update_output:
                update_output(line)

        result_text = "\n".join(output_lines)

        return ToolResult(
            llm_content=result_text,
            return_display=f"Echo Result:\n{result_text}"
        )


class EchoTool(BaseDeclarativeTool[EchoToolParams]):
    """
    Simple echo tool for testing

    Demonstrates:
    - Pydantic parameter validation
    - JSON Schema generation
    - Streaming output
    """

    def __init__(self):
        super().__init__(
            name="echo",
            display_name="Echo Tool",
            description="Repeats a message N times. Useful for testing tool invocation.",
            kind=ToolKind.READ,
            parameters_model=EchoToolParams,
            is_output_markdown=False,
            can_update_output=True  # Supports streaming
        )

    def validate_param_values(self, params: dict) -> Optional[str]:
        """Custom validation"""
        # Example: additional business logic validation
        repeat = params.get("repeat", 1)
        if repeat > 5:
            return "Warning: repeating more than 5 times may be excessive"
        return None

    def create_invocation(self, params: EchoToolParams) -> EchoToolInvocation:
        """Create invocation instance"""
        return EchoToolInvocation(params)
