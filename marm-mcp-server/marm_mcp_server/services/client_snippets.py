"""Paste-ready config snippets and agent CLI commands for the Console's Manual tab.

Nothing here touches disk or reads a key. Entries come from `client_config.build_entry`, so a
snippet always matches what Connect would write, with key references and never key values.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import client_config, docker_commands
from .client_config import (
    REGISTRY,
    SCOPES,
    SERVER_NAME,
    STDIO_COMMAND,
    TRANSPORTS,
    ClientSpec,
    InvalidRequest,
)

OS_NAMES = ("windows", "macos", "linux")

_DATA_DIRS = {
    "windows": "C:\\Users\\you\\.marm",
    "macos": "/Users/you/.marm",
    "linux": "/home/you/.marm",
}
_OS_APPDATA_DISPLAY: dict[str, dict[str, str | None]] = {
    "vscode": {
        "windows": "%APPDATA%\\Code\\User\\mcp.json",
        "macos": "~/Library/Application Support/Code/User/mcp.json",
        "linux": "~/.config/Code/User/mcp.json",
    },
    "claude-desktop": {
        "windows": "%APPDATA%\\Claude\\claude_desktop_config.json",
        "macos": "~/Library/Application Support/Claude/claude_desktop_config.json",
        "linux": None,
    },
    "hermes": {
        "windows": "%LOCALAPPDATA%\\hermes\\config.yaml",
        "macos": "~/.hermes/config.yaml",
        "linux": "~/.hermes/config.yaml",
    },
    "windsurf": {
        "windows": "%APPDATA%\\devin\\mcp_config.json",
        "macos": "~/.config/devin/mcp_config.json",
        "linux": "~/.config/devin/mcp_config.json",
    },
}
_NO_CLI = {
    "cursor": "Cursor has no command for adding a server. Use the config file snippet.",
    "windsurf": "Windsurf has no command for adding a server. Use the config file snippet.",
    "kiro": "Kiro has no command for adding a server. Use the config file snippet.",
    "claude-desktop": "Claude Desktop has no command for adding a server. Use the config file snippet.",
}
_TOML_TABLE = f"[mcp_servers.{SERVER_NAME}]"
_KEYED_SNIPPET_NOTE = "The config file snippet reads the key from MARM_API_KEY, so it never lands in the file. Use that snippet."


def host_os() -> str:
    if sys.platform == "win32":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def _check_os(os_name: str) -> None:
    if os_name not in OS_NAMES:
        raise InvalidRequest(f"Unknown os: {os_name}")


def _spec(client_id: str) -> ClientSpec:
    spec = REGISTRY.get(client_id)
    if spec is None:
        raise client_config.ClientNotFound(client_id)
    return spec


def _sep(os_name: str, text: str) -> str:
    return text.replace("/", "\\") if os_name == "windows" else text


def _user_path(spec: ClientSpec, os_name: str) -> str:
    if spec.id in _OS_APPDATA_DISPLAY:
        path = _OS_APPDATA_DISPLAY[spec.id][os_name]
        if path is None:
            raise InvalidRequest(f"{spec.label} is not available on {os_name}.")
        return path
    host = spec.user_path()
    assert host is not None
    relative = host.relative_to(client_config._home())
    return _sep(os_name, "/".join(("~", *relative.parts)))


def _config_path(spec: ClientSpec, os_name: str, scope: str) -> str:
    if scope == "user":
        return _user_path(spec, os_name)
    assert spec.project_path is not None
    return _sep(os_name, f"<project>/{spec.project_path}")


def _validate(
    spec: ClientSpec, os_name: str, transport: str, scope: str, auth_required: bool
) -> None:
    _check_os(os_name)
    if scope not in SCOPES:
        raise InvalidRequest(f"Unknown scope: {scope}")
    if scope == "project" and not spec.project_path:
        raise InvalidRequest(f"{spec.label} supports the user scope only.")
    if transport not in TRANSPORTS:
        raise InvalidRequest(f"Unknown transport: {transport}")
    reason = client_config.transport_unavailable(spec, transport, auth_required)
    if reason:
        raise InvalidRequest(reason)


def _docker_argv(os_name: str, tag: str) -> list[str]:
    """The Docker STDIO argv with this OS's placeholder data folder and no host-specific user."""
    try:
        plan = docker_commands.stdio_command(
            tag=tag, data_dir=Path(tempfile.gettempdir())
        )
    except docker_commands.DockerCommandError as exc:
        raise InvalidRequest(str(exc)) from exc
    argv: list[str] = []
    skip = False
    for argument in plan["arguments"]:
        if skip:
            skip = False
        elif argument == "--user":
            skip = True
        elif argument == "--entrypoint" and os_name == "linux":
            argv.extend(["--user", "1000:1000", argument])
        elif argument.startswith("type=bind,src="):
            argv.append(
                f"type=bind,src={_DATA_DIRS[os_name]},dst={docker_commands.CONTAINER_DATA_DIR}"
            )
        else:
            argv.append(argument)
    return argv


