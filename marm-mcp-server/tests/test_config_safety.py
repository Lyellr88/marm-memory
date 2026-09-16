import importlib
import os
import stat
import sys
from unittest import mock

import pytest


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
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    first_start = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")
    assert first_start
    assert env_path.read_text() == f"MARM_API_KEY={first_start}\n"
    if os.name != "nt":
        assert stat.S_IMODE(env_path.stat().st_mode) & 0o077 == 0

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
    printed = []
    real_print = print

    def record_print(*args, **kwargs):
        printed.append(args)
        real_print(*args, **kwargs)

    monkeypatch.setattr("builtins.print", record_print)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key
    assert not env_path.exists()
    output = capsys.readouterr()
    warning = output.err
    assert "kept in memory only" in warning
    assert "will not survive a restart" in warning
    assert "Set MARM_API_KEY explicitly in the environment" in warning
    assert ("Set MARM_API_KEY explicitly and restart to connect.",) in printed


def test_resolve_marm_api_key_removes_file_when_protection_raises(
    monkeypatch, tmp_path, capsys
):
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)

    def fail_protection(path):
        raise RuntimeError("ctypes blew up")

    monkeypatch.setattr(api_key_bootstrap, "_protect_key_file", fail_protection)
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_generated_key_file_is_created_owner_only_before_any_chmod(
    monkeypatch, tmp_path
):
    """The key file must be owner-only from creation, not from the chmod after it.

    `_protect_key_file` is neutralised to a no-op that reports success, so the
    only thing that can make the mode 0600 here is how the file was created. If
    creation still goes through the process umask, this fails.
    """
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_protect_key_file", lambda path: True)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_generated_key_file_is_not_world_readable_under_a_permissive_umask(
    monkeypatch, tmp_path
):
    """umask 0 is the worst case: `Path.write_text()` would create this 0666,
    publishing the bearer token to every local user until the chmod lands."""
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_protect_key_file", lambda path: True)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    previous_umask = os.umask(0)
    try:
        generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")
    finally:
        os.umask(previous_umask)

    assert generated_key
    assert stat.S_IMODE(env_path.stat().st_mode) & 0o077 == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_an_existing_insecure_key_file_is_hardened_BEFORE_the_secret_is_written(
    monkeypatch, tmp_path
):
    """The mode must be fixed before the new token reaches the file.

    `O_CREAT` does not re-mode a file that already exists, so an existing 0644
    `~/.marm/.env` would otherwise receive the new bearer token while still
    world-readable, and only be hardened afterwards. That is the same exposure
    as the new-file case on a path whose end state looks correct.

    Captured by recording the mode at the moment the file is opened for
    writing, rather than by inspecting it once everything has finished.
    """
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("MARM_API_KEY=stale-value-that-is-long-enough\n")
    env_path.chmod(0o644)
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_load_key_from_file", lambda: "")
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    modes_at_open = []
    real_open = os.open

    def record_mode(path, flags, mode=0o777, *args, **kwargs):
        if str(path) == str(env_path) and os.path.exists(path):
            modes_at_open.append(stat.S_IMODE(os.stat(path).st_mode))
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", record_mode)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key
    assert modes_at_open, "the key file was never opened"
    assert modes_at_open[0] & 0o077 == 0, (
        f"secret written into a file still at {modes_at_open[0]:#o}"
    )
    assert env_path.read_text() == f"MARM_API_KEY={generated_key}\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_existing_insecure_key_file_is_overwritten_and_hardened(monkeypatch, tmp_path):
    """End state: content replaced and mode owner-only."""
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("MARM_API_KEY=stale-value-that-is-long-enough\n")
    env_path.chmod(0o644)
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_load_key_from_file", lambda: "")
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key
    assert env_path.read_text() == f"MARM_API_KEY={generated_key}\n"
    assert stat.S_IMODE(env_path.stat().st_mode) & 0o077 == 0


def test_key_file_creation_failure_is_reported_and_leaves_no_file(
    monkeypatch, tmp_path, capsys
):
    """A failure opening the file must not crash startup, and must not leave a
    partially written credential behind."""
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    real_open = os.open

    def refuse_key_file(path, flags, mode=0o777, *args, **kwargs):
        if str(path) == str(env_path):
            raise OSError(13, "Permission denied")
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", refuse_key_file)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key  # still usable in memory for this process
    assert not env_path.exists()
    # Assert on both streams: which one the warning lands on is not part of the
    # contract, and under the full suite stdout is not always the process's own.
    captured = capsys.readouterr()
    assert "Could not save API key" in (captured.out + captured.err)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory modes")
def test_key_directory_is_owner_only_even_under_a_permissive_umask(
    monkeypatch, tmp_path
):
    """`~/.marm` must not be world-writable.

    `mkdir(parents=True, exist_ok=True)` uses `0o777 & ~umask`, so under
    `umask 0` it is created `0o777`. Another local user could then swap `.env`
    between hardening and opening it, and `os.open`'s mode only applies when it
    creates the file, so their file would keep its own mode and receive the key.
    """
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / "home" / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    previous_umask = os.umask(0)
    try:
        generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")
    finally:
        os.umask(previous_umask)

    assert generated_key
    assert stat.S_IMODE(env_path.parent.stat().st_mode) & 0o077 == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory modes")
def test_an_existing_world_writable_key_directory_is_tightened(monkeypatch, tmp_path):
    """A mode passed to `mkdir` applies only on creation, so a directory that
    already exists permissively has to be fixed explicitly."""
    from marm_mcp_server.config import api_key_bootstrap

    marm_dir = tmp_path / ".marm"
    marm_dir.mkdir()
    marm_dir.chmod(0o777)
    env_path = marm_dir / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key
    assert stat.S_IMODE(marm_dir.stat().st_mode) & 0o077 == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_a_symlinked_key_file_is_refused_rather_than_followed(monkeypatch, tmp_path):
    """Writing through a link would put the token wherever the link points."""
    from marm_mcp_server.config import api_key_bootstrap

    marm_dir = tmp_path / ".marm"
    marm_dir.mkdir()
    target = tmp_path / "attacker-owned"
    target.write_text("")
    target.chmod(0o666)
    env_path = marm_dir / ".env"
    env_path.symlink_to(target)

    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_load_key_from_file", lambda: "")
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    # Startup still succeeds with an in-memory key; the secret never lands.
    assert generated_key
    assert target.read_text() == ""
    assert generated_key not in target.read_text()
