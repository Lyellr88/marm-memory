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
    monkeypatch, tmp_path, capsys
):
    """Runs everywhere, and asserts whichever contract the platform has.

    Where the key can be persisted safely it must round-trip: the first
    0.0.0.0 start generates and saves one, and every start after loads the
    same key back. Where it cannot -- no descriptor-relative directory
    operations, which is Windows -- nothing is written, the server still
    starts with the key in memory, and the operator is told so.

    Branching rather than skipping is deliberate: a skip on Windows would
    leave the documented Windows behaviour unasserted on the one platform
    where it applies.
    """
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    first_start = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")
    assert first_start
    second_start = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    if api_key_bootstrap._HAVE_DIR_FD:
        assert env_path.read_text() == f"MARM_API_KEY={first_start}\n"
        assert stat.S_IMODE(env_path.stat().st_mode) & 0o077 == 0
        assert second_start == first_start
    else:
        _assert_key_kept_in_memory(env_path, capsys)
        assert second_start != first_start, (
            "nothing was persisted, so the next start must generate a new key"
        )


def _assert_key_kept_in_memory(env_path, capsys):
    """The contract where a key cannot be persisted safely.

    No `.env`, and a warning that says both what happened and what to do --
    a warning without the instruction leaves the operator with a server whose
    key silently changes every restart.
    """
    assert not env_path.exists(), "no key may be written through an unverifiable path"
    warning = capsys.readouterr().err
    assert "kept in memory only and will not survive a restart" in warning
    assert "Set MARM_API_KEY explicitly in the environment" in warning


def test_a_generated_key_is_not_persisted_without_openat(monkeypatch, tmp_path, capsys):
    """The Windows contract, forced on so it is exercised everywhere.

    The branch in the three tests above only runs its Windows half on Windows,
    and CI is Linux -- which is how this behaviour reached a maintainer's
    machine unasserted. Patching `_HAVE_DIR_FD` rather than `os.name` runs the
    same path on every platform.
    """
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.setattr(api_key_bootstrap, "_HAVE_DIR_FD", False)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    first_start = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")
    assert first_start, "the server must still start, with the key in memory"
    _assert_key_kept_in_memory(env_path, capsys)

    second_start = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")
    assert second_start != first_start, (
        "nothing was persisted, so the next start must generate a different key "
        "-- which is exactly what the operator is being warned about"
    )


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
    """An unprotectable `.env` that also cannot be deleted must be shouted about.

    Where no key file is written at all -- no descriptor-relative directory
    operations, which is Windows -- there is no insecure file to fail to
    remove, and the contract is the in-memory one instead. Asserted here
    rather than skipped, so the platform behaviour is covered on the platform
    that has it.
    """
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

    if not api_key_bootstrap._HAVE_DIR_FD:
        _assert_key_kept_in_memory(env_path, capsys)
        return

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
    partially written credential behind.

    The stub injects that failure into the descriptor-relative write. Where
    there is no such write -- Windows -- nothing is ever opened and the same
    end state is reached by declining earlier, which is asserted rather than
    skipped so the behaviour is covered on that platform too.
    """
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)
    monkeypatch.delenv("MARM_API_KEY", raising=False)

    real_open = os.open

    def refuse_key_file(path, flags, mode=0o777, *args, **kwargs):
        # Match on the CREATE, not on the path. The write is descriptor-relative
        # now -- `os.open(name, ..., dir_fd=fd)` passes a bare filename -- so a
        # stub keyed on the directory prefix stops matching and injects no
        # failure at all, which is the vacuous pass the original comment warned
        # about. The directory's own open must still succeed, or this would
        # exercise the wrong failure.
        creating = flags & os.O_CREAT
        in_key_dir = kwargs.get("dir_fd") is not None or os.path.dirname(
            str(path)
        ) == str(env_path.parent)
        if creating and in_key_dir:
            raise OSError(13, "Permission denied")
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", refuse_key_file)

    generated_key = api_key_bootstrap.resolve_marm_api_key("0.0.0.0")

    assert generated_key  # still usable in memory for this process

    if not api_key_bootstrap._HAVE_DIR_FD:
        _assert_key_kept_in_memory(env_path, capsys)
        return

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
def test_a_key_directory_owned_by_someone_else_is_refused(monkeypatch, tmp_path):
    """A world-writable directory owned by another uid must NOT receive a key.

    This asserted the opposite until 2026-09-19: a Docker bind mount is
    world-writable by necessity, so refusing there meant no key was persisted,
    and warning-and-continuing looked like the pragmatic choice.

    It was the wrong trade, and the maintainer said so on PR #206. Writing to a
    private temporary file and renaming protects the key's CONTENTS; it does
    nothing about a directory any local user may swap or pre-populate. The
    supported answer in a container is `MARM_API_KEY` from the environment,
    which needs no key file at all.
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

    with pytest.raises(OSError, match="could not be secured"):
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_a_symlinked_key_directory_is_refused(monkeypatch, tmp_path):
    """`O_NOFOLLOW` covers only the final component.

    With `~/.marm` itself the symlink rather than `~/.marm/.env`, the open
    still traversed it and adopted whatever key the attacker's directory held.
    Opening relative to a validated parent descriptor closes that.
    """
    from marm_mcp_server.config import api_key_bootstrap

    planted = tmp_path / "attacker"
    planted.mkdir()
    (planted / ".env").write_text("MARM_API_KEY=planted-through-the-parent-dir\n")

    home = tmp_path / "home"
    home.mkdir()
    (home / ".marm").symlink_to(planted)
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", home / ".marm" / ".env")

    assert api_key_bootstrap._load_key_from_file() == ""


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_a_real_key_directory_still_reads(monkeypatch, tmp_path):
    """The guard above must not refuse every ordinary directory."""
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("MARM_API_KEY=an-ordinary-key-value-here\n")
    monkeypatch.setattr(api_key_bootstrap, "_MARM_ENV_PATH", env_path)

    assert api_key_bootstrap._load_key_from_file() == "an-ordinary-key-value-here"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative writes")
