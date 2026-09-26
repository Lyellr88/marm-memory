import errno
import os
import secrets
import stat
import sys
from pathlib import Path

from ..services import key_management
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

    Refuses any directory that cannot end up private and owner-owned, whoever
    owns it. An earlier version warned and continued when the directory
    belonged to somebody else, on the grounds that a Docker bind mount is
    world-writable by necessity and hard-failing there would break the one
    deployment that always looks like this.

    That reasoning was wrong about the threat. A world-writable directory owned
    by another uid is exactly where an auto-generated key must not be written:
    the private-temp-then-rename dance protects the file's *contents*, not the
    directory that anyone may swap or pre-populate underneath it. Reported on
    PR #206 against the write path, and the same argument applies here.

    The supported answer in a container is `MARM_API_KEY` from the
    environment, which needs no key file at all.
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
    owner = "this process" if info.st_uid == os.getuid() else f"uid {info.st_uid}"
    raise OSError(
        f"key directory is accessible to other users and could not be secured: "
        f"{directory} (mode {remaining:#o}, owned by {owner}); set MARM_API_KEY "
        f"in the environment to run without persisting a key"
    )


def _sync_directory(directory: "Path | int") -> None:
    """Make the renamed directory entry durable, not just the file contents.

    A POSIX rename is a directory operation, so fsyncing the file alone leaves
    the entry itself unflushed. Windows exposes no directory handle to sync and
    does not need one for this.
    """
    if os.name == "nt":
        return
    if isinstance(directory, int):
        # Already an open, verified descriptor. Re-resolving the path to sync it
        # would reopen the very window that descriptor exists to close.
        os.fsync(directory)
        return
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


#: Descriptor-relative creation is the only way to close the parent-swap
#: window. `os.open(..., dir_fd=...)` resolves the child against an already-open
#: directory inode, so replacing the *pathname* afterwards cannot redirect it.
_HAVE_DIR_FD = (
    hasattr(os, "O_DIRECTORY")
    and os.open in getattr(os, "supports_dir_fd", set())
    # `os.rename`, not `os.replace`: only rename is descriptor-capable, and on
    # POSIX -- the only place this branch runs -- they are the same rename(2),
    # which overwrites atomically. `replace` differs from `rename` on Windows
    # alone, and Windows takes the fail-closed path below.
    and os.rename in getattr(os, "supports_dir_fd", set())
    and os.unlink in getattr(os, "supports_dir_fd", set())
)


