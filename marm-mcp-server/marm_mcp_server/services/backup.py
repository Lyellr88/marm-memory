"""Online snapshots of the memory database.

`VACUUM INTO` copies a consistent image while the runtime keeps serving, so a
snapshot needs no downtime and no write-queue drain. Restore is deliberately not
implemented here: swapping the file under a live connection pool is unsafe, and
the supported path is stop, replace, start.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config.settings import DEFAULT_DB_PATH

_STEM = "marm-memory"
_SUFFIX = ".db"
_NAME_RE = re.compile(
    rf"^{re.escape(_STEM)}-\d{{8}}-\d{{6}}(?:-\d+)?{re.escape(_SUFFIX)}$"
)


def backup_dir() -> Path:
    return Path(DEFAULT_DB_PATH).expanduser().resolve().parent / "backups"


def _resolve(name: str) -> Path:
    # Reject traversal before touching the filesystem: `name` reaches here from HTTP.
    if not _NAME_RE.match(name):
        raise ValueError("Not a MARM snapshot name.")
    return backup_dir() / name


def _describe(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def list_backups() -> list[dict[str, Any]]:
    directory = backup_dir()
    if not directory.is_dir():
        return []
    found = [p for p in directory.iterdir() if p.is_file() and _NAME_RE.match(p.name)]
    return sorted(
        (_describe(p) for p in found), key=lambda item: item["name"], reverse=True
    )


def create_backup() -> dict[str, Any]:
    source = Path(DEFAULT_DB_PATH).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError("No MARM memory database exists yet.")

    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = directory / f"{_STEM}-{stamp}{_SUFFIX}"
    attempt = 0
    while target.exists():
        attempt += 1
        target = directory / f"{_STEM}-{stamp}-{attempt}{_SUFFIX}"

    conn = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("VACUUM INTO ?", (str(target),))
    finally:
        conn.close()
    return _describe(target)


def delete_backup(name: str) -> bool:
    target = _resolve(name)
    if not target.is_file():
        return False
    target.unlink()
    return True
