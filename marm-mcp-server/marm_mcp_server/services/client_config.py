"""Registry and writers for wiring MARM into supported AI client configs.

Shared by the Console's Connections page and `marm-memory fast-start-http
--client`. Every writer merges into the client's existing file, backs it up
first, and reads it back to confirm the entry landed. No client file is ever
overwritten if it fails to parse, and no key value is ever written to disk.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils.subprocess_flags import no_window_flags
from . import skill_install

try:
    import tomllib  # type: ignore[import-not-found,unused-ignore]
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]

try:
    import yaml
except ModuleNotFoundError:
    yaml = None  # type: ignore[assignment]

CLIENT_IDS = [
    "claude",
    "claude-desktop",
    "cursor",
    "vscode",
    "codex",
    "grok",
    "hermes",
    "opencode",
    "cline",
    "antigravity",
    "qwen",
    "devin",
    "kiro",
    "zed",
]
CLIENT_ALIASES = {"windsurf": "devin"}
TRANSPORTS = ("http", "stdio", "docker-stdio")
SCOPES = ("user", "project")
SERVER_NAME = "marm-memory"
STDIO_COMMAND = "marm-mcp-stdio"


class ClientNotFound(Exception):
    """Raised for an unknown client id."""


class ClientNotConfigurable(Exception):
    """Raised when configure cannot proceed: no binary, manual-only auth, unreadable or conflicting file."""


class InvalidRequest(ValueError):
    """Raised for a bad transport, scope, or project path."""


class _Unreadable(Exception):
    """A client file exists but is not in a shape MARM will edit."""


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


@dataclass(frozen=True)
class ClientSpec:
    id: str
    label: str
    binary: str | None
    format: str  # "cli" | "json" | "toml" | "yaml"
    container_key: str | None
    user_path: Callable[[], Path | None]
    project_path: str | None
    markers: Callable[[], list[Path]]
    typed: bool = False
    http_key: str = "url"
    http_type: str = "http"
    stdio_type: str = "stdio"
    auth_ref: str | None = None


REGISTRY: dict[str, ClientSpec] = {
    spec.id: spec
    for spec in [
        ClientSpec(
            "claude",
            "Claude Code",
            "claude",
            "cli",
            "mcpServers",
            _under_home(".claude.json"),
            ".mcp.json",
            _markers(".claude"),
            typed=True,
            auth_ref="${MARM_API_KEY}",
        ),
        ClientSpec(
            "claude-desktop",
            "Claude Desktop",
            None,
            "json",
            "mcpServers",
            _claude_desktop_path,
            None,
            _claude_desktop_markers,
        ),
        ClientSpec(
            "cursor",
            "Cursor",
            "cursor",
            "json",
            "mcpServers",
            _under_home(".cursor", "mcp.json"),
            ".cursor/mcp.json",
            _markers(".cursor"),
            auth_ref="${env:MARM_API_KEY}",
        ),
        ClientSpec(
            "vscode",
            "VS Code",
            "code",
            "json",
            "servers",
            _vscode_config_path,
            ".vscode/mcp.json",
            lambda: [_vscode_config_path().parent],
            typed=True,
            auth_ref="${input:marm-api-key}",
        ),
        ClientSpec(
            "codex",
            "Codex CLI",
            "codex",
            "toml",
            None,
            _under_home(".codex", "config.toml"),
            ".codex/config.toml",
            _markers(".codex"),
        ),
        ClientSpec(
            "grok",
            "Grok Build",
            "grok",
            "toml",
            None,
            _under_home(".grok", "config.toml"),
            ".grok/config.toml",
            _markers(".grok"),
        ),
        ClientSpec(
            "hermes",
            "Hermes Agent",
            "hermes",
            "yaml",
            "mcp_servers",
            lambda: hermes_home() / "config.yaml",
            None,
            lambda: [hermes_home()],
            auth_ref="${MARM_API_KEY}",
        ),
        ClientSpec(
            "opencode",
            "OpenCode",
            "opencode",
            "json",
            "mcp",
            _opencode_path,
            "opencode.json",
            lambda: [opencode_home()],
            typed=True,
            http_type="remote",
            stdio_type="local",
            auth_ref="{env:MARM_API_KEY}",
        ),
        ClientSpec(
            "cline",
            "Cline",
            "cline",
            "json",
            "mcpServers",
            cline_mcp_settings_path,
            None,
            _cline_markers,
            typed=True,
            http_type="streamableHttp",
        ),
        ClientSpec(
            "antigravity",
            "Antigravity",
            "agy",
            "json",
            "mcpServers",
            _antigravity_path,
            ".agents/mcp_config.json",
            _antigravity_markers,
            http_key="serverUrl",
        ),
        ClientSpec(
            "qwen",
            "Qwen Code",
            "qwen",
            "json",
            "mcpServers",
            _under_home(".qwen", "settings.json"),
            ".qwen/settings.json",
            _markers(".qwen"),
            http_key="httpUrl",
        ),
        ClientSpec(
            "devin",
            "Devin",
            "devin",
            "json",
            "mcpServers",
            _devin_path,
            None,
            _devin_markers,
        ),
        ClientSpec(
            "kiro",
            "Kiro",
            "kiro",
            "json",
            "mcpServers",
            _under_home(".kiro", "settings", "mcp.json"),
            ".kiro/settings/mcp.json",
            _markers(".kiro"),
            auth_ref="${MARM_API_KEY}",
        ),
        ClientSpec(
            "zed",
            "Zed",
            "zed",
            "jsonc",
            "context_servers",
            _zed_path,
            None,
            lambda: [zed_home()],
        ),
    ]
}

_GROK_CLAUDE_NOTE = "Grok Build also reads Claude Code's MCP list, so MARM may already load here. Connect adds its own entry."
_ANTIGRAVITY_SHARED_NOTE = "The Antigravity IDE, CLI and 2.0 app read this same file."
_CURSOR_SHARED_NOTE = "The Cursor CLI (agent) reads this same file. Servers in the global file load without approval; project servers ask you to approve them on first use."
_CLINE_SHARED_NOTE = (
    "The Cline extensions in VS Code and JetBrains read this same file."
)
_DEVIN_SHARED_NOTE = "Devin CLI and the Devin Local agent in Devin Desktop (formerly Windsurf) read this same file. The older Cascade agent keeps its own file under ~/.codeium, which MARM does not write."
_ZED_NOTE = "Zed lists MARM under Settings, AI, MCP Servers. Open the file from Zed with the zed: open settings file action."
_OPENCODE_RELOAD_NOTE = "Start a new OpenCode session to load it."
_OPENCODE_COMMENTS_NOTE = "This file had comments or trailing commas, which MARM does not keep. The original is saved next to it as a .marm-backup copy."
_HERMES_RELOAD_NOTE = "Run /reload-mcp in Hermes, or start a new session, to load it."
_CODEX_TRUST_NOTE = (
    "Codex only loads a project's .codex/config.toml for projects it trusts."
)


def _spec(client_id: str) -> ClientSpec:
    spec = REGISTRY.get(CLIENT_ALIASES.get(client_id, client_id))
    if spec is None:
        raise ClientNotFound(client_id)
    return spec


def _scopes(spec: ClientSpec) -> list[str]:
    return ["user", "project"] if spec.project_path else ["user"]


def _stdio_command() -> str:
    return shutil.which(STDIO_COMMAND) or STDIO_COMMAND


def _docker_parts(tag: str, data_dir: Path | None) -> tuple[str, list[str]]:
    from . import docker_commands

    try:
        plan = docker_commands.stdio_command(tag=tag, data_dir=data_dir)
    except docker_commands.DockerCommandError as exc:
        raise ClientNotConfigurable(str(exc)) from exc
    arguments = plan["arguments"]
    return arguments[0], list(arguments[1:])


def _build_entry(
    spec: ClientSpec,
    transport: str,
    url: str,
    auth_required: bool,
    docker_tag: str = "latest",
    docker_data_dir: Path | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any]
    if transport == "http":
        if spec.format == "toml":
            entry = {"url": url}
            if auth_required:
                entry["bearer_token_env_var"] = "MARM_API_KEY"
            return entry
        entry = {"type": spec.http_type} if spec.typed else {}
        entry[spec.http_key] = url
        if spec.id == "opencode":
            entry["oauth"] = False
        if auth_required and spec.auth_ref:
            entry["headers"] = {"Authorization": f"Bearer {spec.auth_ref}"}
        return entry
    args: list[str] = []
    if transport == "stdio":
        command = _stdio_command()
    elif transport == "docker-stdio":
        command, args = _docker_parts(docker_tag, docker_data_dir)
    else:
        raise InvalidRequest(f"Unknown transport: {transport}")
    entry = {"type": spec.stdio_type} if spec.typed else {}
    entry["command"] = command
    entry["args"] = args
    return entry


def build_entry(
    client_id: str,
    transport: str,
    url: str,
    auth_required: bool,
    *,
    docker_tag: str = "latest",
    docker_data_dir: Path | None = None,
) -> dict[str, Any]:
    return _build_entry(
        _spec(client_id), transport, url, auth_required, docker_tag, docker_data_dir
    )


def _unavailable(spec: ClientSpec, transport: str, auth_required: bool) -> str | None:
    if spec.user_path() is None:
        return f"{spec.label} is not available on this platform."
    return transport_unavailable(spec, transport, auth_required)


def transport_unavailable(
    spec: ClientSpec, transport: str, auth_required: bool
) -> str | None:
    if transport == "http":
        if spec.id == "claude-desktop":
            return "Needs the mcp-remote bridge. Use STDIO."
        if auth_required and spec.id in {"cline", "devin", "zed"}:
            name = "Cline CLI" if spec.id == "cline" else spec.label
            return (
                f"MARM has not confirmed that {name} expands environment variables in headers, "
                "so HTTP with a key must be added by hand. Use STDIO, which needs no key."
            )
        if auth_required and spec.id in {"antigravity", "qwen"}:
            return (
                f"{spec.label} cannot reference an environment variable in a header, "
                "so HTTP with a key must be added by hand. Use STDIO, which needs no key."
            )
    return None


def _auth_note(spec: ClientSpec) -> str:
    if spec.id == "vscode":
        return (
            "VS Code will prompt for your MARM API key the first time it connects. "
            "Run `marm-memory key path` to find your key."
        )
    return f"{spec.label} reads MARM_API_KEY from your environment. Run `marm-memory key path` to find your key."


def _configure_notes(
    spec: ClientSpec, transport: str, scope: str, auth_required: bool
) -> list[str]:
    notes: list[str] = []
    if transport == "http" and auth_required:
        notes.append(_auth_note(spec))
    if transport == "stdio" and shutil.which(STDIO_COMMAND) is None:
        notes.append(
            f"{STDIO_COMMAND} was not found on PATH, so the entry uses the bare command name. "
            "If the agent cannot start it, replace it with the full path."
        )
    if spec.id == "codex" and scope == "project":
        notes.append(_CODEX_TRUST_NOTE)
    if spec.id == "hermes":
        notes.append(_HERMES_RELOAD_NOTE)
    if spec.id == "opencode":
        notes.append(_OPENCODE_RELOAD_NOTE)
    return notes


def _detected(spec: ClientSpec) -> bool:
    return any(path.is_dir() for path in spec.markers()) or (
        spec.binary is not None and shutil.which(spec.binary) is not None
    )


def _command_name(value: str) -> str:
    return Path(value.replace("\\", "/")).stem.lower()


def _native_entry(spec: ClientSpec, entry: dict) -> dict:
    """OpenCode keeps the command and its arguments in one list; every other client uses the flat shape."""
    if spec.id != "opencode" or "command" not in entry:
        return entry
    native = {k: v for k, v in entry.items() if k not in {"command", "args"}}
    native["command"] = [entry["command"], *(entry.get("args") or [])]
    return native


def _flat_command(entry: dict) -> dict:
    command = entry.get("command")
    if not isinstance(command, list) or not command:
        return entry
    flat = {k: v for k, v in entry.items() if k != "command"}
    flat["command"], flat["args"] = command[0], command[1:]
    return flat


def _same_value(key: str, current: Any, expected: Any) -> bool:
    if key == "command" and isinstance(current, str) and isinstance(expected, str):
        return _command_name(current) == _command_name(expected)
    if key == "args" and current is None:
        current = []
    if isinstance(current, str) and isinstance(expected, str):
        return current.replace("://localhost:", "://127.0.0.1:") == expected
    return bool(current == expected)


def _matches(current: Any, expected: dict) -> bool:
    """Extra keys a user added (e.g. Codex `enabled = true`) do not make an entry stale."""
    return isinstance(current, dict) and all(
        _same_value(key, current.get(key), value) for key, value in expected.items()
    )


def detect_transport(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    command = entry.get("command")
    if isinstance(command, str):
        return "docker-stdio" if _command_name(command) == "docker" else "stdio"
    if any(key in entry for key in ("url", "httpUrl", "serverUrl")):
        return "http"
    return None


def _project_root(project: str | None) -> Path:
    if not project:
        raise InvalidRequest("Project scope needs a project path.")
    root = Path(project)
    if not root.is_absolute() or not root.is_dir():
        raise InvalidRequest(f"Project path must be an existing directory: {project}")
    return Path(os.path.realpath(root))


def _target(spec: ClientSpec, scope: str, project: str | None) -> Path | None:
    if scope not in SCOPES:
        raise InvalidRequest(f"Unknown scope: {scope}")
    if scope not in _scopes(spec):
        raise InvalidRequest(f"{spec.label} supports the user scope only.")
    if scope == "user":
        return spec.user_path()
    assert spec.project_path is not None
    root = _project_root(project)
    target = root / spec.project_path
    if spec.id == "opencode" and (root / "opencode.jsonc").exists():
        target = root / "opencode.jsonc"
    if not Path(os.path.realpath(target)).is_relative_to(root):
        raise ClientNotConfigurable(
            f"{target} resolves outside the project; refusing to use it."
        )
    return target


def _strip_jsonc(text: str) -> str:
    """Drop comments and trailing commas outside strings so OpenCode's JSONC files parse."""
    chunks: list[str] = []
    plain: list[str] = []

    def flush() -> None:
        chunks.append(re.sub(r",(\s*[}\]])", r"\1", "".join(plain)))
        plain.clear()

    i, n = 0, len(text)
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            flush()
            chunks.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            plain.append(text[i])
            i += 1
    flush()
    return "".join(chunks)