def test_the_key_is_flushed_to_disk_before_it_is_called_saved(monkeypatch, tmp_path):
    """`os.replace` is atomic against a reader, not against power loss.

    The caller prints "Saved to: ..." and "on subsequent starts the key loads
    silently", so an unflushed write makes that a promise the code has not
    kept: a crash before writeback leaves the next start generating a
    different key and rejecting every client that kept the first one.
    """
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)

    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd))[1])

    api_key_bootstrap._write_key_file(env_path, "a-key-long-enough-to-store")

    assert env_path.read_text() == "MARM_API_KEY=a-key-long-enough-to-store\n"
    # One for the file contents, one for the renamed directory entry.
    assert len(synced) == 2, f"expected file and directory fsync, saw {len(synced)}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative writes")
def test_a_failed_flush_is_reported_as_a_persistence_failure(monkeypatch, tmp_path):
    """Otherwise the caller prints "Saved to:" for a key that may not be there."""
    from marm_mcp_server.config import api_key_bootstrap

    env_path = tmp_path / ".marm" / ".env"
    env_path.parent.mkdir(parents=True)

    def refuse(_fd):
        raise OSError("disk went away")

    monkeypatch.setattr(os, "fsync", refuse)

    with pytest.raises(api_key_bootstrap.KeyFileProtectionError):
        api_key_bootstrap._write_key_file(env_path, "a-key-long-enough-to-store")
    assert not env_path.exists(), "a failed write must not leave a file behind"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_a_symlinked_key_directory_is_refused_rather_than_written_through(tmp_path):
    """Persistence must fail closed on a symlinked `~/.marm`, not rotate the key.

    The read path already refuses one: `open_no_follow` declines a symlinked
    parent, so the saved key was never loaded back. The write path followed the
    same link happily, so every restart generated a key, saved it where the
    reader would not look, and rejected every client holding the previous one.
    """
    from marm_mcp_server.config.api_key_bootstrap import (
        KeyFileProtectionError,
        _write_key_file,
    )

    real = tmp_path / "real-marm"
    real.mkdir()
    linked = tmp_path / "linked-marm"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(KeyFileProtectionError, match="key directory is a symlink"):
        _write_key_file(linked / ".env", "k-should-not-be-written")

    assert not (real / ".env").exists(), "the key was written through the symlink"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative writes")
def test_a_directory_sync_failure_after_the_rename_leaves_no_key_behind(
    monkeypatch, tmp_path
):
    """State and warning have to agree.

    If the file fsync and `os.replace` both succeed and only the directory sync
    fails, the temporary path is already gone -- so the old cleanup unlinked
    nothing and `.env` survived holding the key, while the caller reported that
    persistence had failed and told the operator the key lived only in memory.
    """
    from marm_mcp_server.config import api_key_bootstrap as boot

    target = tmp_path / ".env"

    def _fail_directory_sync(_directory):
        raise OSError("simulated directory fsync failure")

    monkeypatch.setattr(boot, "_sync_directory", _fail_directory_sync)

    with pytest.raises(boot.KeyFileProtectionError, match="directory entry"):
        boot._write_key_file(target, "k-not-durably-persisted")

    assert not target.exists(), (
        "persistence reported failure but the key file remained, so the next "
        "start would silently adopt a key the caller said was not saved"
    )
    leftovers = [p.name for p in tmp_path.iterdir()]
    assert leftovers == [], f"temporary files left behind: {leftovers}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative writes")
def test_swapping_the_key_directory_after_the_check_cannot_redirect_the_key(
    monkeypatch, tmp_path
):
    """The reported attack, reproduced: swap the parent between check and write.

    `_write_key_file()` used to test `path.parent.is_symlink()` and then create
    its temporary file through that same parent *pathname*. `O_NOFOLLOW`
    constrains only the final component, so replacing the directory in the gap
    delivered the key to an attacker-controlled target. Reported on PR #206 with
    a Windows junction; a symlink is the POSIX equivalent.

    Verifying an open descriptor instead makes the swap irrelevant -- the inode
    is already held, so renaming the path afterwards redirects nothing.
    """
    from marm_mcp_server.config import api_key_bootstrap as boot

    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    attacker = tmp_path / "attacker"
    attacker.mkdir(mode=0o700)
    target = real / ".env"

    real_open = os.open
    swapped = {"done": False}

    def swap_then_open(path, flags, mode=0o777, *args, **kwargs):
        descriptor = real_open(path, flags, mode, *args, **kwargs)
        # Fire once, immediately after the directory is opened and verified --
        # precisely the window the report describes.
        if not swapped["done"] and flags & getattr(os, "O_DIRECTORY", 0):
            swapped["done"] = True
            real.rename(tmp_path / "moved-away")
            (tmp_path / "real").symlink_to(attacker, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(os, "open", swap_then_open)
    boot._write_key_file(target, "k-must-not-leak")

    assert swapped["done"], "the swap never fired; the test proved nothing"
    assert not (attacker / ".env").exists(), (
        "the key was written into the attacker's directory after the swap"
    )
    assert (tmp_path / "moved-away" / ".env").read_text().strip() == (
        "MARM_API_KEY=k-must-not-leak"
    ), "the key must land in the directory that was actually verified"
