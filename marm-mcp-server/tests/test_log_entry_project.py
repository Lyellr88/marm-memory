"""`marm_log_entry` must accept an explicit project, on both transports.

Without one, every logged memory is attributed to `MARM_PROJECT`, which
`_detect_project()` derives from the SERVER process's working directory. On a
shared HTTP runtime that is the server's directory, not the caller's, so
project-scoped recall misses or misattributes the entry (issue #214).

The parity tests are the point: the two transports must agree, and a log written
with an explicit project must be retrievable under that project scope.
"""

import importlib

import pytest
from conftest import load_isolated_server

SCOPE = "a-caller-chosen-project"


def _rows(memory, table, column="project"):
    with memory.get_connection() as conn:
        return [r[0] for r in conn.execute(f"SELECT {column} FROM {table}").fetchall()]


@pytest.mark.asyncio
async def test_an_explicit_project_reaches_the_log_row_and_the_memory(
    monkeypatch, tmp_path
):
    """The column, not the metadata blob: scoped recall reads the column."""
    load_isolated_server(monkeypatch, tmp_path)
    log_entry = importlib.import_module("marm_mcp_server.services.log_entry")
    memory = importlib.import_module("marm_mcp_server.core.memory").memory

    result = await log_entry.create_log_entry(
        "2026-01-02-topic-a durable fact worth keeping",
        "sess-http",
        project=SCOPE,
    )

    assert result["status"] != "error", result
    assert _rows(memory, "log_entries") == [SCOPE]
    assert _rows(memory, "memories") == [SCOPE]


@pytest.mark.asyncio
async def test_omitting_the_project_keeps_the_detected_fallback(monkeypatch, tmp_path):
    """The current behaviour must survive: omitted means detected, not NULL."""
    load_isolated_server(monkeypatch, tmp_path)
    log_entry = importlib.import_module("marm_mcp_server.services.log_entry")
    memory = importlib.import_module("marm_mcp_server.core.memory").memory
    settings = importlib.import_module("marm_mcp_server.config.settings")

    await log_entry.create_log_entry("2026-01-02-topic-no scope given", "sess-default")

    assert _rows(memory, "log_entries") == [settings.MARM_PROJECT or None]


@pytest.mark.asyncio
async def test_the_session_switch_path_carries_the_project_too(monkeypatch, tmp_path):
    """`Session: name` writes its own marker row through a separate INSERT.

    That branch returns early, so it is the one a change to the normal path
    silently misses.
    """
    load_isolated_server(monkeypatch, tmp_path)
    log_entry = importlib.import_module("marm_mcp_server.services.log_entry")
    memory = importlib.import_module("marm_mcp_server.core.memory").memory

    result = await log_entry.create_log_entry(
        "Session: launch-review", None, project=SCOPE
    )

    assert result["status"] == "session_switched", result
    assert _rows(memory, "log_entries") == [SCOPE]


def test_both_transports_expose_project(monkeypatch, tmp_path):
    """HTTP and STDIO must offer the same parameter, or the same call scopes
    differently depending on which transport a client happens to use."""
    load_isolated_server(monkeypatch, tmp_path)
    models = importlib.import_module("marm_mcp_server.core.models")
    assert "project" in models.LogEntryRequest.model_fields, "HTTP request model"

    import inspect

    stdio = importlib.import_module("marm_mcp_server.server_stdio")
    assert "project" in inspect.signature(stdio.marm_log_entry).parameters, "STDIO tool"


@pytest.mark.asyncio
async def test_a_scoped_entry_is_retrievable_under_that_scope(monkeypatch, tmp_path):
    """The whole point of the change: scoped recall must find it."""
    load_isolated_server(monkeypatch, tmp_path)
    log_entry = importlib.import_module("marm_mcp_server.services.log_entry")
    memory = importlib.import_module("marm_mcp_server.core.memory").memory

    await log_entry.create_log_entry(
        "2026-01-02-topic-scoped and findable", "sess-scoped", project=SCOPE
    )
    await log_entry.create_log_entry(
        "2026-01-02-topic-a different scope entirely", "sess-other", project="elsewhere"
    )

    with memory.get_connection() as conn:
        found = conn.execute(
            "SELECT content FROM memories WHERE project = ?", (SCOPE,)
        ).fetchall()
    assert len(found) == 1, f"scoped recall returned {len(found)} rows"
    assert "scoped and findable" in found[0][0]


@pytest.mark.asyncio
async def test_the_scope_survives_the_write_queue(monkeypatch, tmp_path):
    """The queued path is the one the server actually uses.

    `_store_memory` always accepted `project`/`explicit_scope`; the queue did
    not forward them, so the scope was dropped between the caller and the row
    exactly when the write queue was enabled -- which is the default.
    """
    load_isolated_server(monkeypatch, tmp_path, write_queue_enabled=True)
    log_entry = importlib.import_module("marm_mcp_server.services.log_entry")
    memory = importlib.import_module("marm_mcp_server.core.memory").memory

    await log_entry.create_log_entry(
        "2026-01-02-topic-through the queue", "sess-queued", project=SCOPE
    )
    try:
        assert _rows(memory, "memories") == [SCOPE]
        assert _rows(memory, "log_entries") == [SCOPE]
    finally:
        await memory.stop_write_queue()