def _entry(
    client_id: str,
    os_name: str,
    transport: str,
    url: str,
    auth_required: bool,
    docker_tag: str,
) -> dict[str, Any]:
    entry = client_config.build_entry(
        client_id,
        transport,
        url,
        auth_required,
        docker_tag=docker_tag,
        docker_data_dir=Path(tempfile.gettempdir()),
    )
    if transport == "stdio":
        entry["command"] = STDIO_COMMAND
    elif transport == "docker-stdio":
        entry["args"] = _docker_argv(os_name, docker_tag)[1:]
    return entry


def _toml_text(entry: dict[str, Any]) -> str:
    lines = [_TOML_TABLE, *(f"{k} = {json.dumps(v)}" for k, v in entry.items())]
    return "\n".join(lines) + "\n"


def _yaml_text(entry: dict[str, Any]) -> str:
    return "\n".join(["mcp_servers:", *client_config._yaml_block(entry, 2)]) + "\n"


def _json_text(
    spec: ClientSpec, entry: dict[str, Any], transport: str, auth: bool
) -> str:
    content: dict[str, Any] = {}
    if spec.id == "vscode" and transport == "http" and auth:
        content["inputs"] = [
            {
                "id": "marm-api-key",
                "type": "promptString",
                "description": "MARM API key",
                "password": True,
            }
        ]
    content[spec.container_key or "mcpServers"] = {SERVER_NAME: entry}
    return json.dumps(content, indent=2, ensure_ascii=False) + "\n"


def _snippet_notes(
    spec: ClientSpec, os_name: str, transport: str, scope: str, auth_required: bool
) -> list[str]:
    notes: list[str] = []
    if transport == "http" and auth_required:
        notes.append(client_config._auth_note(spec))
    if transport == "stdio":
        finder = "where" if os_name == "windows" else "which"
        notes.append(
            f"GUI apps often start with a shorter PATH than your terminal. If {spec.label} cannot start "
            f"{STDIO_COMMAND}, replace it with the full path from `{finder} {STDIO_COMMAND}`."
        )
    if transport == "docker-stdio":
        notes.append(
            "Replace the data folder in the mount argument with an absolute path to your MARM data "
            "directory. A leading ~ is not expanded here."
        )
        if os_name == "linux":
            notes.append(
                "Replace 1000:1000 with your own user and group ids from `id -u` and `id -g`."
            )
    if spec.id == "claude" and scope == "user":
        notes.append(
            "Claude Code keeps other settings in this file. Prefer `claude mcp add`, or merge only the marm-memory entry."
        )
    if spec.id == "codex" and scope == "project":
        notes.append(client_config._CODEX_TRUST_NOTE)
    if spec.id == "windsurf":
        notes.append(
            "Older Windsurf installs use ~/.codeium/windsurf/mcp_config.json instead."
        )
    if spec.id == "hermes":
        notes.append(
            "If HERMES_HOME is set, the file is $HERMES_HOME/config.yaml. Run /reload-mcp in Hermes after saving."
        )
    return notes


