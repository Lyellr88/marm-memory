"""
MARM MCP Server - STDIO Transport
Memory Accurate Response Mode for Model Context Protocol

Runs via the official MCP SDK over standard input/output. No port, no API key, no HTTP listener.
Intended for local single-client use (e.g. Docker STDIO, direct CLI invocation).

Usage:
  python -m marm_mcp_server.server_stdio
  docker run -i --rm -v ~/.marm:/home/marm/.marm lyellr88/marm-mcp-server:latest python -m marm_mcp_server.server_stdio
"""

import asyncio
import builtins
import sys

_real_print = builtins.print
builtins.print = lambda *args, **kwargs: _real_print(
    *args, **{**kwargs, "file": sys.stderr}
)

import os  # noqa: E402
import re  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Literal, Optional  # noqa: E402

from anyio import BrokenResourceError, ClosedResourceError, EndOfStream  # noqa: E402
from pydantic import ValidationError  # noqa: E402

os.environ["SERVER_HOST"] = "127.0.0.1"

from .core.stdio_logging import _stdio_log  # noqa: E402

from .core.stdio_tool_lifecycle import _log_tool_call  # noqa: E402


from mcp.server.fastmcp import FastMCP  # noqa: E402

from marm_mcp_server.core.memory import memory  # noqa: E402
from marm_mcp_server.core.events import events  # noqa: E402
from marm_mcp_server.services.notebook import notebook_dispatch  # noqa: E402
from marm_mcp_server.services.summary import generate_session_summary  # noqa: E402
from marm_mcp_server.services.recall import smart_recall  # noqa: E402
from marm_mcp_server.endpoints.concepts import (  # noqa: E402
    marm_concept_build as _marm_concept_build_endpoint,
    _run_recall,
)
from marm_mcp_server.core.models import (  # noqa: E402
    ConceptBuildRequest,
    ConceptRecallRequest,
)
from marm_mcp_server.config.settings import (  # noqa: E402
    SERVER_VERSION,
    DEFAULT_DB_PATH,
    SEMANTIC_SEARCH_AVAILABLE,
    MARM_PROJECT,
    MARM_PLATFORM,
)
from marm_mcp_server.core.graph_supervisor import graph_supervisor  # noqa: E402
from marm_graph.core import tool_router as graph_router  # noqa: E402
from marm_graph.core.models import (  # noqa: E402
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)

mcp = FastMCP("MARM MCP Server")


def _graph_unavailable() -> dict:
    """Fresh dict per call -- _log_tool_call mutates result in place (protocol
    injection, compaction blocks), so a shared constant here would leak state
    (e.g. marm_protocol) into every subsequent unavailable response."""
    return {"status": "error", "message": "graph backend unavailable"}


async def _graph_available() -> bool:
    return await asyncio.to_thread(graph_supervisor.is_available)


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
    Returns a ranked list of results with similarity scores.

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

    Returns: status, results list with id/content/score/project/platform, results_count
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


