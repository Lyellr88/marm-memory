"""Tests for marm_mcp_server/core/events.py changes in this PR.

Covers:
- get_health_status() was removed — verify it no longer exists
- emit() still invokes registered callbacks
- emit() with no listeners completes silently
- emit() error-isolates failed callbacks so other callbacks still run
- failure count tracking via failed_callbacks dict
- _log_callback_error escalation (warning -> error -> critical)
"""

import asyncio
import sys

import pytest


@pytest.fixture
def isolated_events(monkeypatch, tmp_path):
    """Return a fresh MARMEvents instance with no shared state."""
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            del sys.modules[name]

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "events-test.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "events-analytics.db"))

    from marm_mcp_server.core.events import MARMEvents

    return MARMEvents()


# ---------------------------------------------------------------------------
# Removal regression
# ---------------------------------------------------------------------------

def test_get_health_status_method_was_removed(isolated_events):
    """get_health_status() was deleted in this PR and must not exist."""
    assert not hasattr(isolated_events, "get_health_status"), (
        "get_health_status() must be removed from MARMEvents"
    )


# ---------------------------------------------------------------------------
# emit() — basic behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emit_calls_registered_callback(isolated_events):
    received = []

    async def handler(data):
        received.append(data)

    isolated_events.on("test_event", handler)
    await isolated_events.emit("test_event", {"key": "value"})

    assert received == [{"key": "value"}]


@pytest.mark.asyncio
async def test_emit_with_no_listeners_is_silent(isolated_events):
    # Should complete without exception even when nothing is registered.
    await isolated_events.emit("unregistered_event", {"irrelevant": True})


@pytest.mark.asyncio
async def test_emit_calls_multiple_callbacks_in_order(isolated_events):
    order = []

    async def first(data):
        order.append("first")

    async def second(data):
        order.append("second")

    isolated_events.on("ordered_event", first)
    isolated_events.on("ordered_event", second)
    await isolated_events.emit("ordered_event", {})

    assert order == ["first", "second"]


# ---------------------------------------------------------------------------
# emit() — error isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emit_error_in_one_callback_does_not_prevent_others(isolated_events):
    """A callback that raises must not block subsequent callbacks."""
    results = []

    async def bad_handler(data):
        raise RuntimeError("intentional failure")

    async def good_handler(data):
        results.append("ok")

    isolated_events.on("mixed_event", bad_handler)
    isolated_events.on("mixed_event", good_handler)
    await isolated_events.emit("mixed_event", {})

    assert results == ["ok"]


@pytest.mark.asyncio
async def test_emit_failed_callback_is_tracked_in_failed_callbacks(isolated_events):
    async def failing(data):
        raise ValueError("boom")

    isolated_events.on("fail_event", failing)
    await isolated_events.emit("fail_event", {})

    # At least one entry should have been added for the failing callback
    assert len(isolated_events.failed_callbacks) == 1
    count = next(iter(isolated_events.failed_callbacks.values()))
    assert count == 1


@pytest.mark.asyncio
async def test_emit_failure_count_increments_on_repeated_failures(isolated_events):
    async def always_fails(data):
        raise RuntimeError("persistent error")

    isolated_events.on("repeat_fail", always_fails)

    for _ in range(3):
        await isolated_events.emit("repeat_fail", {})

    count = next(iter(isolated_events.failed_callbacks.values()))
    assert count == 3


@pytest.mark.asyncio
async def test_emit_success_resets_failure_count(isolated_events):
    """A successful invocation should remove the callback from failed_callbacks."""
    call_count = [0]

    async def sometimes_fails(data):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("first call fails")
        # Second call succeeds

    isolated_events.on("recovery_event", sometimes_fails)

    await isolated_events.emit("recovery_event", {})
    assert len(isolated_events.failed_callbacks) == 1  # tracked after failure

    await isolated_events.emit("recovery_event", {})
    assert len(isolated_events.failed_callbacks) == 0  # cleared after success


# ---------------------------------------------------------------------------
# _log_callback_error — failure escalation
# ---------------------------------------------------------------------------

def test_log_callback_error_records_first_failure_as_warning(isolated_events):
    import logging

    with pytest.raises(AssertionError):
        pass  # just to confirm pytest is running

    log_records = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            log_records.append(record)

    handler = CapturingHandler()
    isolated_events.logger.addHandler(handler)
    isolated_events.logger.setLevel(logging.DEBUG)

    isolated_events._log_callback_error("cb_1", "something broke", "test_event")

    assert any(r.levelno == logging.WARNING for r in log_records)
    assert isolated_events.failed_callbacks["cb_1"] == 1


def test_log_callback_error_escalates_to_error_on_repeated_failures(isolated_events):
    import logging

    log_records = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            log_records.append(record)

    handler = CapturingHandler()
    isolated_events.logger.addHandler(handler)
    isolated_events.logger.setLevel(logging.DEBUG)

    for i in range(3):
        isolated_events._log_callback_error("cb_repeat", "still broken", "test_event")

    # Third failure → ERROR level
    error_records = [r for r in log_records if r.levelno >= logging.ERROR]
    assert len(error_records) >= 1
    assert isolated_events.failed_callbacks["cb_repeat"] == 3


def test_log_callback_error_escalates_to_critical_after_five_failures(isolated_events):
    import logging

    log_records = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            log_records.append(record)

    handler = CapturingHandler()
    isolated_events.logger.addHandler(handler)
    isolated_events.logger.setLevel(logging.DEBUG)

    for _ in range(6):
        isolated_events._log_callback_error("cb_critical", "always failing", "evt")

    critical_records = [r for r in log_records if r.levelno == logging.CRITICAL]
    assert len(critical_records) >= 1