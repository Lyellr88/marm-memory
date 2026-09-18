import os
import secrets
import stat
import sys
from pathlib import Path

from ..services.key_management import _protect_key_file
from ..utils.security import generate_api_key, open_no_follow

_MARM_ENV_PATH = Path.home() / ".marm" / ".env"


class KeyFileProtectionError(OSError):
    """The key file could not be made owner-only.

    A distinct type because the operator needs a distinct instruction: the key
    is live in this process but will not survive a restart, so set
    MARM_API_KEY explicitly.
    """


def _file_link(path: Path) -> str:
    try:
        uri = path.as_uri()
        return f"\033]8;;{uri}\033\\{path}\033]8;;\033\\"
    except Exception:
        return str(path)


def _secure_key_dir(directory: Path) -> None:
    """Create or tighten `~/.marm` so only its owner can put files in it.

    `mkdir(exist_ok=True)` applies its mode only on creation, so an
    already-permissive directory is tightened here too -- otherwise a local
    user with write access could swap `.env` for a file of their own and
    receive the bearer token.

    Refuses only a directory we OWN and still cannot secure, which is the case
    where staying permissive was our choice to make. A directory owned by
    somebody else cannot be chmodded at all, and hard-failing there breaks the
    one deployment that always looks like this: a Docker bind mount is
    world-writable by necessity, because the container's non-root user does not
    share the host uid. Persisting is still safe there -- the key goes to a
    private temporary file, is hardened before it has a public name, and is
    renamed into place -- so this warns and continues rather than declining to
    save a key at all.
    """
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":  # POSIX modes do not apply; ACLs are handled per-file
        return
    if stat.S_IMODE(directory.stat().st_mode) & 0o077:
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    info = directory.stat()
    remaining = stat.S_IMODE(info.st_mode)
    if not remaining & 0o077:
        return
    if info.st_uid == os.getuid():
        raise OSError(
            f"key directory is accessible to other users and could not be "
            f"secured: {directory} (mode {remaining:#o})"
        )
    print(
        f"WARNING: {directory} is owned by another user and is group- or "
        f"world-accessible (mode {remaining:#o}); the key file itself is still "
        f"created owner-only.",
        flush=True,
    )


def _sync_directory(directory: Path) -> None:
    """Make the renamed directory entry durable, not just the file contents.

    A POSIX rename is a directory operation, so fsyncing the file alone leaves
    the entry itself unflushed. Windows exposes no directory handle to sync and
    does not need one for this.
    """
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_key_file(path: Path, marm_api_key: str) -> None:
    """Write the key file so the secret is never readable by anyone else.

    The secret is never written to `path`. It goes to a fresh private file in
    the same directory, is hardened while it still has a name nobody else
    knows, and is then moved into place. That closes three exposures at once:
    a new file created through the umask, an existing file whose mode `os.open`
    does not change, and a pathname swapped between the check and the open --
    which `O_NOFOLLOW` cannot close on Windows.

    `O_CREAT | O_EXCL` guarantees the descriptor is one we created. `os.replace`
    is atomic on both platforms, so it replaces a symlink rather than writing
    through it and a concurrent reader never sees a half-written key.

    Unlike `initialize_managed_key()`, bootstrap intentionally overwrites,
    which is why this ends in a replace rather than a failure.
    """
    if path.is_symlink():
        # Reports intent early; the atomic replace below is what makes it safe.
        raise OSError(f"key file is a symlink, refusing to write through it: {path}")

    # The PARENT matters too, and refusing it on the read path only was worse
    # than not refusing it at all: `open_no_follow` declines a symlinked
    # `~/.marm`, so the key was never loaded back, while this path happily wrote
    # through the same link. Every restart therefore generated and saved a new
    # key and rejected every client holding the previous one. Persistence
    # through a symlinked key directory is unsupported, so it fails closed here
    # and the caller keeps the key in memory.
    if path.parent.is_symlink():
        raise KeyFileProtectionError(
            f"key directory is a symlink, refusing to persist through it: {path.parent}"
        )

    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as key_file:
            key_file.write(f"MARM_API_KEY={marm_api_key}\n")
            # `os.replace` is atomic against a concurrent reader, not against
            # power loss. Without this the caller prints "Saved to: ..." and
            # "on subsequent starts the key loads silently", and a crash before
            # writeback makes the next start generate a DIFFERENT key and
            # reject every client that kept the one it was handed.
            key_file.flush()
            try:
                os.fsync(key_file.fileno())
            except OSError as exc:
                raise KeyFileProtectionError(
                    f"could not flush the new key file to disk: {path}: {exc}"
                ) from exc
        # Harden before the file is reachable under its real name.
        try:
            protected = _protect_key_file(temporary)
        except Exception as exc:  # a platform backend can raise, not just fail
            raise KeyFileProtectionError(
                f"could not secure the new key file: {path}: {exc}"
            ) from exc
        if not protected:
            raise KeyFileProtectionError(f"could not secure the new key file: {path}")
        os.replace(temporary, path)
        try:
            _sync_directory(path.parent)
        except OSError as exc:
            # After the rename, `temporary` no longer exists -- the cleanup
            # below would unlink nothing and `.env` would survive holding the
            # key, while the caller reported that persistence failed and warned
            # the operator the key lives only in memory. The state and the
            # warning have to agree, so this removes the file it just placed:
            # "not persisted" then means exactly that, and the next start
            # generates a key rather than adopting one whose directory entry
            # may not survive a crash.
            try:
                os.unlink(path)
            except OSError:
                pass
            raise KeyFileProtectionError(
                f"could not flush the key directory entry: {path.parent}: {exc}"
            ) from exc
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_key_file_text(path: Path) -> str:
    """Read the key file, refusing to follow a link to reach it.

    This read runs before `_secure_key_dir`, so a key adopted here never
    receives the later protections. `open_no_follow` decides and opens in one
    step on both platforms; a separate `is_symlink()` test would leave a
    window in which the path can be swapped.
    """
    descriptor = open_no_follow(path)
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