def snippet(
    client_id: str,
    os_name: str,
    transport: str,
    scope: str,
    url: str,
    auth_required: bool,
    *,
    docker_tag: str = "latest",
) -> dict[str, Any]:
    spec = _spec(client_id)
    _validate(spec, os_name, transport, scope, auth_required)
    entry = _entry(client_id, os_name, transport, url, auth_required, docker_tag)
    text = {
        "toml": lambda: _toml_text(entry),
        "yaml": lambda: _yaml_text(entry),
    }.get(spec.format, lambda: _json_text(spec, entry, transport, auth_required))()
    return {
        "client": spec.id,
        "os": os_name,
        "path": _config_path(spec, os_name, scope),
        "format": spec.format if spec.format in {"toml", "yaml"} else "json",
        "text": text,
        "notes": _snippet_notes(spec, os_name, transport, scope, auth_required),
    }


def _join(argv: list[str], os_name: str) -> str:
    return docker_commands.shell_command(argv, windows=os_name == "windows")


def _stdio_argv(transport: str, os_name: str, docker_tag: str) -> list[str]:
    if transport == "docker-stdio":
        return _docker_argv(os_name, docker_tag)
    return [STDIO_COMMAND]


def _claude_command(
    transport: str,
    scope: str,
    url: str,
    auth_required: bool,
    argv: list[str],
    os_name: str,
) -> str:
    base = ["claude", "mcp", "add", "--transport"]
    if transport == "http":
        command = _join([*base, "http", "--scope", scope, SERVER_NAME, url], os_name)
        if auth_required:
            command += ' --header "Authorization: Bearer ${MARM_API_KEY}"'
        return command
    return _join([*base, "stdio", "--scope", scope, SERVER_NAME, "--", *argv], os_name)


def _codex_command(
    transport: str, url: str, auth_required: bool, argv: list[str], os_name: str
) -> str:
    if transport == "http":
        command = _join(["codex", "mcp", "add", SERVER_NAME, "--url", url], os_name)
        if auth_required:
            command += " --bearer-token-env-var MARM_API_KEY"
        return command
    return _join(["codex", "mcp", "add", SERVER_NAME, "--", *argv], os_name)


def _gemini_command(
    binary: str, transport: str, scope: str, url: str, argv: list[str], os_name: str
) -> str:
    if transport == "http":
        return _join(
            [
                binary,
                "mcp",
                "add",
                "--transport",
                "http",
                "--scope",
                scope,
                SERVER_NAME,
                url,
            ],
            os_name,
        )
    tail = ["--", *argv] if transport == "docker-stdio" else argv
    return _join([binary, "mcp", "add", "--scope", scope, SERVER_NAME, *tail], os_name)


def _grok_command(
    transport: str, scope: str, url: str, argv: list[str], os_name: str
) -> str:
    base = ["grok", "mcp", "add"]
    where = ["--scope", "project"] if scope == "project" else []
    if transport == "http":
        return _join([*base, "--transport", "http", *where, SERVER_NAME, url], os_name)
    return _join([*base, *where, SERVER_NAME, "--", *argv], os_name)


def _hermes_command(transport: str, url: str, argv: list[str], os_name: str) -> str:
    base = ["hermes", "mcp", "add", SERVER_NAME]
    if transport == "http":
        return _join([*base, "--url", url], os_name)
    rest = ["--args", *argv[1:]] if argv[1:] else []
    return _join([*base, "--command", argv[0], *rest], os_name)


def _agy_command(transport: str, url: str, argv: list[str], os_name: str) -> str:
    if transport == "http":
        return _join(["agy", "mcp", "add", SERVER_NAME, "--type", "http", url], os_name)
    return _join(
        ["agy", "mcp", "add", SERVER_NAME, "--type", "stdio", "--", *argv], os_name
    )


