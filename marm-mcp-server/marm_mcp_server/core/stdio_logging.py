"""STDIO transport logging setup for MARM MCP Server."""

import logging
import os
import pathlib
import sys

_log_dir_env = os.environ.get("MARM_STDIO_LOG_DIR")
_log_dir = (
    pathlib.Path(_log_dir_env)
    if _log_dir_env
    else pathlib.Path.home() / ".marm" / "logs"
)
_log_level_name = os.environ.get("MARM_STDIO_LOG_LEVEL", "INFO").upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
_debug = _log_level <= logging.DEBUG

_stdio_log = logging.getLogger("marm.stdio")
_stdio_log.setLevel(_log_level)
_stdio_log.propagate = False

_fmt = logging.Formatter("%(asctime)s [MARM] %(levelname)s %(message)s")

_sh = logging.StreamHandler(sys.stderr)
_sh.setFormatter(_fmt)
_stdio_log.addHandler(_sh)

try:
    _log_dir.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(_log_dir / "marm-stdio.log", encoding="utf-8")
    _fh.setFormatter(_fmt)
    _stdio_log.addHandler(_fh)
except Exception:
    pass