def _parse_json(spec: ClientSpec, text: str) -> Any:
    if spec.id == "opencode" or spec.format == "jsonc":
        text = _strip_jsonc(text.lstrip("\ufeff"))
    return json.loads(text)


def _servers_path(spec: ClientSpec, content: dict) -> tuple[str, ...]:
    """OpenCode 2 nests servers under mcp.servers; OpenCode 1 lists them directly under mcp."""
    if spec.id == "opencode":
        mcp = content.get("mcp")
        if isinstance(mcp, dict):
            servers, timeout = mcp.get("servers"), mcp.get("timeout")
            if isinstance(servers, dict) and servers.get("type") not in {
                "local",
                "remote",
            }:
                return ("mcp", "servers")
            if servers is None and isinstance(timeout, dict) and "type" not in timeout:
                return ("mcp", "servers")
    assert spec.container_key is not None
    return (spec.container_key,)


def _with_servers(spec: ClientSpec, content: dict, servers: dict) -> dict:
    path = _servers_path(spec, content)
    if len(path) == 1:
        return {**content, path[0]: servers}
    return {**content, "mcp": {**content["mcp"], "servers": servers}}


def _load_json(spec: ClientSpec, path: Path) -> tuple[dict, dict]:
    """Return (content, servers container). Raises _Unreadable for shapes MARM will not edit."""
    if not path.exists():
        return {}, {}
    try:
        content = _parse_json(spec, path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise _Unreadable(f"{spec.label} config could not be read: {path}") from exc
    if not isinstance(content, dict):
        raise _Unreadable(f"{spec.label} config is not a JSON object: {path}")
    container: Any = content
    for key in _servers_path(spec, content):
        container = container.get(key)
        if container is None:
            container = {}
            break
        if not isinstance(container, dict):
            raise _Unreadable(f"{spec.label} config has an unexpected '{key}' value.")
    if spec.id == "vscode" and not isinstance(content.get("inputs", []), list):
        raise _Unreadable("VS Code config has an unexpected 'inputs' value.")
    return content, container


_CODEX_TABLE_MARKERS = (
    f"[mcp_servers.{SERVER_NAME}]",
    f'[mcp_servers."{SERVER_NAME}"]',
)


def _codex_entry(path: Path, spec: ClientSpec) -> dict | None:
    """The table as a dict, {} when it exists but cannot be parsed, None when absent."""
    try:
        text = _read_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise _Unreadable(f"{spec.label} config could not be read: {path}") from exc
    if not any(marker in text for marker in _CODEX_TABLE_MARKERS):
        return None
    if tomllib is None:
        return {}
    try:
        current = tomllib.loads(text).get("mcp_servers", {}).get(SERVER_NAME)
    except tomllib.TOMLDecodeError:
        return {}
    return current if isinstance(current, dict) else {}


def _flat_transport(entry: dict) -> dict:
    """Cline's own installer nests the connection under "transport"; read it as the flat shape."""
    transport = entry.get("transport")
    if not isinstance(transport, dict):
        return entry
    return {**{k: v for k, v in entry.items() if k != "transport"}, **transport}


def _read_current(spec: ClientSpec, path: Path) -> tuple[dict | None, bool, str | None]:
    """Return (current entry, file exists, unreadable reason)."""
    if not path.exists():
        return None, False, None
    try:
        if spec.format == "toml":
            return _codex_entry(path, spec), True, None
        if spec.format == "yaml":
            return _yaml_entry(path, spec), True, None
        _content, container = _load_json(spec, path)
    except _Unreadable as exc:
        return None, True, str(exc)
    current = container.get(SERVER_NAME)
    if spec.id == "cline" and isinstance(current, dict):
        current = _flat_transport(current)
    if spec.id == "opencode" and isinstance(current, dict):
        current = _flat_command(current)
    return (current if isinstance(current, dict) else None), True, None


_MCP_HEADER = re.compile(
    r"^((?:mcp_servers|\"mcp_servers\"|'mcp_servers')[ \t]*):(.*)$"
)
_TRAILING_COMMENT = re.compile(r"\s+#.*$")
_LINES = re.compile(r"[^\n]*\n|[^\n]+")


def _yaml_entry(path: Path, spec: ClientSpec) -> dict | None:
    """The entry as a dict, {} when present in an unexpected shape, None when absent."""
    if yaml is None:
        raise _Unreadable(
            f"PyYAML is not installed, so {spec.label} config cannot be read."
        )
    try:
        content = yaml.safe_load(_read_text(path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise _Unreadable(f"{spec.label} config could not be read: {path}") from exc
    if content is None:
        return None
    if not isinstance(content, dict):
        raise _Unreadable(f"{spec.label} config is not a YAML mapping: {path}")
    servers = content.get("mcp_servers")
    if servers is None:
        return None
    if not isinstance(servers, dict):
        raise _Unreadable(f"{spec.label} config has an unexpected 'mcp_servers' value.")
    if SERVER_NAME not in servers:
        return None
    current = servers[SERVER_NAME]
    return current if isinstance(current, dict) else {}


def _yaml_emit(entry: dict, indent: int) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    for key, value in entry.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.extend(_yaml_emit(value, indent + 2))
        else:
            lines.append(f"{pad}{key}: {json.dumps(value)}")
    return lines


def _yaml_block(entry: dict, indent: int) -> list[str]:
    return [f"{' ' * indent}{SERVER_NAME}:", *_yaml_emit(entry, indent + 2)]


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _split_yaml(text: str) -> tuple[list[str], str]:
    return _LINES.findall(text), ("\r\n" if "\r\n" in text else "\n")


def _yaml_header(lines: list[str]) -> tuple[int, str, str, str] | None:
    """Line index, inline value, trailing comment, and the key text exactly as written."""
    for index, line in enumerate(lines):
        match = _MCP_HEADER.match(line.rstrip("\r\n"))
        if match:
            body = match.group(2)
            found = _TRAILING_COMMENT.search(body)
            comment = found.group(0) if found else ""
            rest = (body[: found.start()] if found else body).strip()
            return index, rest, comment, match.group(1)
    return None


def _region_end(lines: list[str], header: int) -> int:
    for index in range(header + 1, len(lines)):
        if _is_content(lines[index]) and _indent_of(lines[index]) == 0:
            return index
    return len(lines)


def _child_indent(lines: list[str], header: int, end: int) -> int:
    for index in range(header + 1, end):
        if _is_content(lines[index]):
            return _indent_of(lines[index]) or 2
    return 2


def _yaml_insert(text: str, entry: dict) -> str:
    lines, newline = _split_yaml(text)
    found = _yaml_header(lines)
    if found is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += newline
        head = [newline] if lines and lines[-1].strip() else []
        new = ["mcp_servers:", *_yaml_block(entry, 2)]
        return "".join([*lines, *head, *(line + newline for line in new)])
    header, rest, comment, key_text = found
    if rest and rest not in {"{}", "null", "~"}:
        raise _Unreadable("The mcp_servers section uses a layout MARM will not edit.")
    if not lines[header].endswith("\n"):
        lines[header] += newline
    indent = 2 if rest else _child_indent(lines, header, _region_end(lines, header))
    if rest:
        lines[header] = f"{key_text}:{comment}{newline}"
    block = [line + newline for line in _yaml_block(entry, indent)]
    return "".join([*lines[: header + 1], *block, *lines[header + 1 :]])


def _yaml_remove(text: str) -> str:
    lines, newline = _split_yaml(text)
    found = _yaml_header(lines)
    if found is None or found[1]:
        raise _Unreadable("The mcp_servers section uses a layout MARM will not edit.")
    header, _rest, comment, key_text = found
    end = _region_end(lines, header)
    indent = _child_indent(lines, header, end)
    name = re.escape(SERVER_NAME)
    key = re.compile(rf"^ {{{indent}}}(?:{name}|\"{name}\"|'{name}')[ \t]*:")
    start = next((i for i in range(header + 1, end) if key.match(lines[i])), None)
    if start is None:
        raise _Unreadable("The mcp_servers section uses a layout MARM will not edit.")
    stop = start + 1
    while stop < end and (
        not _is_content(lines[stop]) or _indent_of(lines[stop]) > indent
    ):
        stop += 1
    while stop > start + 1 and not _is_content(lines[stop - 1]):
        stop -= 1
    del lines[start:stop]
    end -= stop - start
    if not any(_is_content(line) for line in lines[header + 1 : end]):
        lines[header] = f"{key_text}: {{}}{comment}{newline}"
    return "".join(lines)


def _yaml_doc(text: str) -> dict:
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def _expected_yaml_doc(before: dict, entry: dict | None) -> dict:
    """The whole document as it should read after the edit: only MARM's entry differs."""
    servers = before.get("mcp_servers")
    servers = dict(servers) if isinstance(servers, dict) else {}
    if entry is None:
        servers.pop(SERVER_NAME, None)
    else:
        servers[SERVER_NAME] = entry
    return {**before, "mcp_servers": servers}


def _write_yaml(path: Path, entry: dict | None, spec: ClientSpec) -> None:
    """Insert or remove the MARM entry as text, then re-parse the whole file and restore the original if anything else moved."""
    original = _read_text(path) if path.exists() else None
    try:
        updated = (
            _yaml_insert(original or "", entry)
            if entry is not None
            else _yaml_remove(original or "")
        )
    except _Unreadable as exc:
        raise ClientNotConfigurable(f"{exc} Edit {path} by hand.") from exc
    _backup(path)
    _atomic_write_text(path, updated)
    try:
        expected = _expected_yaml_doc(_yaml_doc(original or ""), entry)
        landed = _yaml_doc(_read_text(path)) == expected
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        landed = False
    if landed:
        return
    if original is None:
        with contextlib.suppress(OSError):
            path.unlink()
    else:
        _atomic_write_text(path, original)
    raise ClientNotConfigurable(
        f"MARM could not change {path} safely, so it was left as it was. Edit it by hand."
    )


def _skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n:
        if text[i] in " \t\r\n\ufeff":
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                raise _Unreadable("The file has an unterminated comment.")
            i = end + 2
        else:
            break
    return i


def _string_end(text: str, i: int) -> int:
    j = i + 1
    while j < len(text) and text[j] != '"':
        j += 2 if text[j] == "\\" else 1
    if j >= len(text):
        raise _Unreadable("The file has an unterminated string.")
    return j + 1


def _value_end(text: str, i: int) -> int:
    i = _skip_ws(text, i)
    if i >= len(text):
        raise _Unreadable("The file ends where a value was expected.")
    if text[i] == '"':
        return _string_end(text, i)
    if text[i] == "{":
        return _object_members(text, i)[1] + 1
    if text[i] == "[":
        i += 1
        while True:
            i = _skip_ws(text, i)
            if i >= len(text):
                raise _Unreadable("The file ends inside a list.")
            if text[i] == "]":
                return i + 1
            i = _skip_ws(text, _value_end(text, i))
            if i < len(text) and text[i] == ",":
                i += 1
    start = i
    while (
        i < len(text)
        and text[i] not in " \t\r\n,}]"
        and not text.startswith(("//", "/*"), i)
    ):
        i += 1
    if i == start:
        raise _Unreadable("The file has an unexpected token.")
    return i


def _object_members(
    text: str, start: int
) -> tuple[list[tuple[str, int, int, int]], int]:
    """Members as (key, key start, value start, value end), plus the closing brace index."""
    members: list[tuple[str, int, int, int]] = []
    i = start + 1
    while True:
        i = _skip_ws(text, i)
        if i >= len(text):
            raise _Unreadable("The file ends inside an object.")
        if text[i] == "}":
            return members, i
        if text[i] != '"':
            raise _Unreadable("The file has an unexpected token.")
        key_end = _string_end(text, i)
        try:
            key = json.loads(text[i:key_end])
        except json.JSONDecodeError as exc:
            raise _Unreadable("The file has an invalid key.") from exc
        colon = _skip_ws(text, key_end)
        if colon >= len(text) or text[colon] != ":":
            raise _Unreadable("The file has a key with no value.")
        value_start = _skip_ws(text, colon + 1)
        value_end = _value_end(text, value_start)
        members.append((key, i, value_start, value_end))
        i = _skip_ws(text, value_end)
        if i < len(text) and text[i] == ",":
            i += 1
        elif i >= len(text) or text[i] != "}":
            raise _Unreadable("The file has a missing comma.")


def _root_object(text: str) -> tuple[int, list[tuple[str, int, int, int]], int]:
    start = _skip_ws(text, 0)
    if start >= len(text) or text[start] != "{":
        raise _Unreadable("The file is not a JSON object.")
    members, close = _object_members(text, start)
    if _skip_ws(text, close + 1) != len(text):
        raise _Unreadable("The file has content after its object.")
    return start, members, close


def _line_start(text: str, i: int) -> int:
    return text.rfind("\n", 0, i) + 1


def _first_on_line(text: str, i: int) -> bool:
    return not text[_line_start(text, i) : i].strip()


def _line_indent(text: str, i: int) -> str:
    start = _line_start(text, i)
    end = text.find("\n", start)
    line = text[start : len(text) if end == -1 else end]
    return line[: len(line) - len(line.lstrip(" \t"))]


def _indents(text: str, obj_start: int, members: list) -> tuple[str, str, str]:
    """Indent of the object's line, of its members, and one indent step."""
    parent = _line_indent(text, obj_start)
    if members and _first_on_line(text, members[0][1]):
        member = _line_indent(text, members[0][1])
    else:
        member = parent + "  "
    unit = (
        member[len(parent) :]
        if member.startswith(parent) and len(member) > len(parent)
        else "  "
    )
    return parent, member, unit


def _entry_block(entry: dict, indent: str, unit: str, newline: str) -> str:
    lines = json.dumps(entry, indent=unit, ensure_ascii=False).split("\n")
    return f'"{SERVER_NAME}": ' + (newline + indent).join(lines)


def _add_member(text: str, obj_start: int, members: list, close: int, render) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    parent, member, unit = _indents(text, obj_start, members)
    body = render(member, unit, newline)
    edits: list[tuple[int, str]] = []
    if _first_on_line(text, close):
        edits.append((_line_start(text, close), member + body + newline))
    else:
        edits.append((close, newline + member + body + newline + parent))
    if members and text[_skip_ws(text, members[-1][3])] != ",":
        edits.append((members[-1][3], ","))
    for pos, inserted in sorted(edits, key=lambda edit: edit[0], reverse=True):
        text = text[:pos] + inserted + text[pos:]
    return text


def _jsonc_put(text: str, key: str, entry: dict) -> str:
    if not text.strip():
        content = {key: {SERVER_NAME: entry}}
        return json.dumps(content, indent=2, ensure_ascii=False) + "\n"
    root_start, members, root_close = _root_object(text)
    servers = next((m for m in members if m[0] == key), None)
    if servers is None:

        def render_root(member: str, unit: str, newline: str) -> str:
            inner = member + unit
            block = _entry_block(entry, inner, unit, newline)
            return f'"{key}": {{' + newline + inner + block + newline + member + "}"

        return _add_member(text, root_start, members, root_close, render_root)
    if text[servers[2]] != "{":
        raise _Unreadable(f"The {key} setting is not an object.")
    inner_members, close = _object_members(text, servers[2])
    existing = next((m for m in inner_members if m[0] == SERVER_NAME), None)
    if existing is not None:
        newline = "\r\n" if "\r\n" in text else "\n"
        _parent, member, unit = _indents(text, servers[2], inner_members)
        block = _entry_block(entry, member, unit, newline)
        return text[: existing[2]] + block.split(": ", 1)[1] + text[existing[3] :]
    return _add_member(
        text,
        servers[2],
        inner_members,
        close,
        lambda member, unit, newline: _entry_block(entry, member, unit, newline),
    )


def _jsonc_remove(text: str, key: str) -> str:
    _root_start, members, _root_close = _root_object(text)
    servers = next((m for m in members if m[0] == key), None)
    if servers is None or text[servers[2]] != "{":
        raise _Unreadable(f"There is no {key} object to remove from.")
    inner, close = _object_members(text, servers[2])
    index = next((i for i, m in enumerate(inner) if m[0] == SERVER_NAME), None)
    if index is None:
        raise _Unreadable("MARM is not in this file.")
    _name, start, _value_start, end = inner[index]
    if (
        len(inner) == 1
        and not text[servers[2] + 1 : start].strip()
        and text[end:close].strip() in {"", ","}
    ):
        return text[: servers[2] + 1] + text[close:]
    edits: list[tuple[int, int]] = []
    after = _skip_ws(text, end)
    if after < len(text) and text[after] == ",":
        span_end = after + 1
    else:
        span_end = end
        if index > 0:
            comma = _skip_ws(text, inner[index - 1][3])
            edits.append((comma, comma + 1))
    line_end = text.find("\n", span_end)
    line_end = len(text) if line_end == -1 else line_end + 1
    if _first_on_line(text, start) and not text[span_end:line_end].strip():
        edits.append((_line_start(text, start), line_end))
    else:
        edits.append((start, span_end))
    for first, last in sorted(edits, reverse=True):
        text = text[:first] + text[last:]
    return text


def _jsonc_doc(text: str) -> dict:
    if not text.strip():
        return {}
    data = json.loads(_strip_jsonc(text.lstrip("\ufeff")))
    return data if isinstance(data, dict) else {}


def _expected_jsonc_doc(before: dict, key: str, entry: dict | None) -> dict:
    servers = before.get(key)
    servers = dict(servers) if isinstance(servers, dict) else {}
    if entry is None:
        servers.pop(SERVER_NAME, None)
    else:
        servers[SERVER_NAME] = entry
    return {**before, key: servers}


def _write_jsonc(path: Path, entry: dict | None, spec: ClientSpec) -> None:
    """Insert or remove the MARM entry as text, then re-parse the whole file and restore the original if anything else moved."""
    original = _read_text(path) if path.exists() else None
    key = spec.container_key or "mcpServers"
    try:
        updated = (
            _jsonc_put(original or "", key, entry)
            if entry is not None
            else _jsonc_remove(original or "", key)
        )
    except _Unreadable as exc:
        raise ClientNotConfigurable(f"{exc} Edit {path} by hand.") from exc
    _backup(path)
    _atomic_write_text(path, updated)
    try:
        expected = _expected_jsonc_doc(_jsonc_doc(original or ""), key, entry)
        landed = _jsonc_doc(_read_text(path)) == expected
    except (OSError, ValueError):
        landed = False
    if landed:
        return
    if original is None:
        with contextlib.suppress(OSError):
            path.unlink()
    else:
        _atomic_write_text(path, original)
    raise ClientNotConfigurable(
        f"MARM could not change {path} safely, so it was left as it was. Edit it by hand."
    )


def _read_text(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _atomic_write_text(path: Path, text: str) -> None:
    """Write through symlinks to the real target so dotfile-manager links survive."""
    real = Path(os.path.realpath(path))
    tmp = real.with_name(real.name + ".tmp")
    try:
        real.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, real)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise ClientNotConfigurable(
            f"Could not write {path}: {exc.strerror or exc}"
        ) from exc


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".marm-backup")


def _backup(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.copy2(path, _backup_path(path))
    except OSError as exc:
        raise ClientNotConfigurable(
            f"Could not back up {path}: {exc.strerror or exc}"
        ) from exc


def _write_json(path: Path, content: dict) -> None:
    _atomic_write_text(path, json.dumps(content, indent=2, ensure_ascii=False) + "\n")


def _plan_action(state: str, exists: bool) -> str:
    if state == "configured":
        return "none"
    if state == "missing":
        return "add" if exists else "create"
    return "replace"


def run_cli_subprocess(
    argv: list[str], timeout: float = 20.0
) -> subprocess.CompletedProcess:
    """Run a client CLI command. The sole seam tests replace to avoid a real subprocess."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
        creationflags=no_window_flags(),
    )


def _run_cli(argv: list[str], label: str, *, check: bool = True) -> None:
    try:
        proc = run_cli_subprocess(argv)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClientNotConfigurable(f"'{label}' failed: {exc}") from exc
    if check and proc.returncode != 0:
        raise ClientNotConfigurable(
            f"'{label}' exited {proc.returncode}: {proc.stderr.strip()}"
        )


def _toml_value(value: Any) -> str:
    return json.dumps(value)


def _append_codex(path: Path, entry: dict) -> None:
    text = _read_text(path) if path.exists() else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    if text and not text.endswith("\n"):
        text += newline
    lines = ["", f"[mcp_servers.{SERVER_NAME}]"]
    lines.extend(f"{key} = {_toml_value(value)}" for key, value in entry.items())
    _atomic_write_text(path, text + newline.join(lines) + newline)


def _is_cli_method(spec: ClientSpec, scope: str) -> bool:
    return spec.format == "cli" and scope == "user"


def configure(
    client_id: str,
    url: str,
    auth_required: bool,
    transport: str = "http",
    scope: str = "user",
    project: str | None = None,
    dry_run: bool = False,
    *,
    docker_tag: str = "latest",
    docker_data_dir: Path | None = None,
) -> dict:
    spec = _spec(client_id)
    if transport not in TRANSPORTS:
        raise InvalidRequest(f"Unknown transport: {transport}")
    path = _target(spec, scope, project)
    reason = _unavailable(spec, transport, auth_required)
    if reason or path is None:
        raise ClientNotConfigurable(reason or f"{spec.label} is not available here.")
    if scope == "user" and not _detected(spec):
        raise ClientNotConfigurable(f"{spec.label} was not detected on this machine.")
    entry = _build_entry(
        spec, transport, url, auth_required, docker_tag, docker_data_dir
    )
    current, exists, problem = _read_current(spec, path)
    if problem:
        raise ClientNotConfigurable(problem)
    state = (
        "missing"
        if current is None
        else ("configured" if _matches(current, entry) else "different")
    )
    if spec.format in {"toml", "yaml"} and state == "different":
        shape = (
            f"[mcp_servers.{SERVER_NAME}] table"
            if spec.format == "toml"
            else f"mcp_servers.{SERVER_NAME} entry"
        )
        raise ClientNotConfigurable(
            f"{path} already has a {shape} that differs; edit it manually."
        )
    action = _plan_action(state, exists)
    use_cli = _is_cli_method(spec, scope)
    result: dict[str, Any] = {
        "client": spec.id,
        "transport": transport,
        "scope": scope,
        "config_path": str(path),
        "action": action,
        "entry": _native_entry(spec, entry),
        "backup_path": str(_backup_path(path))
        if (not use_cli and exists and action != "none")
        else None,
        "method": "cli" if use_cli else "file",
        "notes": _configure_notes(spec, transport, scope, auth_required),
    }
    if (
        spec.id == "opencode"
        and exists
        and action != "none"
        and _strip_jsonc(_read_text(path)) != _read_text(path)
    ):
        result["notes"].append(_OPENCODE_COMMENTS_NOTE)
    if dry_run:
        return result
    binary = shutil.which("claude") if use_cli else None
    if use_cli and binary is None:
        raise ClientNotConfigurable("The 'claude' binary was not found on PATH.")
    if action == "none":
        result["written"] = False
        result["verified"] = True
        return result
    if binary is not None:
        if state == "different":
            _run_cli(
                [binary, "mcp", "remove", "--scope", "user", SERVER_NAME],
                "claude mcp remove",
                check=False,
            )
        _run_cli(
            [
                binary,
                "mcp",
                "add-json",
                "--scope",
                "user",
                SERVER_NAME,
                json.dumps(entry),
            ],
            "claude mcp add-json",
        )
    elif spec.format == "toml":
        _backup(path)
        _append_codex(path, entry)
    elif spec.format == "yaml":
        _write_yaml(path, entry, spec)
    elif spec.format == "jsonc":
        _write_jsonc(path, entry, spec)
    else:
        content, container = _load_json(spec, path)
        _backup(path)
        new_content = _with_servers(
            spec, content, {**container, SERVER_NAME: _native_entry(spec, entry)}
        )
        if spec.id == "vscode" and transport == "http" and auth_required:
            inputs = list(new_content.get("inputs", []))
            if not any(
                isinstance(item, dict) and item.get("id") == "marm-api-key"
                for item in inputs
            ):
                inputs.append(
                    {
                        "id": "marm-api-key",
                        "type": "promptString",
                        "description": "MARM API key",
                        "password": True,
                    }
                )
            new_content["inputs"] = inputs
        _write_json(path, new_content)
    written, _exists, _problem = _read_current(spec, path)
    result["written"] = True
    result["verified"] = _matches(written, entry) or (
        spec.format == "toml" and tomllib is None and written is not None
    )
    return result


def remove(
    client_id: str,
    scope: str = "user",
    project: str | None = None,
    dry_run: bool = False,
) -> dict:
    spec = _spec(client_id)
    path = _target(spec, scope, project)
    if path is None:
        raise ClientNotConfigurable(f"{spec.label} is not available on this platform.")
    current, exists, problem = _read_current(spec, path)
    if problem:
        raise ClientNotConfigurable(problem)
    action = "remove" if current is not None else "none"
    use_cli = spec.format in {"cli", "toml"} and scope == "user"
    result: dict[str, Any] = {
        "client": spec.id,
        "config_path": str(path),
        "action": action,
        "backup_path": str(_backup_path(path))
        if (not use_cli and exists and action == "remove")
        else None,
        "method": "cli" if use_cli else "file",
    }
    if action == "remove" and spec.format == "toml" and scope == "project":
        raise ClientNotConfigurable(
            f"The {spec.label} cannot edit a project file. Remove the [mcp_servers.{SERVER_NAME}] table from {path} by hand."
        )
    if dry_run:
        return result
    if action == "none":
        result["written"] = False
        result["verified"] = True
        return result
    if use_cli:
        binary = shutil.which(spec.binary) if spec.binary else None
        if binary is None:
            raise ClientNotConfigurable(
                f"The '{spec.binary}' binary was not found on PATH. "
                + (
                    f"Remove the [mcp_servers.{SERVER_NAME}] table from {path} by hand."
                    if spec.format == "toml"
                    else ""
                )
            )
        argv = [binary, "mcp", "remove"]
        if spec.format == "cli":
            argv += ["--scope", "user"]
        _run_cli([*argv, SERVER_NAME], f"{spec.binary} mcp remove")
    elif spec.format == "yaml":
        _write_yaml(path, None, spec)
    elif spec.format == "jsonc":
        _write_jsonc(path, None, spec)
    else:
        content, container = _load_json(spec, path)
        _backup(path)
        remaining = {k: v for k, v in container.items() if k != SERVER_NAME}
        _write_json(path, _with_servers(spec, content, remaining))
    remaining_entry, _exists, _problem = _read_current(spec, path)
    result["written"] = True
    result["verified"] = remaining_entry is None
    return result


def read_entry(
    client_id: str, scope: str = "user", project: str | None = None
) -> dict | None:
    """The MARM entry as it actually sits in the client's file, for the probe."""
    spec = _spec(client_id)
    path = _target(spec, scope, project)
    if path is None:
        return None
    current, _exists, problem = _read_current(spec, path)
    if problem:
        raise ClientNotConfigurable(problem)
    return current


def _scope_state(
    client_id: str,
    scope: str,
    project: str | None,
    url: str | None,
    auth_required: bool,
) -> dict[str, Any]:
    spec = _spec(client_id)
    path = _target(spec, scope, project)
    current, exists, problem = (
        _read_current(spec, path) if path else (None, False, None)
    )
    transport = detect_transport(current)
    if problem:
        state = "unreadable"
    elif current is None:
        state = "missing"
    elif url is None:
        state = "configured"
    elif transport == "docker-stdio":
        state = (
            "configured"
            if STDIO_COMMAND in (current.get("args") or [])
            else "different"
        )
    elif transport is None:
        state = "different"
    else:
        expected = _build_entry(spec, transport, url, auth_required)
        state = "configured" if _matches(current, expected) else "different"
    return {
        "scope": scope,
        "project": project if scope == "project" else None,
        "config_path": str(path) if path else None,
        "config_exists": exists,
        "state": state,
        "transport_detected": transport,
        "current_entry": current,
    }


def status(
    client_id: str,
    scope: str = "user",
    project: str | None = None,
    url: str | None = None,
    auth_required: bool = False,
) -> dict[str, Any]:
    """One ScopeState. Without a url the entry counts as configured whenever it exists."""
    return _scope_state(client_id, scope, project, url, auth_required)


def _claude_has_project_entry(path: Path) -> bool:
    spec = REGISTRY["claude"]
    try:
        content, _container = _load_json(spec, path)
    except _Unreadable:
        return False
    projects = content.get("projects")
    if not isinstance(projects, dict):
        return False
    return any(
        isinstance(project, dict)
        and isinstance(project.get("mcpServers"), dict)
        and SERVER_NAME in project["mcpServers"]
        for project in projects.values()
    )


def _claude_has_user_entry() -> bool:
    path = REGISTRY["claude"].user_path()
    if path is None or not path.exists():
        return False
    try:
        _content, container = _load_json(REGISTRY["claude"], path)
    except _Unreadable:
        return False
    return SERVER_NAME in container


def _agent_notes(
    spec: ClientSpec, detected: bool, state: dict[str, Any], auth_required: bool
) -> list[str]:
    notes: list[str] = []
    if spec.id == "claude":
        path = spec.user_path()
        if state["state"] == "missing" and path and _claude_has_project_entry(path):
            notes.append(
                "MARM is already set up for some projects. Configuring adds it for every project."
            )
        if detected and shutil.which("claude") is None:
            notes.append(
                "The 'claude' binary was not found on PATH. Every-project setup needs it; "
                "a single project writes .mcp.json directly."
            )
    if auth_required and spec.id not in {
        "claude-desktop",
        "antigravity",
        "qwen",
        "cline",
        "devin",
        "zed",
    }:
        notes.append(_auth_note(spec))
    if spec.id == "codex":
        notes.append(_CODEX_TRUST_NOTE)
    if spec.id == "cline":
        notes.append(_CLINE_SHARED_NOTE)
    if spec.id == "cursor":
        notes.append(_CURSOR_SHARED_NOTE)
    if spec.id == "devin":
        notes.append(_DEVIN_SHARED_NOTE)
    if spec.id == "zed":
        notes.append(_ZED_NOTE)
    if spec.id == "antigravity":
        notes.append(_ANTIGRAVITY_SHARED_NOTE)
    if spec.id == "grok" and state["state"] == "missing" and _claude_has_user_entry():
        notes.append(_GROK_CLAUDE_NOTE)
    return notes


def _skill_state(client_id: str) -> dict[str, bool]:
    supported = client_id in skill_install.AGENTS
    return {
        "supported": supported,
        "installed": skill_install.is_installed(client_id) if supported else False,
    }


def _agent(client_id: str, url: str, auth_required: bool) -> dict[str, Any]:
    spec = REGISTRY[client_id]
    detected = _detected(spec)
    user = _scope_state(client_id, "user", None, url, auth_required)
    unavailable = {
        transport: reason
        for transport in TRANSPORTS
        if (reason := _unavailable(spec, transport, auth_required))
    }
    return {
        "id": spec.id,
        "label": spec.label,
        "detected": detected,
        "transports": list(TRANSPORTS),
        "scopes": _scopes(spec),
        "user": user,
        "skill": _skill_state(client_id),
        "notes": _agent_notes(spec, detected, user, auth_required),
        "unavailable": unavailable,
    }


def list_agents(url: str, auth_required: bool) -> list[dict]:
    return [_agent(client_id, url, auth_required) for client_id in CLIENT_IDS]
