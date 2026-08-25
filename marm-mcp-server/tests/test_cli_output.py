from marm_mcp_server.services.cli_output import _format_size, _queue_state


def test_format_size_none_is_unknown():
    assert _format_size(None) == "unknown"


def test_format_size_stays_in_bytes_under_1024():
    assert _format_size(512) == "512.0 B"


def test_format_size_converts_to_kb():
    assert _format_size(2048) == "2.0 KB"


def test_format_size_converts_to_mb():
    assert _format_size(5 * 1024 * 1024) == "5.0 MB"


def test_format_size_caps_at_gb_for_very_large_values():
    huge = 3 * 1024 * 1024 * 1024 * 1024
    result = _format_size(huge)
    assert result.endswith(" GB")
    assert float(result.split()[0]) == huge / (1024**3)


def test_queue_state_disabled_when_not_enabled():
    assert _queue_state({"enabled": False, "running": True}) == "disabled"


def test_queue_state_stopping_takes_priority_over_running():
    assert _queue_state({"enabled": True, "running": True, "stopping": True}) == (
        "stopping"
    )


def test_queue_state_healthy_when_running():
    assert _queue_state({"enabled": True, "running": True}) == "healthy"


def test_queue_state_starting_when_not_yet_running():
    assert _queue_state({"enabled": True, "running": False}) == "starting"


def test_queue_state_defaults_enabled_true_when_key_missing():
    assert _queue_state({"running": True}) == "healthy"
