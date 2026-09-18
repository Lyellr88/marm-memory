import importlib
import os
import stat
import sys
from pathlib import Path
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

    # Protection must SUCCEED on the temporary file and fail on the final one.
    # A blanket False would now fail before the rename, where there is no file
    # to remove and therefore no "could not be removed" case to reach.
    def protect(path):
        return str(path) != str(env_path)

    monkeypatch.setattr(api_key_bootstrap, "_protect_key_file", protect)

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
def test_the_secret_is_never_written_into_a_file_others_can_read(monkeypatch, tmp_path):
    """The token must never exist on disk readable by anyone but its owner.

    Checks the property, not the path: every file opened for writing is
    owner-only at the instant it is opened, and a pre-existing 0644 file is
    replaced rather than written through.
    """
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("MARM_API_KEY=stale-value-that-is-long-enough\n")
    env_path.chmod(0o644)
    stale_inode = env_path.stat().st_ino
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_load_key_from_file", lambda: "")
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    opened_for_write = []
    real_open = os.open

    def record(path, flags, mode=0o777, *args, **kwargs):
        descriptor = real_open(path, flags, mode, *args, **kwargs)
        if flags & (os.O_WRONLY | os.O_RDWR):
            opened_for_write.append(
                (str(path), stat.S_IMODE(os.fstat(descriptor).st_mode))
            )
        return descriptor

    monkeypatch.setattr(os, "open", record)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key
    assert opened_for_write, "nothing was ever opened for writing"
    for opened_path, mode in opened_for_write:
        assert mode & 0o077 == 0, f"secret written into {opened_path} at {mode:#o}"
    assert str(env_path) not in [p for p, _ in opened_for_write], (
        "the credential was written through the real path, which a symlink "
        "swapped in after the checks would have redirected"
    )
    assert env_path.read_text() == f"MARM_API_KEY={generated_key}\n"
    assert env_path.stat().st_ino != stale_inode, "the 0644 file was reused"
    assert stat.S_IMODE(env_path.stat().st_mode) & 0o077 == 0


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
        # Match the directory, not the exact name: the write goes to a private
        # temporary file beside `.env`, so a stub keyed on `.env` itself would
        # inject no failure at all and the test would pass vacuously.
        if os.path.dirname(str(path)) == str(env_path.parent):
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_a_symlinked_key_file_is_refused_rather_than_read_through(
    monkeypatch, tmp_path
):
    """A symlinked key file must not be read through.

    This read runs before the directory and file are hardened, so a key
    adopted here never receives those protections.
    """
    from marm_mcp_server.config import api_key_bootstrap

    planted = tmp_path / "attacker.env"
    planted.write_text("MARM_API_KEY=key-chosen-by-somebody-else\n")
    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.symlink_to(planted)
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)

    assert api_key_bootstrap._load_key_from_file() == ""

    # And the real file is still read normally -- the gate is the link, not the read.
    env_path.unlink()
    env_path.write_text("MARM_API_KEY=a-key-we-actually-wrote\n")
    assert api_key_bootstrap._load_key_from_file() == "a-key-we-actually-wrote"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_a_symlink_swapped_in_after_the_checks_does_not_receive_the_secret(tmp_path):
    """A link planted after the checks must not receive the secret.

    No check on a pathname survives that pathname being replaced immediately
    afterwards, so the write goes to a private temporary file and is renamed
    into place. Driven against `_write_key_file` directly: racing
    `resolve_marm_api_key` would plant the link during the earlier read, where
    a different guard refuses it, and never exercise the write window.
    """
    from marm_mcp_server.config import api_key_bootstrap

    target = tmp_path / "attacker-target"
    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)

    real_is_symlink = type(env_path).is_symlink
    raced = []

    def swap_in_the_link(self):
        answer = real_is_symlink(self)
        # Once, and only for the write's own check: the attacker wins exactly
        # the window between that check returning False and the open.
        if not raced and str(self) == str(env_path) and not answer:
            raced.append(True)
            env_path.symlink_to(target)
        return answer

    type(env_path).is_symlink = swap_in_the_link
    try:
        api_key_bootstrap._write_key_file(env_path, "a-generated-key")
    finally:
        type(env_path).is_symlink = real_is_symlink

    assert raced, "the window was never exercised"
    assert not target.exists(), "the credential was written through the symlink"
    assert not env_path.is_symlink(), "the symlink survived the write"
    assert env_path.read_text() == "MARM_API_KEY=a-generated-key\n"
    assert stat.S_IMODE(env_path.stat().st_mode) & 0o077 == 0
    assert sorted(p.name for p in env_path.parent.iterdir()) == [".env"], (
        "the temporary file was left behind"
    )


