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
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..utils.subprocess_flags import no_window_flags
from .client_registry import REGISTRY, ClientSpec
from .client_text_edit import (
    SERVER_NAME,
    _expected_jsonc_doc,
    _expected_yaml_doc,
    _jsonc_doc,
    _jsonc_put,
    _jsonc_remove,
    _strip_jsonc,
    _Unreadable,
    _yaml_insert,
    _yaml_remove,
)

try:
    import tomllib  # type: ignore[import-not-found,unused-ignore]
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]

try:
    import yaml  # type: ignore[import-untyped,unused-ignore]
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
STDIO_COMMAND = "marm-mcp-stdio"


class ClientNotFound(Exception):
    """Raised for an unknown client id."""


class ClientNotConfigurable(Exception):
    """Raised when configure cannot proceed: no binary, manual-only auth, unreadable or conflicting file."""


class InvalidRequest(ValueError):
    """Raised for a bad transport, scope, or project path."""


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


def _yaml_doc(text: str) -> dict:
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


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
