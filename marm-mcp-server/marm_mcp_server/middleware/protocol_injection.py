"""MCP protocol/compaction injection middleware for MARM MCP Server."""

import asyncio
import json

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..core.compaction import claim_pending_compaction_prompt
from ..core.memory import memory
from ..core.protocol_delivery_state import (
    _PROTOCOL_LITE_INTERVAL,
    _mark_protocol_session_delivered,
    _protocol_call_counts,
    _protocol_delivery_lock,
    _protocol_session_delivered,
    _prune_call_counts,
)
from ..services.documentation import (
    docs_are_loaded,
    ensure_marm_started,
    maybe_auto_refresh,
)
from ..utils.helpers import read_protocol_file, read_protocol_lite_file

logger = structlog.get_logger()


async def _mcp_tool_call_tracker(request: Request, call_next):
    """Lazy doc-load and auto-refresh for MCP tool calls.

    Registered first so LIFO puts it last — only runs after rate_limit and auth pass.
    Only acts on tools/call requests; init, discovery, and rejected requests are ignored.
    Doc loading runs before the handler so the first tool call gets warm docs,
    matching STDIO transport timing.

    On the first successful tool call for each session, the MARM protocol is injected
    into the response so each agent receives it exactly once. Tracked per session_name
    in _protocol_delivered_sessions. Tools that omit session_name share a "__default__"
    scope — agents should use distinct session names for independent delivery.
    Note: the session is marked delivered when read_protocol_file() succeeds; a later
    failure during response mutation marks the session delivered even if the client
    did not receive the injection.
    """
    is_tool_call = False
    body = b""
    if request.method == "POST" and request.url.path == "/mcp":
        try:
            body = await request.body()
            is_tool_call = b'"tools/call"' in body
        except Exception as exc:
            logger.debug(
                "Failed to parse MCP tool call body for session routing",
                error=str(exc),
                body_preview=body[:200].decode("utf-8", errors="replace"),
                exc_info=True,
            )

    if is_tool_call and not docs_are_loaded():
        await ensure_marm_started("default")

    response = await call_next(request)

    if is_tool_call:
        asyncio.create_task(maybe_auto_refresh())  # noqa: RUF006

    if is_tool_call and response.status_code == 200:
        _explicit_session = None
        _tool_name = None
        try:
            _parsed_body = json.loads(body)
            _explicit_session = (
                _parsed_body.get("params", {}).get("arguments", {}).get("session_name")
            ) or None
            _tool_name = _parsed_body.get("params", {}).get("name")
        except Exception:
            pass

        _protocol_session = _explicit_session or "__default__"
        if _explicit_session:
            _compaction_session = _explicit_session
        elif _tool_name == "marm_log_entry":
            _compaction_session = memory.active_log_session
        elif _tool_name in ("marm_notebook", "marm_smart_recall"):
            _compaction_session = "main"
        else:
            _compaction_session = None

        # Move counter and pruning under lock to prevent races
        async with _protocol_delivery_lock:
            _protocol_call_counts[_protocol_session] = (
                _protocol_call_counts.get(_protocol_session, 0) + 1
            )
            call_count = _protocol_call_counts[_protocol_session]
            _prune_call_counts()

            # Skip body mutation if protocol already delivered, compaction off,
            # and we're not at the lite reinjection interval.
            if (
                _protocol_session_delivered(_protocol_session)
                and not settings.COMPACTION_ENABLED
            ):
                if call_count % _PROTOCOL_LITE_INTERVAL != 0:
                    return response
                # Fall through to inject lite protocol below.

        try:
            content_type = response.headers.get("content-type", "") or ""
            if (
                isinstance(content_type, str)
                and content_type
                and "application/json" not in content_type
            ):
                return response
        except Exception:
            pass

        body_bytes = b""
        try:
            async for chunk in response.body_iterator:
                body_bytes += chunk
            data = json.loads(body_bytes)
            result = data.get("result", {})
            content = result.get("content")

            if not isinstance(content, list):
                from starlette.responses import Response as StarletteResponse

                return StarletteResponse(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type="application/json",
                )

            injections = []
            protocol_injected = False
            async with _protocol_delivery_lock:
                if not _protocol_session_delivered(_protocol_session):
                    protocol_content = await read_protocol_file()
                    injections.append(
                        {
                            "type": "text",
                            "text": f"[MARM SESSION INIT]\n\n{protocol_content}",
                        }
                    )
                    _mark_protocol_session_delivered(_protocol_session)
                    protocol_injected = True
                elif call_count % _PROTOCOL_LITE_INTERVAL == 0:
                    lite_content = await read_protocol_lite_file()
                    if lite_content:
                        injections.append(
                            {
                                "type": "text",
                                "text": f"[MARM PROTOCOL REFRESH]\n\n{lite_content}",
                            }
                        )
                        # Lite does not set protocol_injected=True — allows
                        # compaction to coexist on the same call.

            if not protocol_injected:
                compaction_block = await asyncio.to_thread(
                    claim_pending_compaction_prompt, memory, _compaction_session
                )
                if compaction_block:
                    injections.append(compaction_block)

            if not injections:
                from starlette.responses import Response as StarletteResponse

                return StarletteResponse(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type="application/json",
                )

            content[:0] = injections
            return JSONResponse(
                content=data,
                status_code=response.status_code,
                headers={
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() not in ("content-length", "content-type")
                },
            )
        except Exception as e:
            logger.warning("Protocol injection failed", error=str(e))
            from starlette.responses import Response as StarletteResponse

            return StarletteResponse(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="application/json",
            )

    return response
