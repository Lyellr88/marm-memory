"""Tests for config safety: clamping, warnings, and safe parsing."""

import importlib
import os
import sys
from unittest import mock


def _reload_settings_with_env(env: dict[str, str]):
    """Reload settings under a temporary env patch, then restore the original module."""
    module_name = "marm_mcp_server.config.settings"
    original = sys.modules.pop(module_name, None)

    try:
        with mock.patch.dict(os.environ, env, clear=False):
            settings_mod = importlib.import_module(module_name)
            return importlib.reload(settings_mod)
    finally:
        sys.modules.pop(module_name, None)
        if original is not None:
            sys.modules[module_name] = original


def test_rate_limit_rpm_zero_disables_limiting():
    """MARM_RATE_LIMIT_RPM=0 should be preserved (0 = disable rate limiting)."""
    settings_mod = _reload_settings_with_env({"MARM_RATE_LIMIT_RPM": "0"})
    assert settings_mod.MARM_RATE_LIMIT_RPM == 0


def test_rate_limit_rpm_negative_clamped_to_zero():
    """Negative MARM_RATE_LIMIT_RPM should be clamped to 0 with a warning."""
    settings_mod = _reload_settings_with_env({"MARM_RATE_LIMIT_RPM": "-5"})
    assert settings_mod.MARM_RATE_LIMIT_RPM == 0


def test_malformed_int_env_falls_back_to_default():
    """Malformed int env var should fall back to default, not crash."""
    settings_mod = _reload_settings_with_env({"COMPACTION_TRIGGER_COUNT": "abc"})
    assert settings_mod.COMPACTION_TRIGGER_COUNT == 5  # default


def test_malformed_float_env_falls_back_to_default():
    """Malformed float env var should fall back to default, not crash."""
    settings_mod = _reload_settings_with_env(
        {"CONSOLIDATION_THRESHOLD": "not_a_number"}
    )
    assert settings_mod.CONSOLIDATION_THRESHOLD == 0.92  # default


def test_consolidation_threshold_clamped_to_unit_range():
    """CONSOLIDATION_THRESHOLD > 1.0 should be clamped to [0, 1]."""
    settings_mod = _reload_settings_with_env({"CONSOLIDATION_THRESHOLD": "1.5"})
    assert settings_mod.CONSOLIDATION_THRESHOLD == 1.0
