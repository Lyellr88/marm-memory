import os
import sys
from collections.abc import Callable
from pathlib import Path


def _home() -> Path:
    return Path.home()


def _platform() -> str:
    return sys.platform


def _appdata() -> Path:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) if appdata else _home() / "AppData" / "Roaming"


def hermes_home() -> Path:
    override = os.environ.get("HERMES_HOME")
    if override:
        return Path(override).expanduser()
    if _platform() == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else _home() / "AppData" / "Local") / "hermes"
    return _home() / ".hermes"


def cline_home() -> Path:
    override = os.environ.get("CLINE_DIR")
    return Path(override).expanduser() if override else _home() / ".cline"


def cline_data_dir() -> Path:
    data = os.environ.get("CLINE_DATA_DIR")
    return Path(data).expanduser() if data else cline_home() / "data"


def cline_mcp_settings_path() -> Path:
    explicit = os.environ.get("CLINE_MCP_SETTINGS_PATH")
    if explicit:
        return Path(explicit).expanduser()
    return cline_data_dir() / "settings" / "cline_mcp_settings.json"


def _cline_markers() -> list[Path]:
    return [cline_home(), cline_data_dir(), cline_mcp_settings_path().parent]


def _xdg_config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return Path(base).expanduser() if base else _home() / ".config"


def opencode_home() -> Path:
    return _xdg_config_home() / "opencode"


def zed_home() -> Path:
    if _platform() == "win32":
        return _appdata() / "Zed"
    base = _home() / ".config" if _platform() == "darwin" else _xdg_config_home()
    return base / "zed"


def _zed_path() -> Path:
    return zed_home() / "settings.json"


def _opencode_path() -> Path:
    for name in ("opencode.jsonc", "opencode.json"):
        if (opencode_home() / name).exists():
            return opencode_home() / name
    return opencode_home() / "opencode.json"


def _antigravity_path() -> Path:
    gemini = _home() / ".gemini"
    legacy = gemini / "antigravity" / "mcp_config.json"
    if legacy.exists() and not (gemini / "config").is_dir():
        return legacy
    return gemini / "config" / "mcp_config.json"


def _antigravity_markers() -> list[Path]:
    gemini = _home() / ".gemini"
    return [
        gemini / "config",
        gemini / "antigravity",
        gemini / "antigravity-cli",
        gemini / "antigravity-ide",
        _home() / ".antigravity",
    ]


def _vscode_config_path() -> Path:
    if _platform() == "win32":
        return _appdata() / "Code" / "User" / "mcp.json"
    if _platform() == "darwin":
        return (
            _home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
        )
    return _home() / ".config" / "Code" / "User" / "mcp.json"


def _claude_desktop_path() -> Path | None:
    if _platform() == "win32":
        return _appdata() / "Claude" / "claude_desktop_config.json"
    if _platform() == "darwin":
        return (
            _home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    return None


def _claude_desktop_markers() -> list[Path]:
    path = _claude_desktop_path()
    return [path.parent] if path else []


def devin_home() -> Path:
    if _platform() == "win32":
        return _appdata() / "devin"
    return _xdg_config_home() / "devin"


def _devin_path() -> Path:
    return devin_home() / "mcp_config.json"


def _devin_markers() -> list[Path]:
    if _platform() == "darwin":
        desktop = _home() / "Library" / "Application Support" / "Devin"
    elif _platform() == "win32":
        desktop = _appdata() / "Devin"
    else:
        desktop = _xdg_config_home() / "Devin"
    return [devin_home(), desktop]


def _under_home(*parts: str) -> Callable[[], Path]:
    return lambda: _home().joinpath(*parts)


def _markers(*parts: str) -> Callable[[], list[Path]]:
    return lambda: [_home().joinpath(*parts)]
