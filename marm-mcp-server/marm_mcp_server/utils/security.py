"""Cryptographic utilities — no imports from settings, no side effects."""

import os
import secrets
import string
import subprocess
import sys
from pathlib import Path


def generate_api_key(length: int = 40) -> str:
    """Generate a cryptographically strong API key with mixed character classes."""
    symbols = "-_+=.~@#%^&*"
    alphabet = string.ascii_letters + string.digits + symbols
    key = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(symbols),
    ]
    key += [secrets.choice(alphabet) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(key)
    return "".join(key)


def restrict_windows_file_to_current_user(path: Path) -> bool:
    """Grant the executing Windows identity exclusive access to a sensitive file."""
    if sys.platform != "win32":
        return True
    try:
        system_root = os.environ.get("SystemRoot")
        if not system_root:
            return False
        system32 = Path(system_root) / "System32"
        whoami = system32 / "whoami.exe"
        icacls = system32 / "icacls.exe"
        if not whoami.is_absolute() or not icacls.is_absolute():
            return False
        identity = subprocess.run(
            [str(whoami)], check=False, capture_output=True, text=True
        ).stdout.strip()
        if not identity:
            return False
        result = subprocess.run(
            [
                str(icacls),
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{identity}:(F)",
            ],
            check=False,
            capture_output=True,
        )
        return result.returncode == 0
    except OSError:
        return False
