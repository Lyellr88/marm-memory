import builtins
import sys

_real_print = builtins.print
builtins.print = lambda *args, **kwargs: _real_print(
    *args, **{**kwargs, "file": sys.stderr}
)

import os  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from typing import Optional  # noqa: E402

import anyio  # noqa: E402
from anyio import BrokenResourceError, ClosedResourceError, EndOfStream  # noqa: E402

os.environ["SERVER_HOST"] = "127.0.0.1"

from mcp.server.fastmcp import FastMCP  # noqa: E402

from marm_mcp_server.config.settings import (  # noqa: E402
    CHUNK_DRAIN_TIMEOUT_SECONDS,
    DEFAULT_DB_PATH,
    SEMANTIC_SEARCH_AVAILABLE,
    SERVER_VERSION,
)
from marm_mcp_server.core.concept_worker import concept_worker  # noqa: E402
from marm_mcp_server.core.graph_index_worker import graph_index_worker  # noqa: E402
from marm_mcp_server.core.graph_supervisor import graph_supervisor  # noqa: E402
from marm_mcp_server.core.memory import memory  # noqa: E402
from marm_mcp_server.core.memory_utils import drain_chunk_writes  # noqa: E402
from marm_mcp_server.services.notebook import notebook_dispatch  # noqa: E402
from marm_mcp_server.services.recall import smart_recall  # noqa: E402
from marm_mcp_server.services.stdio_entry_tools import (  # noqa: E402
    create_log_entry_stdio,
    delete_entry_stdio,
    list_log_entries_stdio,
)
from marm_mcp_server.services.summary import generate_session_summary  # noqa: E402

from .core.stdio_logging import _stdio_log  # noqa: E402
from .core.stdio_tool_lifecycle import _log_tool_call  # noqa: E402
from .utils.embedding_state import check_embedding_compatibility  # noqa: E402


@asynccontextmanager
async def _stdio_lifespan(_server: FastMCP) -> AsyncIterator[None]:
    """Drain in-flight chunk writes on teardown, inside the loop mcp.run() owns.

    This cannot live in main()'s finally: that runs after mcp.run() has already
    closed the event loop, where awaiting is impossible and a fresh asyncio.run()
    would see none of the original loop's tasks.

    The drain sits in a finally because an exception thrown into the generator at
    the yield skips anything after it. A crashed or cancelled session is exactly
    when unwritten chunks are most likely to be pending.
    """
    concept_worker.start()
    graph_index_worker.start()
    try:
        yield
    finally:
        with (
            anyio.CancelScope(shield=True),
            anyio.move_on_after(CHUNK_DRAIN_TIMEOUT_SECONDS * 2),
        ):
            try:
                await concept_worker.stop()
            except Exception as exc:
                _stdio_log.warning("concept worker stop failed: %s", exc)
            try:
                await graph_index_worker.stop()
            except Exception as exc:
                _stdio_log.warning("graph auto-index worker stop failed: %s", exc)
            try:
                await memory.stop_write_queue()
            except Exception as exc:
                _stdio_log.warning("write queue drain failed: %s", exc)
            try:
                await drain_chunk_writes(
                    memory,
                    CHUNK_DRAIN_TIMEOUT_SECONDS,
                    lambda message: _stdio_log.info("%s", message),
                )
            except Exception as exc:
                _stdio_log.warning("chunk drain failed: %s", exc)


mcp = FastMCP("MARM MCP Server", lifespan=_stdio_lifespan)