def test_the_read_path_fails_closed_when_it_cannot_open_safely(monkeypatch, tmp_path):
    """An unsafe open must refuse, not fall back to a following one.

    The Windows branch cannot run here and there is no Windows CI, so what is
    pinned is the contract every branch shares: `open_no_follow` raising means
    no key is adopted. Generating a fresh key is the tolerable outcome;
    adopting one an attacker redirected is not.
    """
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("MARM_API_KEY=planted-value-that-is-long-enough\n")
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)

    def refuse(_path):
        raise OSError("cannot prove this open is safe")

    monkeypatch.setattr(api_key_bootstrap, "open_no_follow", refuse)
    assert api_key_bootstrap._load_key_from_file() == ""


def test_a_readable_key_file_is_still_adopted(monkeypatch, tmp_path):
    """The guard above must not be the reason every key read returns empty."""
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("MARM_API_KEY=a-real-key-value-long-enough\n")
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)

    assert api_key_bootstrap._load_key_from_file() == "a-real-key-value-long-enough"


def test_open_no_follow_refuses_a_reparse_point_on_windows(monkeypatch, tmp_path):
    """The Windows branch refuses what it opened when it is a reparse point.

    Exercised by simulation because no runner here is Windows: the real
    CreateFileW is replaced, and what is being pinned is that a handle whose
    attributes carry FILE_ATTRIBUTE_REPARSE_POINT is closed and refused rather
    than read.
    """
    import ctypes
    import os as os_module

    from marm_mcp_server.utils import security

    monkeypatch.setattr(security.sys, "platform", "win32")

    fake_fd = os_module.open(tmp_path / "decoy", os_module.O_CREAT | os_module.O_RDONLY)
    closed = []

    class _Kernel32:
        @staticmethod
        def CreateFileW(*_args):
            return 4242

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: _Kernel32(), raising=False)
    monkeypatch.setitem(
        __import__("sys").modules,
        "msvcrt",
        type("m", (), {"open_osfhandle": staticmethod(lambda *_a: fake_fd)})(),
    )
    monkeypatch.setattr(
        security.os,
        "fstat",
        lambda _fd: type("s", (), {"st_file_attributes": 0x400})(),
    )
    monkeypatch.setattr(security.os, "close", lambda fd: closed.append(fd))

    with pytest.raises(OSError, match="reparse point"):
        security.open_no_follow(tmp_path / ".env")
    assert closed == [fake_fd], "the handle must be closed before refusing"
    os_module.close(fake_fd)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory modes")
def test_a_key_directory_owned_by_someone_else_still_persists_the_key(
    monkeypatch, tmp_path
):
    """A Docker bind mount is world-writable and not ours, and must still work.

    The container's non-root user does not share the host uid, so the mount is
    world-writable by necessity and cannot be chmodded from inside. Refusing
    there meant no key was ever persisted -- caught by the upstream Docker
    suite, not by this file, because it only appears with a real mount.
    """
    from marm_mcp_server.config import api_key_bootstrap

    directory = tmp_path / ".marm"
    directory.mkdir(mode=0o777)
    os.chmod(directory, 0o777)

    real_stat = Path.stat

    def not_ours(self, *args, **kwargs):
        info = real_stat(self, *args, **kwargs)
        if self == directory:
            return os.stat_result(
                (
                    info.st_mode,
                    info.st_ino,
                    info.st_dev,
                    info.st_nlink,
                    info.st_uid + 1,
                    info.st_gid,
                    *tuple(info)[6:],
                )
            )
        return info

    monkeypatch.setattr(Path, "stat", not_ours)
    monkeypatch.setattr(
        Path,
        "chmod",
        lambda *a, **k: (_ for _ in ()).throw(
            PermissionError("Operation not permitted")
        ),
    )

    # Warns, but does not raise: the key file itself is still created 0600.
    api_key_bootstrap._secure_key_dir(directory)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory modes")
def test_a_key_directory_we_own_and_cannot_secure_is_still_refused(
    monkeypatch, tmp_path
):
    """The original protection, unchanged: staying permissive was our choice."""
    from marm_mcp_server.config import api_key_bootstrap

    directory = tmp_path / ".marm"
    directory.mkdir(mode=0o777)
    os.chmod(directory, 0o777)
    monkeypatch.setattr(Path, "chmod", lambda *a, **k: None)

    with pytest.raises(OSError, match="could not be secured"):
        api_key_bootstrap._secure_key_dir(directory)
