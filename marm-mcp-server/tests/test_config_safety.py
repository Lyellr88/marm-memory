"""Tests for config safety: clamping, warnings, and safe parsing."""

import os
import sys
from unittest import mock


def test_rate_limit_rpm_zero_disables_limiting():
    """MARM_RATE_LIMIT_RPM=0 should be preserved (0 = disable rate limiting)."""
    with mock.patch.dict(os.environ, {"MARM_RATE_LIMIT_RPM": "0"}):
        # Re-import to pick up the env var
        import importlib
        import marm_mcp_server.config.settings as settings_mod

        importlib.reload(settings_mod)
        assert settings_mod.MARM_RATE_LIMIT_RPM == 0


def test_rate_limit_rpm_negative_clamped_to_zero():
    """Negative MARM_RATE_LIMIT_RPM should be clamped to 0 with a warning."""
    with mock.patch.dict(os.environ, {"MARM_RATE_LIMIT_RPM": "-5"}):
        import importlib
        import marm_mcp_server.config.settings as settings_mod

        importlib.reload(settings_mod)
        assert settings_mod.MARM_RATE_LIMIT_RPM == 0


def test_malformed_int_env_falls_back_to_default():
    """Malformed int env var should fall back to default, not crash."""
    with mock.patch.dict(os.environ, {"COMPACTION_TRIGGER_COUNT": "abc"}):
        import importlib
        import marm_mcp_server.config.settings as settings_mod

        importlib.reload(settings_mod)
        assert settings_mod.COMPACTION_TRIGGER_COUNT == 5  # default


def test_malformed_float_env_falls_back_to_default():
    """Malformed float env var should fall back to default, not crash."""
    with mock.patch.dict(os.environ, {"CONSOLIDATION_THRESHOLD": "not_a_number"}):
        import importlib
        import marm_mcp_server.config.settings as settings_mod

        importlib.reload(settings_mod)
        assert settings_mod.CONSOLIDATION_THRESHOLD == 0.92  # default


def test_consolidation_threshold_clamped_to_unit_range():
    """CONSOLIDATION_THRESHOLD > 1.0 should be clamped to [0, 1]."""
    with mock.patch.dict(os.environ, {"CONSOLIDATION_THRESHOLD": "1.5"}):
        import importlib
        import marm_mcp_server.config.settings as settings_mod

        importlib.reload(settings_mod)
        assert settings_mod.CONSOLIDATION_THRESHOLD == 1.0
