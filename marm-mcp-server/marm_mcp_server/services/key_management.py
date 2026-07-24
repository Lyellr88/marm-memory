"""Persistent local API-key operations for the product CLI."""

from __future__ import annotations

import sys
from pathlib import Path

from ..utils.security import generate_api_key


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


def _protect_key_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass
    if sys.platform != "win32":
        return
    try:
        import getpass
        import subprocess

        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{getpass.getuser()}:(F)",
            ],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass


def initialize_managed_key(path: Path | None = None) -> tuple[Path, bool]:
    """Create the managed key file once, preserving an existing credential."""
    destination = path or managed_key_path()
    if read_managed_key(destination):
        return destination, False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"MARM_API_KEY={generate_api_key()}\n", encoding="utf-8")
    _protect_key_file(destination)
    return destination, True
