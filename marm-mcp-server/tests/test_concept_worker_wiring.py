"""Settings parsing and lifecycle wiring for the concept indexing worker.

The worker itself is covered in test_concept_worker.py. What is covered here
is everything around it that a unit test of the worker cannot see: whether the
documented env spellings actually take effect, and whether the two servers
really start and stop it.
"""

import importlib
import sqlite3
import sys

import pytest
from conftest import load_isolated_server


def _reload_settings(monkeypatch, tmp_path, **env):
    """Reload settings with every path it resolves pointed at tmp_path.

    Reload re-executes the module, and module level code resolves the database
    path and can create directories and an API key file. The session HOME
    sandbox in conftest already keeps that out of the developer's real
    ~/.marm, but relying on a distant fixture for that is fragile, so pin the
    paths here too.
    """
    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "settings-probe.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(tmp_path / "marm_index.db"))
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    settings = importlib.import_module("marm_mcp_server.config.settings")
    return importlib.reload(settings)


@pytest.fixture(autouse=True)
def restore_settings():
    yield
    importlib.reload(importlib.import_module("marm_mcp_server.config.settings"))


@pytest.mark.parametrize(
    "value", ["false", "False", "FALSE", "0", "no", "off", " off "]
)
def test_the_documented_off_switches_actually_turn_indexing_off(
    monkeypatch, tmp_path, value
):
    """README and CHANGELOG both tell users CONCEPT_AUTO_INDEX=false. A check
    against a single literal read that as on, which is the opposite of what
    the user asked for."""
    settings = _reload_settings(monkeypatch, tmp_path, CONCEPT_AUTO_INDEX=value)
    assert settings.CONCEPT_AUTO_INDEX is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE"])
def test_the_on_switches_keep_indexing_on(monkeypatch, tmp_path, value):
    settings = _reload_settings(monkeypatch, tmp_path, CONCEPT_AUTO_INDEX=value)
    assert settings.CONCEPT_AUTO_INDEX is True


def test_indexing_is_on_when_the_variable_is_absent(monkeypatch, tmp_path):
    settings = _reload_settings(monkeypatch, tmp_path, CONCEPT_AUTO_INDEX=None)
    assert settings.CONCEPT_AUTO_INDEX is True


def test_an_unparseable_value_falls_back_to_the_default(monkeypatch, tmp_path, capsys):
    settings = _reload_settings(monkeypatch, tmp_path, CONCEPT_AUTO_INDEX="maybe")
    assert settings.CONCEPT_AUTO_INDEX is True
    assert "not a true/false value" in capsys.readouterr().err


def test_batch_size_is_capped_below_sqlites_parameter_ceiling(
    monkeypatch, tmp_path, capsys
):
    """A claimed batch becomes one IN (...) clause in three queries. An
    oversized batch would fail identically on every cycle, forever."""
    settings = _reload_settings(
        monkeypatch, tmp_path, CONCEPT_INDEX_BATCH_SIZE="100000"
    )
    assert settings.CONCEPT_INDEX_BATCH_SIZE == settings.CONCEPT_INDEX_BATCH_SIZE_MAX
    assert settings.CONCEPT_INDEX_BATCH_SIZE < 32766
    assert "clamped" in capsys.readouterr().err


def test_batch_size_still_has_a_floor(monkeypatch, tmp_path):
    settings = _reload_settings(monkeypatch, tmp_path, CONCEPT_INDEX_BATCH_SIZE="0")
    assert settings.CONCEPT_INDEX_BATCH_SIZE == 1


def test_knowledge_status_reports_how_far_behind_indexing_is(monkeypatch, tmp_path):
    """A dormant worker's only other symptom is a graph that quietly stops
    growing. Pending and parked are reported separately because they call for
    different responses."""
    load_isolated_server(monkeypatch, tmp_path)
    runtime_status = importlib.import_module("marm_mcp_server.services.runtime_status")
    concept_queue = importlib.import_module("marm_mcp_server.core.concept_queue")
    mem = sys.modules["marm_mcp_server.core.memory"].memory

    with mem.get_connection() as conn:
        for index, state in enumerate(["pending", "leased", "parked"]):
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp) "
                "VALUES (?, 's', 'c', datetime('now'))",
                (f"m{index}",),
            )
            concept_queue.enqueue(conn, f"m{index}", "h1")
            conn.execute(
                "UPDATE concept_index_queue SET state = ? WHERE memory_id = ?",
                (state, f"m{index}"),
            )

    status = runtime_status.knowledge_status()

    assert status["index_queue"] == {"pending": 2, "parked": 1}
    assert status["auto_index"] is True


