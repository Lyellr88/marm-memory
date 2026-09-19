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

    `project` is unbounded over STDIO and on every other project-scoped model
    in `core/models.py`; the one payload that bounds it -- the Console memory
    payload -- uses 255. A tighter limit on this one model would reject over
    HTTP a scope the same caller can use everywhere else, which is the kind of
    difference nobody discovers until a real project name is long.
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
