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
    assert settings_mod.COMPACTION_TRIGGER_COUNT == 5


def test_malformed_float_env_falls_back_to_default():
    """Malformed float env var should fall back to default, not crash."""
    settings_mod = _reload_settings_with_env(
        {"CONSOLIDATION_THRESHOLD": "not_a_number"}
    )
    assert settings_mod.CONSOLIDATION_THRESHOLD == 0.92


def test_consolidation_threshold_clamped_to_unit_range():
    """CONSOLIDATION_THRESHOLD > 1.0 should be clamped to [0, 1]."""
    settings_mod = _reload_settings_with_env({"CONSOLIDATION_THRESHOLD": "1.5"})
    assert settings_mod.CONSOLIDATION_THRESHOLD == 1.0


def test_resolve_marm_api_key_persists_a_generated_key_across_starts(
    monkeypatch, tmp_path
):
    """A real generated key must round-trip through resolve_marm_api_key's
    persist-then-reload path exactly: the first 0.0.0.0 start with no key
    anywhere generates and saves one, and every start after that must load
    the same key back rather than generating a new one each time."""
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_protect_key_file", lambda path: True)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    first_start = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")
    assert first_start
    assert env_path.read_text() == f"MARM_API_KEY={first_start}\n"

    second_start = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")
    assert second_start == first_start


def test_resolve_marm_api_key_removes_file_when_protection_fails(
    monkeypatch, tmp_path, capsys
):
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_protect_key_file", lambda path: False)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key
    assert not env_path.exists()
    warning = capsys.readouterr().err
    assert "kept in memory only" in warning
    assert "will not survive a restart" in warning
    assert "Set MARM_API_KEY explicitly in the environment" in warning


def test_resolve_marm_api_key_warns_when_insecure_file_cannot_be_removed(
    monkeypatch, tmp_path, capsys
):
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_protect_key_file", lambda path: False)

    def fail_unlink(self, missing_ok=False):
        raise OSError("denied")

    monkeypatch.setattr(type(env_path), "unlink", fail_unlink)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key
    assert env_path.exists()
    warning = capsys.readouterr().err
    assert "insecure file could not be removed" in warning
    assert str(env_path) in warning
    assert "memory for this process only" in warning
    assert "Set MARM_API_KEY explicitly in the environment" in warning
