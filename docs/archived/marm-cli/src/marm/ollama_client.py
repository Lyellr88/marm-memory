"""Ollama client with function calling support for MARM tools"""
import httpx
import json
import logging
import asyncio
import random
from typing import Dict, List, Any, Optional, AsyncIterator, Callable
from dataclasses import dataclass

from .tool_registry import ToolRegistry
from .tool_error import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Chat message"""
    role: str  # system, user, assistant, tool
    content: str
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None


class OllamaClient:
    """
    Ollama client with function calling support

    Integrates MARM tool registry with Ollama chat API for
    natural language tool invocation
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "codellama:13b",
        tool_registry: Optional[ToolRegistry] = None
    ):
        """
        Initialize Ollama client

        Args:
            base_url: Ollama server URL
            model: Model name to use
            tool_registry: MARM tool registry for function calling
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.tool_registry = tool_registry
        self.client = httpx.AsyncClient(timeout=300.0)

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        stream: bool = True,
        temperature: float = 0.7
    ) -> AsyncIterator[Dict]:
        """
        Send chat request to Ollama with optional tool calling

        Args:
            messages: Conversation history
            tools: Function/tool declarations (auto-filled from registry if None)
            stream: Whether to stream response
            temperature: Sampling temperature

        Yields:
            Response chunks from Ollama
        """
        # Auto-fill tools from registry if not provided
        if tools is None and self.tool_registry:
            tools = self.tool_registry.get_function_declarations()
            logger.info(f"Auto-loaded {len(tools)} tools from registry")

        # Build request payload
        payload = {
            "model": self.model,
            "messages": [self._message_to_dict(msg) for msg in messages],
            "stream": stream,
            "options": {
                "temperature": temperature
            }
        }

        # Add tools if available
        if tools:
            payload["tools"] = tools
            logger.debug(f"Sending {len(tools)} tool declarations to Ollama")

        # Send request with retry logic
        url = f"{self.base_url}/api/chat"
        max_attempts = 5

        for attempt in range(1, max_attempts + 1):
            try:
                async with self.client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                chunk = json.loads(line)
                                yield chunk
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse chunk: {e}")
                                continue

                    # Success - exit retry loop
                    break

            except httpx.HTTPStatusError as e:
                # Check if we should retry
                if e.response.status_code in [429, 500, 502, 503, 504] and attempt < max_attempts:
                    # Exponential backoff with jitter (like webchat)
                    base_delay = (2 ** (attempt - 1)) * 0.5  # 0.5, 1, 2, 4, 8 seconds
                    jitter = random.uniform(0, 0.25)  # Add 0-250ms jitter
                    delay = min(base_delay + jitter, 10.0)  # Cap at 10 seconds

                    logger.warning(f"Ollama API error {e.response.status_code} (attempt {attempt}/{max_attempts}), retrying in {delay:.2f}s...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"Ollama API error: {e}")
                    raise

            except httpx.HTTPError as e:
                logger.error(f"Ollama API error: {e}")
                raise

    async def chat_completion(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        max_tool_rounds: int = 5,
        on_tool_call: Optional[Callable[[str, Dict], None]] = None
    ) -> Message:
        """
        Complete chat request with automatic tool execution

        Handles the full tool calling loop:
        1. Send message to LLM
        2. If LLM calls tools, execute them
        3. Feed tool results back to LLM
        4. Repeat until LLM provides final answer (max_tool_rounds times)

        Args:
            messages: Conversation history
            tools: Function declarations (auto-filled from registry)
            max_tool_rounds: Max iterations of tool calling
            on_tool_call: Callback when tool is called (for UI updates)

        Returns:
            Final assistant message
        """
        current_messages = messages.copy()

        for round_num in range(max_tool_rounds):
            logger.info(f"Chat completion round {round_num + 1}/{max_tool_rounds}")

            # Get response from LLM
            full_response = await self._collect_response(current_messages, tools)

            # Check if LLM wants to call tools
            tool_calls = full_response.get("message", {}).get("tool_calls")

            if not tool_calls:
                # No tool calls - return final answer
                content = full_response.get("message", {}).get("content", "")
                return Message(role="assistant", content=content)

            # LLM requested tool calls - execute them
            logger.info(f"LLM requested {len(tool_calls)} tool calls")

            # Add assistant message with tool calls to history
            assistant_msg = Message(
                role="assistant",
                content="",
                tool_calls=tool_calls
            )
            current_messages.append(assistant_msg)

            # Execute each tool call
            for tool_call in tool_calls:
                tool_name = tool_call.get("function", {}).get("name")
                tool_args = tool_call.get("function", {}).get("arguments", {})

                logger.info(f"Executing tool: {tool_name}")

                # Notify UI if callback provided
                if on_tool_call:
                    on_tool_call(tool_name, tool_args)

                # Execute tool via registry
                result = await self._execute_tool(tool_name, tool_args)

                # Add tool result to conversation
                tool_result_msg = Message(
                    role="tool",
                    content=result.llm_content,
                    tool_call_id=tool_call.get("id")
                )
                current_messages.append(tool_result_msg)

        # Max rounds reached - return last response
        logger.warning(f"Max tool rounds ({max_tool_rounds}) reached")
        return Message(
            role="assistant",
            content="I've completed the maximum number of tool calls. Please continue."
        )

    async def _collect_response(self, messages: List[Message], tools: Optional[List[Dict]]) -> Dict:
        """Get full non-streaming response from Ollama"""
        import asyncio

        try:
            # Use stream=False to get complete response immediately (fixes hanging issue)
            async def get_response():
                async for chunk in self.chat(messages, tools, stream=False):
                    return chunk  # With stream=False, we get one complete response
                return {}

            # Add timeout protection (300 seconds - matches main timeout)
            full_response = await asyncio.wait_for(get_response(), timeout=300.0)
        except asyncio.TimeoutError:
            logger.error("Response collection timed out after 300 seconds")
            raise

        return full_response

    async def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> ToolResult:
        """
        Execute tool via registry

        Args:
            tool_name: Name of tool to execute
            tool_args: Tool arguments

        Returns:
            ToolResult with execution outcome
        """
        if not self.tool_registry:
            from .tool_error import ToolError, ToolErrorType
            return ToolResult(
                llm_content="Error: No tool registry configured",
                return_display="❌ Tool registry not available",
                error=ToolError(
                    message="Tool registry not configured",
                    type=ToolErrorType.TOOL_NOT_REGISTERED
                )
            )

        # Get tool from registry
        tool = self.tool_registry.get_tool(tool_name)

        if not tool:
            from .tool_error import ToolError, ToolErrorType
            logger.error(f"Tool not found: {tool_name}")
            return ToolResult(
                llm_content=f"Error: Tool '{tool_name}' not found",
                return_display=f"❌ Unknown tool: {tool_name}",
                error=ToolError(
                    message=f"Tool not registered: {tool_name}",
                    type=ToolErrorType.TOOL_NOT_REGISTERED
                )
            )

        # Execute tool
        try:
            result = await tool.invoke(tool_args)
            logger.info(f"Tool {tool_name} executed successfully")
            return result

        except Exception as e:
            from .tool_error import ToolError, ToolErrorType
            logger.exception(f"Tool execution failed: {e}")
            return ToolResult(
                llm_content=f"Error executing {tool_name}: {str(e)}",
                return_display=f"❌ Tool execution failed: {str(e)}",
                error=ToolError(
                    message=str(e),
                    type=ToolErrorType.EXECUTION_FAILED
                )
            )

    def _message_to_dict(self, message: Message) -> Dict:
        """Convert Message to dict for Ollama API"""
        msg_dict = {
            "role": message.role,
            "content": message.content
        }

        if message.tool_calls:
            msg_dict["tool_calls"] = message.tool_calls

        if message.tool_call_id:
            msg_dict["tool_call_id"] = message.tool_call_id

        return msg_dict

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
