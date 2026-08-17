"""Persistent local API-key operations for the product CLI."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from ..utils.security import generate_api_key, restrict_windows_file_to_current_user


def managed_key_path() -> Path:
    """Return the managed local env file without creating it."""
    return Path.home() / ".marm" / ".env"


def read_managed_key(path: Path | None = None) -> str:
    """Read the managed key without exposing parsing details to CLI callers."""
    try:
        for raw_line in (
            (path or managed_key_path()).read_text(encoding="utf-8").splitlines()
        ):
            line = raw_line.strip()
            if not line or line.startswith("#") or not line.startswith("MARM_API_KEY="):
                continue
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                return value[1:-1]
            return value.split("#", 1)[0].strip()
    except OSError:
        pass
    return ""


def _protect_key_file(path: Path) -> bool:
    """Apply and verify owner-only access before treating a key as usable."""
    if sys.platform != "win32":
        try:
            path.chmod(0o600)
            return stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
        except OSError:
            return False
    try:
        return restrict_windows_file_to_current_user(path)
    except OSError:
        return False


def initialize_managed_key(path: Path | None = None) -> tuple[Path, bool]:
    """Create the managed key file once, preserving an existing credential."""
    destination = path or managed_key_path()
    if read_managed_key(destination):
        if not _protect_key_file(destination):
            raise RuntimeError(f"Could not secure managed key file: {destination}")
        return destination, False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(
            f"Managed key file exists but does not contain MARM_API_KEY: {destination}"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as key_file:
            key_file.write(f"MARM_API_KEY={generate_api_key()}\n")
    except OSError:
        destination.unlink(missing_ok=True)
        raise
    if not _protect_key_file(destination):
        raise RuntimeError(f"Could not secure managed key file: {destination}")
    return destination, True
