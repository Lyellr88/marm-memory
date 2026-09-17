import os
import secrets
import stat
import sys
from pathlib import Path

from ..services.key_management import _protect_key_file
from ..utils.security import generate_api_key

_MARM_ENV_PATH = Path.home() / ".marm" / ".env"


class KeyFileProtectionError(OSError):
    """The key file could not be made owner-only.

    Distinct from every other write failure because the operator needs a
    different instruction: the key is live in this process but will not survive
    a restart, so set MARM_API_KEY explicitly. Hardening happens inside
    `_write_key_file` now, so without a specific type that advice would be lost
    to the generic "could not save" branch.
    """


def _file_link(path: Path) -> str:
    try:
        uri = path.as_uri()
        return f"\033]8;;{uri}\033\\{path}\033]8;;\033\\"
    except Exception:
        return str(path)


def _secure_key_dir(directory: Path) -> None:
    """Create or tighten `~/.marm` so only its owner can put files in it.

    `mkdir(parents=True, exist_ok=True)` uses `0o777 & ~umask`, so under
    `umask 0` the directory is created world-writable. Any local user with
    write and execute there can swap `.env` for a file or symlink they own
    during the window between hardening it and opening it, and since an
    explicit mode only applies when `os.open` CREATES a file, their file keeps
    its permissive mode and receives the bearer token.

    Closing that means the directory, not just the file: a mode argument to
    `mkdir` applies only on creation, so an already-permissive directory is
    tightened here too. Fails closed if it cannot be made owner-only, because
    writing a credential into a directory other users can write to is the thing
    being prevented.
    """
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":  # POSIX modes do not apply; ACLs are handled per-file
        return
    if stat.S_IMODE(directory.stat().st_mode) & 0o077:
        directory.chmod(0o700)
    remaining = stat.S_IMODE(directory.stat().st_mode)
    if remaining & 0o077:
        raise OSError(
            f"key directory is accessible to other users and could not be "
            f"secured: {directory} (mode {remaining:#o})"
        )


