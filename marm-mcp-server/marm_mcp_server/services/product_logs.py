"""Bounded managed-runtime log display for the product CLI."""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path


def show_logs(lines: int, follow: bool, *, path: Path) -> int:
    """Print the requested tail and safely follow a log that may be rotated."""
    if not path.exists():
        print("No managed runtime log exists yet.")
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as log_file:
        recent = deque(log_file, maxlen=max(1, lines))
        for line in recent:
            print(line, end="")
        if not follow:
            return 0
        while True:
            line = log_file.readline()
            if line:
                print(line, end="")
                continue
            try:
                if path.stat().st_size < log_file.tell():
                    log_file.seek(0)
                time.sleep(0.5)
            except KeyboardInterrupt:
                return 0
            except OSError:
                time.sleep(0.5)