@mcp.tool()
@_log_tool_call
async def marm_smart_recall(
    query: str,
    session_name: str = "default",
    limit: int = 5,
    search_all: bool = False,
    include_logs: bool = False,
    detail: int = 1,
    exact_mode: str = "auto",
    project: Optional[str] = None,
    platform: Optional[str] = None,
) -> dict:
    """
    🧠 Recall memories by semantic similarity or keyword match.

    Searches stored memories for the most relevant matches to `query`.
    Returns a ranked list of results with similarity scores. When a compatible
    concept graph exists, the response also includes bounded relationship and
    linked-code context without changing memory ranking.

    Parameters:
    - query: natural language search term or phrase
    - session_name: limit search to a specific session (default searches active session)
    - limit: maximum number of results to return (default 5)
    - search_all: if True, search across all sessions instead of just the active one
    - include_logs: if True, include log entries alongside memory results
    - detail: controls how much content is returned per result
        1 = summary only (~200 chars)
        2 = extended context (~500 chars)
        3 = full content
    - exact_mode: retrieval lane to use
        'auto'     = automatically switch to exact/lexical for syntax-heavy queries
                     (config keys, file paths, CLI commands, API names, code snippets)
        'exact'    = always use deterministic FTS/BM25, no semantic re-ranking
        'semantic' = always use vector similarity regardless of query shape
    - project: filter results to a specific project (e.g. "marm-memory"); omit to search all
    - platform: filter results to a specific platform (e.g. "claude-code", "cursor"); omit to search all

    Returns: status, ranked results, graph_context, and results_count
    """
    return await smart_recall(
        query,
        session_name,
        limit,
        search_all,
        include_logs,
        detail,
        exact_mode,
        project=project,
        platform=platform,
    )


@mcp.tool()
@_log_tool_call
async def marm_log_entry(
    entry: str,
    session_name: Optional[str] = None,
) -> dict:
    """
    📝 Write a log entry to the active session.

    Entries are stored with a date, topic, and summary. If `entry` begins with
    "Session: [name]" or "Topic: [name]", the active session switches to that name
    and all subsequent entries route there automatically. Entries are also stored
    as semantic memories so marm_smart_recall can find them.

    Entry format: YYYY-MM-DD-topic-summary (date prefix is optional; auto-tagged if omitted)

    Parameters:
    - entry: the text to log; plain text or prefixed with "Session:" / "Topic:" to switch sessions
    - session_name: override the target session explicitly (optional; active session used if omitted)

    Returns: status, message confirming the entry or session switch, entry_id, memory_id
    """
    return await create_log_entry_stdio(entry, session_name)


@mcp.tool()
@_log_tool_call
async def marm_log_show(
    session_name: Optional[str] = None,
) -> dict:
    """
    📋 List log sessions or show entries for a specific session.

    Two modes depending on whether `session_name` is provided:
    - No session_name: returns a summary of all sessions with entry counts
    - With session_name: returns all entries for that session, ordered by date descending

    Parameters:
    - session_name: name of the session to inspect (omit to list all sessions)

    Returns (no session_name): status, sessions list with session_name/entry_count, total_sessions
    Returns (with session_name): status, session_name, entries list with id/entry_date/topic/summary/full_entry, total_entries
    """
    return await list_log_entries_stdio(session_name)


@mcp.tool()
@_log_tool_call
async def marm_delete(
    type: str,
    target: str,
    session_name: Optional[str] = None,
    project: Optional[str] = None,
    platform: Optional[str] = None,
) -> dict:
    """
    🗑️ Delete a log session, log entry, or notebook entry

    type="log" + session_name: delete specific entry by id or topic
    type="log" (no session_name): delete entire session and all its entries
    type="notebook": delete notebook entry by name
    """
    return await delete_entry_stdio(type, target, session_name, project, platform)


@mcp.tool()
@_log_tool_call
async def marm_notebook(
    action: str,
    name: Optional[str] = None,
    data: Optional[str] = None,
    names: Optional[str] = None,
    session_name: str = "main",
    project: Optional[str] = None,
    platform: Optional[str] = None,
) -> dict:
    """
    📔 Unified notebook — add, use, show, status, clear, or save

    action="add": save or update a scratch entry (name + data required)
    action="use": activate entries as instructions (names required, comma-separated)
    action="show": list scratch entries for this session with previews
    action="status": show currently active entries
    action="clear": clear the active entry list
    action="save": promote a scratch entry (or new data) into the permanent docs store
    """
    try:
        return await notebook_dispatch(
            action=action,
            name=name,
            data=data,
            names=names,
            session_name=session_name,
            project=project,
            platform=platform,
        )
    except Exception as e:
        return {"status": "error", "message": f"Notebook operation failed: {e!s}"}