def _write_key_file(path: Path, marm_api_key: str) -> None:
    """Write the key file so the secret is never on disk readable by anyone else.

    Three exposures, and a mode argument to `os.open` closes only the first.

    New file: `Path.write_text()` creates through the process umask -- 0644
    typically, 0666 under `umask 0` -- leaving the plaintext bearer token
    readable by other local users until a later chmod lands. Creating with an
    explicit 0o600 closes that window.

    Existing file: the mode argument applies ONLY when `os.open` CREATES the
    file. An existing `~/.marm/.env` at 0644 keeps 0644 through an `O_TRUNC`
    open, so the new token would land in a still-readable file and be hardened
    only afterwards -- easy to overlook, because the end state looks correct.

    Replacement: no check on a pathname survives that pathname being replaced
    immediately after the check. `O_NOFOLLOW` closes that race on POSIX, but it
    does not exist on Windows -- `getattr(os, "O_NOFOLLOW", 0)` is 0 there -- so
    an actor who can write to the directory could swap in a reparse point
    between the check and the open, and the credential would be written through
    it. Pathname-based ACL hardening afterwards cannot take that back.

    All three close the same way: the secret is never written to `path` at all.
    It goes to a fresh private file in the same directory, which is hardened
    while it still has a name nobody else knows, and is then moved into place.

    `O_CREAT | O_EXCL` means the descriptor is one we created: if anything
    already holds the temporary name, the open fails rather than adopting a
    file someone else controls. `os.replace` swaps the directory entry
    atomically on both platforms, replacing a symlink or reparse point rather
    than writing through it, and a concurrent reader sees either the old file
    or the new one but never a half-written key.

    `_protect_key_file()` runs on the temporary file, before it is reachable
    under the real name, so there is no instant at which `.env` exists and is
    readable by others. The caller runs it again on the final path: that is the
    cross-platform check it uses to decide the key was persisted safely.

    `initialize_managed_key()` intentionally refuses to overwrite (`O_EXCL` on
    its destination); bootstrap intentionally does overwrite, which is why this
    ends in a replace rather than a failure.
    """
    if path.is_symlink():
        # Cheap and clear: report the intent before doing any work. It is not
        # what makes this safe -- the replace below is -- because the link can
        # be created a microsecond after this returns.
        raise OSError(f"key file is a symlink, refusing to write through it: {path}")

    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as key_file:
            key_file.write(f"MARM_API_KEY={marm_api_key}\n")
        # Harden before the file is reachable under its real name, so there is
        # no instant at which `.env` exists and is readable by anyone else.
        try:
            protected = _protect_key_file(temporary)
        except Exception as exc:  # a platform backend can raise, not just fail
            raise KeyFileProtectionError(
                f"could not secure the new key file: {path}: {exc}"
            ) from exc
        if not protected:
            raise KeyFileProtectionError(f"could not secure the new key file: {path}")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_key_file_text(path: Path) -> str:
    """Read the key file, refusing to follow a link to get there.

    The write path already refuses a symlinked `.env`; following one on READ is
    the same defect from the other side. `_load_key_from_file` runs BEFORE
    `_secure_key_dir` and `_write_key_file` in `resolve_marm_api_key`, so a
    local actor who can place the link supplies a key that the service adopts
    and then serves with, and none of the later protections ever apply to it.

    `O_NOFOLLOW` makes the kernel refuse a symlinked final component, which
    closes the check-then-read gap that a separate `is_symlink()` test leaves
    open. It does not exist on Windows, so the explicit check carries that
    platform -- see `_write_key_file` for why the write path does not rely on
    an equivalent check there.
    """
    if path.is_symlink():
        raise OSError(f"key file is a symlink, refusing to read through it: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "r", encoding="utf-8") as key_file:
        return key_file.read()


def _load_key_from_file() -> str:
    """Read MARM_API_KEY from ~/.marm/.env if present."""
    try:
        for raw_line in _read_key_file_text(_MARM_ENV_PATH).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("MARM_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                else:
                    value = value.split("#", 1)[0].strip()
                return value
    except Exception:
        pass
    return ""


def _warn_key_kept_in_memory() -> None:
    """Said whenever the key exists but is not on disk safely.

    Two paths reach it -- protection failing before the rename, and an
    unprotected `.env` that was successfully removed -- and both leave the
    operator in the same position, so they get the same instruction.
    """
    print(
        "WARNING: API key file protection failed. The API key is being "
        "kept in memory only and will not survive a restart. Set "
        "MARM_API_KEY explicitly in the environment.",
        file=sys.stderr,
    )


def resolve_marm_api_key(server_host: str) -> str:
    """Resolve MARM_API_KEY: env var, then ~/.marm/.env, then auto-generate
    and persist one when server_host is 0.0.0.0 and no key was found."""
    marm_api_key = os.environ.get("MARM_API_KEY", "")

    if server_host == "0.0.0.0" and not marm_api_key:
        file_key = _load_key_from_file()
        if file_key:
            marm_api_key = file_key

    is_generate_key_cmd = "--generate-key" in sys.argv or sys.argv[1:3] == [
        "key",
        "generate",
    ]

    if server_host == "0.0.0.0" and not marm_api_key and not is_generate_key_cmd:
        marm_api_key = generate_api_key()
        key_persisted = False
        try:
            _secure_key_dir(_MARM_ENV_PATH.parent)
            try:
                _write_key_file(_MARM_ENV_PATH, marm_api_key)
            except KeyFileProtectionError:
                # Nothing reached `.env`. _write_key_file hardens its temporary
                # file before the rename and removes it on failure, so there is
                # no insecure file to warn about or try to delete -- saying
                # otherwise would send the operator looking for a file that is
                # not there.
                _warn_key_kept_in_memory()
            else:
                try:
                    key_protected = _protect_key_file(_MARM_ENV_PATH)
                except Exception:
                    key_protected = False
                if key_protected:
                    key_persisted = True
                else:
                    # `.env` does exist here and is not verifiably protected.
                    try:
                        _MARM_ENV_PATH.unlink(missing_ok=True)
                    except OSError as e:
                        print(
                            "WARNING: API key file protection failed and the insecure "
                            f"file could not be removed: {_MARM_ENV_PATH}: {e}. Remove "
                            "it immediately. The generated API key remains active in "
                            "memory for this process only; do not rely on the insecure "
                            "file surviving a restart. Set MARM_API_KEY explicitly in "
                            "the environment.",
                            file=sys.stderr,
                        )
                    else:
                        _warn_key_kept_in_memory()
        except Exception as e:
            print(f"WARNING: Could not save API key to {_MARM_ENV_PATH}: {e}")

        print()
        print(
            "MARM: SERVER_HOST=0.0.0.0 detected — API key auto-generated (first start)."
        )
        if key_persisted:
            print(f"Saved to: {_file_link(_MARM_ENV_PATH)}")
            print()
            print(
                "Add this to your MCP client (replace YOUR_KEY with the key from the file above):"
            )
            print(
                '  claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer YOUR_KEY"'
            )
            print()
            print("On subsequent starts the key loads silently from the file above.")
        else:
            print("Set MARM_API_KEY explicitly and restart to connect.")
        print()

    return marm_api_key
