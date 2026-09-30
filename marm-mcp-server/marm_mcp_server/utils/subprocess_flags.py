"""Process flags for child programs started by MARM's background processes."""

import subprocess
import sys


def no_window_flags() -> int:
    """A detached process has no console, so Windows opens a new window for every console child."""
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0
