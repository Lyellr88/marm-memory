import os
import stat
import sys
from pathlib import Path

from ..services.key_management import _protect_key_file
from ..utils.security import generate_api_key

_MARM_ENV_PATH = Path.home() / ".marm" / ".env"


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
    """Write the key file so the secret is never on disk world-readable.

    There are two distinct exposures, and the mode argument to `os.open` only
    closes one of them.

    New file: `Path.write_text()` creates through the process umask -- 0644
    typically, 0666 under `umask 0` -- leaving the plaintext bearer token
    readable by other local users until the chmod inside `_protect_key_file()`
    lands. Creating with an explicit 0o600 closes that window.

    Existing file: the mode argument applies ONLY when `os.open` creates the
    file. An existing `~/.marm/.env` at 0644 keeps 0644 through the `O_TRUNC`
    open, so without the step below the new token would be written into a
    still-world-readable file and hardened only afterwards -- the same exposure
    the new-file case has, on a path that is easy to overlook because the end
    state looks correct. So harden before writing when the file already exists.

    `_protect_key_file()` still runs after the write. It is the cross-platform
    step, it is what validates Windows ACLs, and it is what the caller checks
    before deciding the key was persisted safely.

    `O_TRUNC` because bootstrap intentionally overwrites, where
    `initialize_managed_key()` intentionally refuses to (`O_EXCL`).
    """
    if path.is_symlink():
        # Never write a credential through a link: the target is chosen by
        # whoever created the link, not by us.
        raise OSError(f"key file is a symlink, refusing to write through it: {path}")
    if path.exists() and not _protect_key_file(path):
        raise OSError(f"could not secure the existing key file before writing: {path}")
    # O_NOFOLLOW makes the kernel refuse a symlink swapped in after the checks
    # above, closing the gap between them and this open. Absent on Windows.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as key_file:
        key_file.write(f"MARM_API_KEY={marm_api_key}\n")


def _load_key_from_file() -> str:
    """Read MARM_API_KEY from ~/.marm/.env if present."""
    try:
        for raw_line in _MARM_ENV_PATH.read_text().splitlines():
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
            _write_key_file(_MARM_ENV_PATH, marm_api_key)
            try:
                key_protected = _protect_key_file(_MARM_ENV_PATH)
            except Exception:
                key_protected = False
            if key_protected:
                key_persisted = True
            else:
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
                    print(
                        "WARNING: API key file protection failed. The API key is being "
                        "kept in memory only and will not survive a restart. Set "
                        "MARM_API_KEY explicitly in the environment.",
                        file=sys.stderr,
                    )
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