def _open_private_key_dir(directory: Path) -> int:
    """Open the key directory and verify it THROUGH the descriptor.

    Checking the parent by pathname and then creating a file by pathname is a
    check-then-use gap: `O_NOFOLLOW` constrains only the final component, so a
    directory swapped between the two -- a junction on Windows, a symlink on
    POSIX -- still receives the key. Reported on PR #206 with a working
    reproduction: replacing the directory immediately after the check delivered
    `MARM_API_KEY` to an attacker-controlled target.

    Everything here is decided from `fstat` on the descriptor, never from the
    path. Once this returns, the caller operates relative to that inode and the
    pathname is irrelevant.

    Fails closed rather than falling back. An auto-generated key must never
    land in a directory that cannot be shown to be private and owner-owned --
    including the world-writable, foreign-owned Docker bind mount, where the
    supported answer is to supply `MARM_API_KEY` from the environment.
    """
    if not _HAVE_DIR_FD:
        # Windows, or any platform without descriptor-relative openat. The race
        # cannot be closed here, and a full handle-relative implementation is
        # out of proportion to the problem, so persistence is declined.
        raise KeyFileProtectionError(
            "this platform cannot verify the key directory without a "
            "time-of-check/time-of-use gap; set MARM_API_KEY in the environment "
            "to persist a key"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError as exc:
        # O_NOFOLLOW|O_DIRECTORY reports a symlinked directory as ELOOP or
        # ENOTDIR depending on the platform. Say what actually happened --
        # "Not a directory" about a directory is a confusing way to report a
        # symlink, and this is the message an operator has to act on.
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise KeyFileProtectionError(
                f"key directory is a symlink, refusing to persist through it: "
                f"{directory}"
            ) from exc
        raise KeyFileProtectionError(
            f"could not open the key directory safely: {directory}: {exc}"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid():
            raise KeyFileProtectionError(
                f"key directory is owned by uid {info.st_uid}, not by this "
                f"process (uid {os.geteuid()}): {directory}; set MARM_API_KEY "
                f"in the environment to persist a key"
            )
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o022:
            raise KeyFileProtectionError(
                f"key directory is writable by group or others (mode "
                f"{mode:#o}): {directory}; set MARM_API_KEY in the environment "
                f"to persist a key"
            )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _write_key_file(path: Path, marm_api_key: str) -> None:
    """Write the key file so the secret is never readable by anyone else.

    The secret is never written to `path`. It goes to a fresh private file in
    the same directory, is hardened while it still has a name nobody else
    knows, and is then moved into place. That closes three exposures at once:
    a new file created through the umask, an existing file whose mode `os.open`
    does not change, and a pathname swapped between the check and the open --
    which `O_NOFOLLOW` cannot close on Windows.

    **Every step runs relative to a verified directory descriptor.** An earlier
    version checked `path.parent.is_symlink()` and then created the temporary
    file through the parent *pathname*, which left a swap window: replacing the
    directory with a junction between the two delivered the key to an
    attacker-controlled target (reported on PR #206, with a reproduction). A
    descriptor is immune to that -- the inode is already open, so renaming or
    replacing the path afterwards changes nothing.

    `O_CREAT | O_EXCL` guarantees the descriptor is one we created. `os.replace`
    is atomic on both platforms, so it replaces a symlink rather than writing
    through it and a concurrent reader never sees a half-written key.

    Unlike `initialize_managed_key()`, bootstrap intentionally overwrites,
    which is why this ends in a replace rather than a failure.
    """
    if path.is_symlink():
        # Reports intent early; the atomic replace below is what makes it safe.
        raise OSError(f"key file is a symlink, refusing to write through it: {path}")

    # Fails closed when the directory cannot be shown to be private and ours --
    # a symlinked `~/.marm`, a foreign owner, or group/other write. This is the
    # check the old `path.parent.is_symlink()` test was reaching for, done
    # against an inode instead of a name.
    directory = _open_private_key_dir(path.parent)
    # A bare name, never a path: every operation below is relative to the
    # verified descriptor, so there is nothing left to resolve.
    name = f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(name, flags, 0o600, dir_fd=directory)
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
        # Harden before the file is reachable under its real name -- and do it
        # through the same descriptor. `_protect_key_file()` takes a path, so
        # calling it here would reintroduce the pathname dependency this
        # function exists to remove: under the reported swap it looks for the
        # temporary file in the attacker's directory, does not find it, and
        # fails a write that was never actually endangered.
        try:
            os.chmod(name, 0o600, dir_fd=directory)
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except OSError as exc:
            raise KeyFileProtectionError(
                f"could not secure the new key file: {path}: {exc}"
            ) from exc
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise KeyFileProtectionError(
                f"could not secure the new key file: {path} "
                f"(mode {stat.S_IMODE(info.st_mode):#o})"
            )
        os.rename(name, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        try:
            # Pass the verified descriptor, not the path: re-resolving it here
            # would reopen the window the descriptor exists to close.
            _sync_directory(directory)
        except OSError as exc:
            # The file is in place but the entry may not survive a crash, and
            # the caller is about to promise that it will. A persistence
            # failure is the honest report -- it is the branch that says the
            # key is live in memory and will not survive a restart.
            try:
                os.unlink(path.name, dir_fd=directory)
            except OSError:
                pass
            raise KeyFileProtectionError(
                f"could not flush the key directory entry: {path.parent}: {exc}"
            ) from exc
    except BaseException:
        try:
            os.unlink(name, dir_fd=directory)
        except OSError:
            pass
        raise
    finally:
        os.close(directory)


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


def _load_key_from_keychain() -> tuple[str, str]:
    """Read an explicitly stored keychain credential and preserve failures."""
    key, problem = key_management.keychain_lookup()
    if problem:
        print(
            f"MARM: cannot use the OS keychain ({problem}); "
            f"falling back to {_MARM_ENV_PATH}.",
            file=sys.stderr,
        )
    return key, problem


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
    """Resolve MARM_API_KEY from env, keychain, file, or a new key."""
    marm_api_key = os.environ.get("MARM_API_KEY", "")

    if server_host == "0.0.0.0" and not marm_api_key:
        keychain_key, keychain_problem = _load_key_from_keychain()
        marm_api_key = keychain_key or _load_key_from_file()
        if not marm_api_key and keychain_problem:
            raise key_management.KeychainUnavailable(
                "MARM_API_KEY was not loaded because the OS keychain failed and "
                f"no fallback file exists: {keychain_problem}"
            )

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