def test_the_http_project_bound_matches_the_other_project_routes():
    """A bound that is stricter here than elsewhere is a transport divergence.

    The one other payload that bounds `project` -- the Console memory payload
    -- uses 255. A tighter limit on this model would reject a scope the same
    caller can use elsewhere, which is the kind of difference nobody discovers
    until a real project name is long. The transports share this model; see
    `test_the_project_bound_is_the_same_on_both_transports`.
    """
    from marm_mcp_server.core.models import LogEntryRequest
    from marm_mcp_server.endpoints.memory import ConsoleMemoryPayload

    def bound(model, field):
        return next(
            m.max_length
            for m in model.model_fields[field].metadata
            if getattr(m, "max_length", None) is not None
        )

    assert bound(LogEntryRequest, "project") == bound(ConsoleMemoryPayload, "project")


# --- review round: platform, transport parity, and recall through the transports


PLATFORM = "claude-code"
FACT = "2026-01-02-topic-the quartz relay governs failover"
OTHER = "2026-01-02-topic-the quartz relay governs failover elsewhere too"
QUERY = "quartz relay failover"


def _recalled(results):
    return sorted((r.get("project"), r.get("platform")) for r in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True], ids=["direct", "write-queue"])
async def test_an_explicit_project_keeps_the_detected_platform(
    monkeypatch, tmp_path, queued
):
    """An explicit project must not strip the platform the log row records, or
    a recall filtered by project AND platform misses the entry."""
    monkeypatch.setenv("MARM_PLATFORM", PLATFORM)
    load_isolated_server(monkeypatch, tmp_path, write_queue_enabled=queued)
    log_entry = importlib.import_module("marm_mcp_server.services.log_entry")
    memory = importlib.import_module("marm_mcp_server.core.memory").memory
    recall = importlib.import_module("marm_mcp_server.services.recall")

    try:
        await log_entry.create_log_entry(FACT, "sess-a", project=SCOPE)
        assert _rows(memory, "log_entries", "platform") == [PLATFORM]
        assert _rows(memory, "memories", "platform") == [PLATFORM]

        out = await recall.smart_recall(
            QUERY, search_all=True, project=SCOPE, platform=PLATFORM
        )
        assert _recalled(out["results"]) == [(SCOPE, PLATFORM)]
    finally:
        if queued:
            await memory.stop_write_queue()


def test_http_log_entry_scope_is_what_recall_filters_on(monkeypatch, tmp_path):
    """Through the HTTP routes themselves: write two scopes, recall one."""
    from conftest import local_client

    client = local_client(load_isolated_server(monkeypatch, tmp_path).app)
    for entry, scope in ((FACT, SCOPE), (OTHER, "another-project")):
        written = client.post(
            "/marm_log_entry",
            json={"entry": entry, "session_name": "sess-h", "project": scope},
        )
        assert written.status_code == 200, written.text

    body = client.post(
        "/marm_smart_recall",
        json={"query": QUERY, "search_all": True, "project": SCOPE},
    ).json()
    assert [r["project"] for r in body["results"]] == [SCOPE]


def _stdio_call(monkeypatch, tmp_path, calls):
    """Run tool calls through an in-process STDIO client session."""
    import asyncio
    import json

    from mcp.shared.memory import create_connected_server_and_client_session
    from test_stdio_transport import _isolated_stdio

    stdio = _isolated_stdio(monkeypatch, tmp_path)
    # Recall reads the store through its own module reference.
    monkeypatch.setattr(
        importlib.import_module("marm_mcp_server.services.recall"),
        "memory",
        stdio.memory,
    )

    async def run():
        out = []
        async with create_connected_server_and_client_session(stdio.mcp) as client:
            for name, args in calls:
                result = await client.call_tool(name, args)
                out.append(json.loads(result.content[0].text))
        return out

    return asyncio.run(run()), stdio.memory


def test_stdio_log_entry_scope_is_what_recall_filters_on(monkeypatch, tmp_path):
    results, _ = _stdio_call(
        monkeypatch,
        tmp_path,
        [
            ("marm_log_entry", {"entry": FACT, "session_name": "s", "project": SCOPE}),
            (
                "marm_log_entry",
                {"entry": OTHER, "session_name": "s", "project": "another-project"},
            ),
            (
                "marm_smart_recall",
                {"query": QUERY, "search_all": True, "project": SCOPE},
            ),
        ],
    )
    assert [r["project"] for r in results[-1]["results"]] == [SCOPE]


def test_the_project_bound_is_the_same_on_both_transports(monkeypatch, tmp_path):
    """HTTP rejected a 256-character project that STDIO accepted, so one call
    scoped or failed depending on the transport it happened to use."""
    from conftest import local_client

    too_long, longest = "p" * 256, "p" * 255

    client = local_client(load_isolated_server(monkeypatch, tmp_path).app)
    http = client.post(
        "/marm_log_entry",
        json={"entry": FACT, "session_name": "h", "project": too_long},
    )
    assert http.status_code == 422

    stdio_dir = tmp_path / "stdio"
    stdio_dir.mkdir()
    results, memory = _stdio_call(
        monkeypatch,
        stdio_dir,
        [
            (
                "marm_log_entry",
                {"entry": FACT, "session_name": "s", "project": too_long},
            ),
            (
                "marm_log_entry",
                {"entry": FACT, "session_name": "s", "project": longest},
            ),
        ],
    )
    assert results[0]["status"] == "error"
    assert results[1]["status"] != "error", results[1]
    assert _rows(memory, "log_entries") == [longest], "only the valid call wrote"