def _one_command(
    client_id: str,
    transport: str,
    scope: str,
    url: str,
    auth_required: bool,
    os_name: str,
    docker_tag: str,
) -> tuple[str | None, str]:
    spec = REGISTRY[client_id]
    if client_id in _NO_CLI:
        return None, _NO_CLI[client_id]
    reason = client_config.transport_unavailable(spec, transport, auth_required)
    if reason:
        return None, reason
    argv = _stdio_argv(transport, os_name, docker_tag)
    if client_id == "claude":
        where = (
            "for every project"
            if scope == "user"
            else "in the current project (writes .mcp.json)"
        )
        return _claude_command(
            transport, scope, url, auth_required, argv, os_name
        ), f"Adds MARM {where}."
    if client_id == "codex":
        if scope == "project":
            return (
                None,
                "The Codex CLI only edits your user config. Use the config file snippet for one project.",
            )
        return _codex_command(
            transport, url, auth_required, argv, os_name
        ), "Adds MARM for every project."
    if client_id == "hermes":
        if scope == "project":
            return None, "Hermes Agent has one user config. Use the user scope."
        if transport == "http" and auth_required:
            return None, _KEYED_SNIPPET_NOTE
        return (
            _hermes_command(transport, url, argv, os_name),
            "Adds MARM to your Hermes config. Then run /reload-mcp.",
        )
    if client_id == "grok":
        if transport == "http" and auth_required:
            return (
                None,
                _KEYED_SNIPPET_NOTE,
            )
        return _grok_command(transport, scope, url, argv, os_name), (
            "Adds MARM for every project."
            if scope == "user"
            else "Adds MARM to the current project (writes .grok/config.toml)."
        )
    if client_id == "antigravity":
        if scope == "project":
            return (
                None,
                "The Antigravity CLI adds servers to your user config. Use the config file snippet for one project.",
            )
        return _agy_command(
            transport, url, argv, os_name
        ), "Adds MARM for every project."
    if client_id == "qwen":
        return _gemini_command(client_id, transport, scope, url, argv, os_name), (
            "Adds MARM for every project."
            if scope == "user"
            else "Adds MARM to the current project."
        )
    if scope == "project":
        return (
            None,
            "VS Code adds servers to your user profile only. Use the config file snippet for one project.",
        )
    if transport == "http" and auth_required:
        return (
            None,
            "The key needs a prompt input that only the config file snippet defines. Use that snippet.",
        )
    entry = client_config.build_entry(
        "vscode",
        transport,
        url,
        auth_required,
        docker_data_dir=Path(tempfile.gettempdir()),
    )
    if transport == "stdio":
        entry["command"] = STDIO_COMMAND
    elif transport == "docker-stdio":
        entry["args"] = argv[1:]
    payload = json.dumps({"name": SERVER_NAME, **entry}, separators=(",", ":"))
    note = "Adds MARM to your VS Code user profile."
    if os_name == "windows":
        note += " In cmd or PowerShell the single quotes may not work, so use the config file snippet instead."
    return f"code --add-mcp '{payload}'", note


def agent_commands(
    transport: str,
    scope: str,
    url: str,
    auth_required: bool,
    *,
    os_name: str | None = None,
    docker_tag: str = "latest",
) -> list[dict[str, Any]]:
    os_name = os_name or host_os()
    _check_os(os_name)
    if transport not in TRANSPORTS:
        raise InvalidRequest(f"Unknown transport: {transport}")
    if scope not in SCOPES:
        raise InvalidRequest(f"Unknown scope: {scope}")
    commands = []
    for client_id in client_config.CLIENT_IDS:
        command, note = _one_command(
            client_id, transport, scope, url, auth_required, os_name, docker_tag
        )
        commands.append(
            {
                "client": client_id,
                "label": REGISTRY[client_id].label,
                "command": command,
                "note": note,
            }
        )
    return commands