def test_knowledge_status_still_reports_when_the_queue_cannot_be_read(
    monkeypatch, tmp_path
):
    """An optional number must not take the whole status command down."""
    load_isolated_server(monkeypatch, tmp_path)
    runtime_status = importlib.import_module("marm_mcp_server.services.runtime_status")
    concept_queue = importlib.import_module("marm_mcp_server.core.concept_queue")

    def explode():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(concept_queue, "counts", explode)

    status = runtime_status.knowledge_status()

    assert status["index_queue"] == {"pending": None, "parked": None}
    assert status["state"] in (
        "ready",
        "ready_no_build",
        "missing_spacy",
        "missing_model",
    )


@pytest.mark.asyncio
async def test_http_shutdown_stops_the_worker_before_the_write_queue(
    monkeypatch, tmp_path
):
    """Order matters: the worker produces concept writes and reads the memory
    DB, so it has to be stopped before the pools start closing."""
    load_isolated_server(monkeypatch, tmp_path)
    shutdown_module = importlib.import_module("marm_mcp_server.core.shutdown_manager")
    memory_module = sys.modules["marm_mcp_server.core.memory"]

    order = []

    async def record_worker_stop():
        order.append("worker")

    async def record_queue_stop():
        order.append("write_queue")

    monkeypatch.setattr(shutdown_module.concept_worker, "stop", record_worker_stop)
    monkeypatch.setattr(memory_module.memory, "stop_write_queue", record_queue_stop)

    await shutdown_module.ShutdownManager().graceful_shutdown()

    assert order[:2] == ["worker", "write_queue"]


@pytest.mark.asyncio
async def test_http_shutdown_survives_a_worker_that_fails_to_stop(
    monkeypatch, tmp_path
):
    """A broken optional subsystem must not strand the write queue."""
    load_isolated_server(monkeypatch, tmp_path)
    shutdown_module = importlib.import_module("marm_mcp_server.core.shutdown_manager")
    memory_module = sys.modules["marm_mcp_server.core.memory"]

    stopped = []

    async def explode():
        raise RuntimeError("worker stop failed")

    async def record_queue_stop():
        stopped.append("write_queue")

    monkeypatch.setattr(shutdown_module.concept_worker, "stop", explode)
    monkeypatch.setattr(memory_module.memory, "stop_write_queue", record_queue_stop)

    await shutdown_module.ShutdownManager().graceful_shutdown()

    assert stopped == ["write_queue"]


@pytest.mark.asyncio
async def test_stdio_lifespan_starts_and_stops_the_worker(monkeypatch, tmp_path):
    """A STDIO session lives as long as its host application, which is long
    enough for the worker to matter, and its teardown is shielded and bounded."""
    load_isolated_server(monkeypatch, tmp_path)
    stdio = importlib.import_module("marm_mcp_server.server_stdio")
    memory_module = sys.modules["marm_mcp_server.core.memory"]

    events = []

    def record_start():
        events.append("start")

    async def record_stop():
        events.append("stop")

    async def noop_queue_stop():
        return None

    monkeypatch.setattr(stdio.concept_worker, "start", record_start)
    monkeypatch.setattr(stdio.concept_worker, "stop", record_stop)
    monkeypatch.setattr(memory_module.memory, "stop_write_queue", noop_queue_stop)

    async with stdio._stdio_lifespan(None):
        assert events == ["start"]

    assert events == ["start", "stop"]


@pytest.mark.asyncio
async def test_stdio_teardown_still_stops_the_worker_after_a_crashed_session(
    monkeypatch, tmp_path
):
    """The teardown sits in a finally precisely because a session that died is
    when unfinished work is most likely."""
    load_isolated_server(monkeypatch, tmp_path)
    stdio = importlib.import_module("marm_mcp_server.server_stdio")
    memory_module = sys.modules["marm_mcp_server.core.memory"]

    events = []

    async def record_stop():
        events.append("stop")

    async def noop_queue_stop():
        return None

    monkeypatch.setattr(stdio.concept_worker, "start", lambda: None)
    monkeypatch.setattr(stdio.concept_worker, "stop", record_stop)
    monkeypatch.setattr(memory_module.memory, "stop_write_queue", noop_queue_stop)

    with pytest.raises(RuntimeError, match="session died"):
        async with stdio._stdio_lifespan(None):
            raise RuntimeError("session died")

    assert events == ["stop"]
