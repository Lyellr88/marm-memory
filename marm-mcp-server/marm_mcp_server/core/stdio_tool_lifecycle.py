"""Per-call lifecycle wrapper for MARM STDIO tools: logging, session
init, protocol/compaction injection."""

import asyncio
import functools
import json
from typing import Any, Awaitable, Callable

from ..services.documentation import ensure_marm_started, maybe_auto_refresh
from ..utils.helpers import read_protocol_file, read_protocol_lite_file
from .compaction import claim_pending_compaction_prompt
from .memory import memory
from .stdio_logging import _debug, _stdio_log

_protocol_delivered = False
_protocol_call_count = 0
_STDIO_LITE_INTERVAL = 30
_protocol_delivery_lock = asyncio.Lock()


# Deliberately signature-erasing: the wrapper introspects kwargs by name
# (session_name, query, limit), which a ParamSpec types as object.
def _log_tool_call(
    fn: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        name = fn.__name__
        if _debug:
            safe = []
            for k, v in kwargs.items():
                if k == "session_name":
                    safe.append(f"session={v}")
                elif k == "query":
                    safe.append(f"query_len={len(v) if v else 0}")
                elif k in ("limit", "search_all"):
                    safe.append(f"{k}={v}")
            _stdio_log.debug("CALL %s %s", name, " ".join(safe))
        else:
            _stdio_log.info("CALL %s", name)

        global _protocol_delivered, _protocol_call_count
        session_name = kwargs.get("session_name", "default")
        try:
            await ensure_marm_started(session_name)
        except Exception as e:
            _stdio_log.warning("session init failed: %s", e)

        _protocol_call_count += 1
        call_count = _protocol_call_count

        try:
            result = await fn(*args, **kwargs)
        except Exception as e:
            _stdio_log.error("EXCEPTION %s %s: %s", name, type(e).__name__, e)
            raise
        if isinstance(result, dict):
            status = result.get("status", "ok")
            if status == "error":
                _stdio_log.error("FAIL %s: %s", name, result.get("message", ""))
            elif _debug:
                count = next(
                    (
                        result[k]
                        for k in ("results_count", "total_entries", "total_count")
                        if k in result
                    ),
                    None,
                )
                _stdio_log.debug(
                    "OK %s status=%s%s",
                    name,
                    status,
                    f" count={count}" if count is not None else "",
                )
            else:
                _stdio_log.info("OK %s", name)

            protocol_injected = False
            async with _protocol_delivery_lock:
                if not _protocol_delivered:
                    try:
                        result["marm_protocol"] = await read_protocol_file()
                        _protocol_delivered = True
                        protocol_injected = True
                    except Exception as e:
                        _stdio_log.warning("protocol injection failed: %s", e)
                elif call_count % _STDIO_LITE_INTERVAL == 0:
                    try:
                        lite_content = await read_protocol_lite_file()
                        if lite_content:
                            result["marm_protocol_lite"] = lite_content
                            # Lite does not block compaction — protocol_injected stays False
                    except Exception as e:
                        _stdio_log.warning("lite protocol injection failed: %s", e)

            if not protocol_injected:
                # fn may have switched or created the active session (e.g.
                # create_log_entry_stdio without an explicit session_name
                # writes to memory.active_log_session), which makes the
                # pre-call session_name snapshot above stale. Only override
                # it when the caller didn't explicitly pass one -- explicit
                # caller intent is always respected as-is.
                compaction_session = session_name
                if not kwargs.get("session_name"):
                    compaction_session = memory.active_log_session
                try:
                    compaction_block = await asyncio.to_thread(
                        claim_pending_compaction_prompt, memory, compaction_session
                    )
                    if compaction_block:
                        serialized_result = json.dumps(result, ensure_ascii=False)
                        result = {
                            **result,
                            "content": [
                                compaction_block,
                                {
                                    "type": "text",
                                    "text": serialized_result,
                                },
                            ],
                        }
                except Exception as e:
                    _stdio_log.warning("compaction injection failed: %s", e)

        try:
            await maybe_auto_refresh()
        except Exception as e:
            _stdio_log.warning("auto-refresh failed: %s", e)

        return result

    return wrapper