_SESSION_PREFIXES = ("Session: ", "Topic: ")
_SESSION_INACTIVITY_NOTICE_SECONDS = 3600


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
    try:
        formatted_entry = entry.strip()

        # Session-switch detection
        for prefix in _SESSION_PREFIXES:
            if formatted_entry.startswith(prefix):
                base_name = formatted_entry[len(prefix) :].strip()
                if not base_name:
                    return {
                        "status": "error",
                        "message": "Session name cannot be empty.",
                    }
                date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                new_session = f"{base_name}-{date_tag}"
                marker_id = str(uuid.uuid4())
                with memory.get_connection() as conn:
                    conn.execute("UPDATE sessions SET marm_active = FALSE")
                    conn.execute(
                        """
                        INSERT INTO sessions (session_name, last_accessed, marm_active)
                        VALUES (?, ?, TRUE)
                        ON CONFLICT(session_name) DO UPDATE SET
                            last_accessed = excluded.last_accessed,
                            marm_active = TRUE
                        """,
                        (new_session, datetime.now(timezone.utc).isoformat()),
                    )
                    conn.execute(
                        """
                        INSERT INTO log_entries
                            (id, session_name, entry_date, topic, summary, full_entry, project, platform)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            marker_id,
                            new_session,
                            date_tag,
                            "session_start",
                            base_name,
                            formatted_entry,
                            MARM_PROJECT or None,
                            MARM_PLATFORM or None,
                        ),
                    )
                    try:
                        conn.execute(
                            "UPDATE session_summary_cache SET dirty = TRUE, updated_at = ? WHERE session_name = ?",
                            (datetime.now(timezone.utc).isoformat(), new_session),
                        )
                    except Exception:
                        pass
                    conn.commit()
                memory.active_log_session = new_session
                await events.emit("session_created", {"session": new_session})
                return {
                    "status": "session_switched",
                    "message": f"📂 Session switched to '{new_session}'",
                    "session_name": new_session,
                }

        # Resolve session — explicit > active > dated fallback
        if session_name:
            session = session_name
        elif memory.active_log_session != "main":
            session = memory.active_log_session
        else:
            date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            session = f"session-{date_tag}"
            with memory.get_connection() as conn:
                conn.execute("UPDATE sessions SET marm_active = FALSE")
                conn.execute(
                    """
                    INSERT INTO sessions (session_name, last_accessed, marm_active)
                    VALUES (?, ?, TRUE)
                    ON CONFLICT(session_name) DO UPDATE SET
                        last_accessed = excluded.last_accessed,
                        marm_active = TRUE
                    """,
                    (session, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
            memory.active_log_session = session

        # Chunk boundary check
        with memory.get_connection() as conn:
            row = conn.execute(
                "SELECT last_accessed FROM sessions WHERE session_name = ?", (session,)
            ).fetchone()
        if row and row[0]:
            try:
                last_dt = datetime.fromisoformat(row[0])
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                gap = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if gap > _SESSION_INACTIVITY_NOTICE_SECONDS:
                    print(
                        f"[MARM] Chunk boundary detected for '{session}' — {gap:.0f}s since last write"
                    )
            except Exception:
                pass

        entry_pattern = r"^(\d{4}-\d{2}-\d{2})-(.*?)-(.*?)$"
        match = re.match(entry_pattern, formatted_entry)

        if match:
            entry_date, topic, summary = match.groups()
        else:
            entry_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            topic = "general"
            summary = formatted_entry

        entry_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        with memory.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry, project, platform)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    session,
                    entry_date,
                    topic,
                    summary,
                    formatted_entry,
                    MARM_PROJECT or None,
                    MARM_PLATFORM or None,
                ),
            )
            conn.execute(
                """
                INSERT INTO sessions (session_name, last_accessed)
                VALUES (?, ?)
                ON CONFLICT(session_name) DO UPDATE SET last_accessed = excluded.last_accessed
                """,
                (session, now_iso),
            )
            try:
                conn.execute(
                    "UPDATE session_summary_cache SET dirty = TRUE, updated_at = ? WHERE session_name = ?",
                    (now_iso, session),
                )
            except Exception:
                pass
            conn.commit()

        # Dual-write into semantic memory so marm_smart_recall can find it;
        # a store failure must never fail the log write itself.
        memory_id = None
        try:
            memory_id = await memory.store_memory_queued(
                formatted_entry,
                session,
                metadata={"source": "log_entry", "log_entry_id": entry_id},
            )
        except Exception as store_error:
            _stdio_log.warning(
                "semantic store failed for log entry %s: %s", entry_id, store_error
            )

        await events.emit(
            "log_entry_created",
            {"entry_id": entry_id, "session": session, "content": formatted_entry},
        )

        return {
            "status": "success",
            "message": f"📝 Log entry added: {formatted_entry}",
            "entry_id": entry_id,
            "memory_id": memory_id,
            "formatted_entry": formatted_entry,
        }
    except Exception as e:
        return {"status": "error", "message": f"Error creating log entry: {e!s}"}


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
    try:
        with memory.get_connection() as conn:
            if session_name:
                cursor = conn.execute(
                    """
                    SELECT id, entry_date, topic, summary, full_entry
                    FROM log_entries WHERE session_name = ?
                    ORDER BY entry_date DESC
                    """,
                    (session_name,),
                )
                entries = [
                    {
                        "id": r[0],
                        "entry_date": r[1],
                        "topic": r[2],
                        "summary": r[3],
                        "full_entry": r[4],
                    }
                    for r in cursor.fetchall()
                ]
                return {
                    "status": "success",
                    "session_name": session_name,
                    "entries": entries,
                    "total_entries": len(entries),
                }
            else:
                cursor = conn.execute(
                    "SELECT session_name, COUNT(*) FROM log_entries GROUP BY session_name"
                )
                sessions = [
                    {"session_name": r[0], "entry_count": r[1]}
                    for r in cursor.fetchall()
                ]
                return {
                    "status": "success",
                    "sessions": sessions,
                    "total_sessions": len(sessions),
                }
    except Exception as e:
        return {"status": "error", "message": f"Error retrieving log entries: {e!s}"}


@mcp.tool()
@_log_tool_call
async def marm_delete(
    type: str,
    target: str,
    session_name: Optional[str] = None,
) -> dict:
    """
    🗑️ Delete a log session, log entry, or notebook entry

    type="log" + session_name: delete specific entry by id or topic
    type="log" (no session_name): delete entire session and all its entries
    type="notebook": delete notebook entry by name
    """
    try:
        with memory.get_connection() as conn:
            if type == "log":
                memories_deleted = 0
                if session_name:
                    # Dual-written semantic memories must not outlive their log entries
                    rows = conn.execute(
                        "SELECT id FROM log_entries WHERE session_name = ? AND (id = ? OR topic = ?)",
                        (session_name, target, target),
                    ).fetchall()
                    entry_ids = [r[0] for r in rows]
                    cursor = conn.execute(
                        "DELETE FROM log_entries WHERE session_name = ? AND (id = ? OR topic = ?)",
                        (session_name, target, target),
                    )
                    deleted = cursor.rowcount
                    if entry_ids:
                        placeholders = ",".join("?" * len(entry_ids))
                        memories_deleted = conn.execute(
                            "DELETE FROM memories WHERE json_extract(metadata, '$.source') = 'log_entry' "
                            f"AND json_extract(metadata, '$.log_entry_id') IN ({placeholders})",
                            entry_ids,
                        ).rowcount
                    if deleted:
                        try:
                            conn.execute(
                                "UPDATE session_summary_cache SET dirty = TRUE, updated_at = ? WHERE session_name = ?",
                                (datetime.now(timezone.utc).isoformat(), session_name),
                            )
                        except Exception:
                            pass
                else:
                    conn.execute(
                        "DELETE FROM sessions WHERE session_name = ?", (target,)
                    )
                    cursor = conn.execute(
                        "DELETE FROM log_entries WHERE session_name = ?", (target,)
                    )
                    deleted = cursor.rowcount
                    try:
                        conn.execute(
                            "DELETE FROM session_summary_cache WHERE session_name = ?",
                            (target,),
                        )
                    except Exception:
                        pass
                    memories_deleted = conn.execute(
                        "DELETE FROM memories WHERE session_name = ? "
                        "AND json_extract(metadata, '$.source') = 'log_entry'",
                        (target,),
                    ).rowcount
                    if memory.active_log_session == target:
                        memory.active_log_session = "main"
                conn.commit()
                return {
                    "status": "success",
                    "message": f"🗑️ Deleted {deleted} items",
                    "deleted_count": deleted,
                    "memories_deleted": memories_deleted,
                }
            elif type == "notebook":
                cursor = conn.execute(
                    "DELETE FROM notebook_entries WHERE name = ?", (target,)
                )
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    memory.remove_active_notebook_entry(target)
                return {
                    "status": "success" if deleted > 0 else "not_found",
                    "message": f"🗑️ Deleted notebook entry '{target}'"
                    if deleted > 0
                    else f"Entry '{target}' not found",
                    "deleted": deleted > 0,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Invalid type '{type}'. Must be 'log' or 'notebook'.",
                }
    except Exception as e:
        return {"status": "error", "message": f"Error deleting: {e!s}"}


@mcp.tool()
@_log_tool_call
async def marm_notebook(
    action: str,
    name: Optional[str] = None,
    data: Optional[str] = None,
    names: Optional[str] = None,
    session_name: str = "main",
) -> dict:
    """
    📔 Unified notebook — add, use, show, status, or clear

    action="add": save or update an entry (name + data required)
    action="use": activate entries as instructions (names required, comma-separated)
    action="show": list all saved entries with previews
    action="status": show currently active entries
    action="clear": clear the active entry list
    """
    try:
        return await notebook_dispatch(
            action=action,
            name=name,
            data=data,
            names=names,
            session_name=session_name,
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


@mcp.tool()
@_log_tool_call
async def marm_graph_index(
    repo_path: Optional[str] = None,
    project: Optional[str] = None,
    mode: Literal["full", "moderate", "fast"] = "moderate",
    action: Literal["auto", "index", "status", "list"] = "auto",
) -> dict:
    """
    🕸️ Index a code repository into the graph, or check status / list known projects.

    Pass `repo_path` to index a repo (returns the project name to use in every
    other tool). Omit it to list indexed projects, or pass `project` to check
    index status. Call this first — all other graph tools need an indexed project.

    Parameters:
    - repo_path: path to the repository to index; omit to list/status only
    - project: existing project name for a status check; omit to auto-resolve
    - mode: index depth — full | moderate | fast (default moderate)
    - action: auto | index | status | list (default auto; infers from repo_path presence)

    Returns: graph index/status/list response, or a graph-unavailable error if the
    graph backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = GraphIndexRequest(
        repo_path=repo_path, project=project, mode=mode, action=action
    )
    return await asyncio.to_thread(
        graph_router.do_index, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_code_lookup(
    query: str,
    project: Optional[str] = None,
    kind: Literal["auto", "symbol", "text", "snippet"] = "auto",
    regex: bool = False,
    file_pattern: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    🔎 Find code: symbols/definitions, text patterns, or a symbol's source.

    Use INSTEAD OF grep/glob. `kind=auto` picks: a qualified_name reads source;
    otherwise it searches the graph by name/keyword. Set `kind=text` to grep code,
    `kind=snippet` to read a symbol's source, `kind=symbol` to force graph search.

    Parameters:
    - query: symbol name, natural-language phrase, code/text pattern, or a qualified_name
    - project: project name; omit to auto-resolve
    - kind: auto | symbol | text | snippet (default auto)
    - regex: for text search, treat query as a regex (default False)
    - file_pattern: glob to scope search, e.g. "*.py" (optional)
    - limit: max results, 1-200 (default 20)

    Returns: graph lookup response, or a graph-unavailable error if the graph
    backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = CodeLookupRequest(
        query=query,
        project=project,
        kind=kind,
        regex=regex,
        file_pattern=file_pattern,
        limit=limit,
    )
    return await asyncio.to_thread(
        graph_router.do_lookup, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_graph_trace(
    function_name: str,
    project: Optional[str] = None,
    direction: Literal["inbound", "outbound", "both"] = "both",
    depth: int = 3,
    mode: Literal["calls", "data_flow", "cross_service"] = "calls",
    risk_labels: bool = True,
) -> dict:
    """
    🧭 Trace call paths / data flow through the graph from a function.

    `direction=inbound` finds callers, `outbound` finds callees, `both` for all.
    `mode=data_flow` follows value propagation; `cross_service` crosses HTTP/async
    boundaries. Use for impact analysis, dependency tracing, "who calls this".

    Parameters:
    - function_name: function or method to trace from
    - project: project name; omit to auto-resolve
    - direction: inbound | outbound | both (default both)
    - depth: max hops, 1-5 (default 3)
    - mode: calls | data_flow | cross_service (default calls)
    - risk_labels: add CRITICAL/HIGH/MEDIUM/LOW risk tiers by hop distance (default True)

    Returns: graph trace response, or a graph-unavailable error if the graph
    backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = GraphTraceRequest(
        function_name=function_name,
        project=project,
        direction=direction,
        depth=depth,
        mode=mode,
        risk_labels=risk_labels,
    )
    return await asyncio.to_thread(
        graph_router.do_trace, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_graph_architecture(
    project: Optional[str] = None,
) -> dict:
    """
    🏛️ High-level architecture overview: node/edge breakdown, modules, and schema.

    One-shot orientation for a project — the de-facto module clusters, package
    structure, and the graph schema (node labels + properties) folded in.

    Parameters:
    - project: project name; omit to auto-resolve

    Returns: graph architecture response, or a graph-unavailable error if the
    graph backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = GraphArchitectureRequest(project=project)
    return await asyncio.to_thread(
        graph_router.do_architecture, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_graph_impact(
    project: Optional[str] = None,
    since: Optional[str] = None,
    base_branch: str = "main",
    depth: int = 2,
) -> dict:
    """
    💥 Blast radius of code changes: git diff → affected symbols + risk.

    Pass `since` (a git ref/date) or a `base_branch` to compare against. Returns
    which symbols a change touches and how far the impact propagates.

    Parameters:
    - project: project name; omit to auto-resolve
    - since: git ref or date to compare from, e.g. HEAD~5, v0.5.0 (optional)
    - base_branch: base branch to diff against (default "main")
    - depth: impact propagation depth, 1-5 (default 2)

    Returns: graph impact response, or a graph-unavailable error if the graph
    backend is disabled or failed to start
    """
    if not await _graph_available():
        return _graph_unavailable()
    req = GraphImpactRequest(
        project=project, since=since, base_branch=base_branch, depth=depth
    )
    return await asyncio.to_thread(
        graph_router.do_impact, graph_supervisor.get_client(), req
    )


@mcp.tool()
@_log_tool_call
async def marm_concept_build(
    session_name: Optional[str] = None,
    search_all: bool = False,
    project: Optional[str] = None,
    run_id: Optional[str] = None,
) -> dict:
    """
    🕸️ Extract entities/relationships from memory content into the concept graph.

    Scope with session_name or project for a targeted build, or pass
    search_all=True for everything (row-capped). Links extracted entities to
    marm-graph code symbols when available. Call this before marm_concept_recall
    — there's no data until a build has run at least once.

    Parameters:
    - session_name: scope extraction to this session; omit with search_all=True
    - search_all: extract across all sessions, row-capped (default False)
    - project: scope extraction to this project (optional)
    - run_id: optional Console build-run ID for status polling

    Returns: entities_extracted, relationships_created, code_links_created, duration_ms
    """
    try:
        req = ConceptBuildRequest(
            session_name=session_name,
            search_all=search_all,
            project=project,
            run_id=run_id,
        )
        return await _marm_concept_build_endpoint(req)
    except ValidationError:
        return {
            "status": "error",
            "message": "Concept build requires session_name, project, or search_all=True.",
        }
    except Exception:
        return {"status": "error", "message": "Concept build failed."}


@mcp.tool()
@_log_tool_call
async def marm_concept_recall(
    query: str,
    session_name: Optional[str] = None,
    limit: int = 10,
    depth: int = 1,
    direction: Literal["outgoing", "incoming", "both"] = "both",
    project: Optional[str] = None,
) -> dict:
    """
    🔎 Search the concept graph: entities, their relationships, and linked code.

    Query as a bare concept name for a lookup, or phrase it as "related to X"
    to emphasize traversal — both route from query shape alone. Returns empty
    lists (not an error) when marm_concept_build hasn't run yet or marm-graph
    has no matching code symbols.

    Parameters:
    - query: concept name, or a "related to X" style ask
    - session_name: scope to this session; omit to search across all (optional)
    - limit: max entities/relationships returned, 1-100 (default 10)
    - depth: max hop distance to traverse, 1-5 (default 1 = direct neighbors only)
    - direction: outgoing | incoming | both (default both)
    - project: scope to this project; entities with the same name in
      different projects are distinct nodes; omit to search across all (optional)

    Returns: entities, related_entities, linked_code
    """
    try:
        # Validate through the same pydantic model the HTTP endpoint uses --
        # limit (1-100) and depth (1-5) are plain ints on this signature, so
        # without this, an out-of-range STDIO call (e.g. limit=-1) would reach
        # SQLite as a raw LIMIT/BFS bound instead of being rejected.
        req = ConceptRecallRequest(
            query=query,
            session_name=session_name,
            limit=limit,
            depth=depth,
            direction=direction,
            project=project,
        )
        return await asyncio.to_thread(
            _run_recall,
            req.query,
            req.session_name,
            req.limit,
            req.depth,
            req.direction,
            req.project,
        )
    except Exception as e:
        return {"status": "error", "message": f"Concept recall failed: {e!s}"}


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