@mcp.tool()
@_log_tool_call
async def marm_summary(
    session_name: str,
) -> dict:
    """
    📊 Generate paste-ready context block for new chats

    Reads log_entries for the session and returns a formatted markdown summary.
    Equivalent to /summary: [session name] command
    """
    return await generate_session_summary(session_name)


@mcp.tool()
@_log_tool_call
async def marm_compaction(
    action: str,
    summaries: Optional[list] = None,
    candidate_id: Optional[str] = None,
) -> dict:
    """
    Compact related memories into a single summary to reduce context bloat.

    Workflow: status/candidates → stage → review → apply/discard

    action="status"     — check if compaction candidates exist (run first)
    action="candidates" — get pending candidates with source previews; each includes a ready-to-use prompt
    action="stage"      — submit your summary: {candidate_id, suggested_summary}; source_memory_ids optional
    action="review"     — inspect staged summaries before committing
    action="apply"      — commit a staged summary; source memories are marked compacted
    action="discard"    — reject a staged summary without touching source memories
    """
    try:
        from marm_mcp_server.core.models import CompactionRequest, StagedSummaryItem
        from marm_mcp_server.endpoints.compaction import marm_compaction as _impl

        items = []
        if summaries is not None:
            if not isinstance(summaries, list):
                return {"status": "error", "message": "summaries must be a list"}
            for item in summaries:
                if not isinstance(item, dict):
                    return {
                        "status": "error",
                        "message": "each summary item must be an object",
                    }
                missing = [
                    key
                    for key in (
                        "candidate_id",
                        "suggested_summary",
                    )
                    if key not in item
                ]
                if missing:
                    return {
                        "status": "error",
                        "message": f"summary item missing required fields: {missing}",
                    }
                items.append(
                    StagedSummaryItem(
                        candidate_id=item["candidate_id"],
                        source_memory_ids=item.get("source_memory_ids"),
                        suggested_summary=item["suggested_summary"],
                    )
                )

        return await _impl(
            CompactionRequest(
                action=action,
                summaries=items if summaries is not None else None,
                candidate_id=candidate_id,
            )
        )
    except Exception as e:
        return {"status": "error", "message": f"Compaction operation failed: {e!s}"}


from .services.stdio_graph_tools import (  # noqa: E402,F401
    marm_code_lookup,
    marm_concept_build,
    marm_concept_recall,
    marm_graph_architecture,
    marm_graph_impact,
    marm_graph_index,
    marm_graph_trace,
    register_graph_tools,
)

register_graph_tools(mcp)


def _is_graceful_teardown(exc: BaseException) -> bool:
    """Return True only if exc is safe to swallow as normal STDIO EOF teardown.

    Accepts AnyIO stream-closure exceptions directly. For grouped exceptions,
    every nested sub-exception must also be graceful teardown; mixed groups are
    not swallowed so real bugs are not lost.
    """
    if isinstance(exc, (ClosedResourceError, EndOfStream, BrokenResourceError)):
        return True

    grouped = getattr(exc, "exceptions", None)
    if not grouped:
        return False

    for sub_exc in grouped:
        if not isinstance(sub_exc, BaseException):
            return False
        if not _is_graceful_teardown(sub_exc):
            return False
    return True


def _stop_graph_supervisor_safely() -> None:
    """Best-effort graph child-process shutdown; must not mask normal STDIO teardown."""
    try:
        graph_supervisor.stop()
    except Exception as e:
        _stdio_log.warning("graph shutdown failed: %s", e)


def main() -> None:
    _stdio_log.info(
        "startup version=%s db=%s semantic_search=%s",
        SERVER_VERSION,
        DEFAULT_DB_PATH,
        SEMANTIC_SEARCH_AVAILABLE,
    )
    check_embedding_compatibility(
        warn=lambda message: _stdio_log.warning("%s", message)
    )
    memory.restore_active_session()
    try:
        mcp.run()
    except BaseException as exc:
        if _is_graceful_teardown(exc):
            _stdio_log.debug("stdin closed during shutdown (normal teardown)")
            return
        raise
    finally:
        _stop_graph_supervisor_safely()
        _stdio_log.info("shutdown")


if __name__ == "__main__":
    main()
