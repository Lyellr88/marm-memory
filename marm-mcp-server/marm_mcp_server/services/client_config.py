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

CLIENT_IDS = [
    "claude",
    "claude-desktop",
    "cursor",
    "vscode",
    "codex",
    "gemini",
    "qwen",
    "windsurf",
    "kiro",
    "xai",
]
DOCKER_STDIO_CLIENT_IDS = [client_id for client_id in CLIENT_IDS if client_id != "xai"]
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


def _devin_path() -> Path:
    if _platform() == "win32":
        return _appdata() / "devin" / "mcp_config.json"
    return _home() / ".config" / "devin" / "mcp_config.json"


def _codeium_path() -> Path:
    return _home() / ".codeium" / "windsurf" / "mcp_config.json"


def _windsurf_path() -> Path:
    devin, codeium = _devin_path(), _codeium_path()
    if devin.exists():
        return devin
    if codeium.exists():
        return codeium
    if devin.parent.is_dir() and not codeium.parent.is_dir():
        return devin
    return codeium


def _under_home(*parts: str) -> Callable[[], Path]:
    return lambda: _home().joinpath(*parts)


def _markers(*parts: str) -> Callable[[], list[Path]]:
    return lambda: [_home().joinpath(*parts)]


@dataclass(frozen=True)
class ClientSpec:
    id: str
    label: str
    binary: str | None
    format: str  # "cli" | "json" | "toml"
    container_key: str | None
    user_path: Callable[[], Path | None]
    project_path: str | None
    markers: Callable[[], list[Path]]
    typed: bool = False
    http_key: str = "url"
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
            "gemini",
            "Gemini CLI",
            "gemini",
            "json",
            "mcpServers",
            _under_home(".gemini", "settings.json"),
            ".gemini/settings.json",
            _markers(".gemini"),
            http_key="httpUrl",
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
            "windsurf",
            "Windsurf",
            "windsurf",
            "json",
            "mcpServers",
            _windsurf_path,
            None,
            lambda: [_devin_path().parent, _codeium_path().parent],
            http_key="serverUrl",
            auth_ref="${env:MARM_API_KEY}",
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
    ]
}

_XAI_PAYLOAD = {
    "type": "mcp",
    "server_label": "marm-memory",
    "server_url": "https://YOUR_PUBLIC_HTTPS_URL/mcp",
    "authorization": "Bearer YOUR_KEY",
}
_XAI_NOTE = (
    "Grok's Responses API needs a public HTTPS URL, not a loopback address. "
    "Expose MARM publicly, then send this tool payload with your MARM API key."
)
_CODEX_TRUST_NOTE = (
    "Codex only loads a project's .codex/config.toml for projects it trusts."
)


def _spec(client_id: str) -> ClientSpec:
    spec = REGISTRY.get(client_id)
    if spec is None:
        if client_id == "xai":
            raise ClientNotConfigurable(
                "Grok (xAI API) needs a public HTTPS URL; configure it manually."
            )
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
        if spec.id == "codex":
            entry = {"url": url}
            if auth_required:
                entry["bearer_token_env_var"] = "MARM_API_KEY"
            return entry
        entry = {"type": "http"} if spec.typed else {}
        entry[spec.http_key] = url
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
    entry = {"type": "stdio"} if spec.typed else {}
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
        if auth_required and spec.id in {"gemini", "qwen"}:
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
    return notes


def _detected(spec: ClientSpec) -> bool:
    return any(path.is_dir() for path in spec.markers()) or (
        spec.binary is not None and shutil.which(spec.binary) is not None
    )


def _command_name(value: str) -> str:
    return Path(value.replace("\\", "/")).stem.lower()


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
    if not Path(os.path.realpath(target)).is_relative_to(root):
        raise ClientNotConfigurable(
            f"{target} resolves outside the project; refusing to use it."
        )
    return target


def _load_json(spec: ClientSpec, path: Path) -> tuple[dict, dict]:
    """Return (content, servers container). Raises _Unreadable for shapes MARM will not edit."""
    if not path.exists():
        return {}, {}
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise _Unreadable(f"{spec.label} config could not be read: {path}") from exc
    if not isinstance(content, dict):
        raise _Unreadable(f"{spec.label} config is not a JSON object: {path}")
    container = content.get(spec.container_key)
    if container is None:
        container = {}
    elif not isinstance(container, dict):
        raise _Unreadable(
            f"{spec.label} config has an unexpected '{spec.container_key}' value."
        )
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


def _read_current(spec: ClientSpec, path: Path) -> tuple[dict | None, bool, str | None]:
    """Return (current entry, file exists, unreadable reason)."""
    if not path.exists():
        return None, False, None
    try:
        if spec.format == "toml":
            return _codex_entry(path, spec), True, None
        _content, container = _load_json(spec, path)
    except _Unreadable as exc:
        return None, True, str(exc)
    current = container.get(SERVER_NAME)
    return (current if isinstance(current, dict) else None), True, None


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
    if spec.format == "toml" and state == "different":
        raise ClientNotConfigurable(
            f"{path} already has a [mcp_servers.{SERVER_NAME}] table that differs; edit it manually."
        )
    action = _plan_action(state, exists)
    use_cli = _is_cli_method(spec, scope)
    result: dict[str, Any] = {
        "client": spec.id,
        "transport": transport,
        "scope": scope,
        "config_path": str(path),
        "action": action,
        "entry": entry,
        "backup_path": str(_backup_path(path))
        if (not use_cli and exists and action != "none")
        else None,
        "method": "cli" if use_cli else "file",
        "notes": _configure_notes(spec, transport, scope, auth_required),
    }
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
    else:
        content, container = _load_json(spec, path)
        _backup(path)
        new_content = dict(content)
        new_content[spec.container_key] = {**container, SERVER_NAME: entry}
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
            f"The Codex CLI cannot edit a project file. Remove the [mcp_servers.{SERVER_NAME}] table from {path} by hand."
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
    else:
        content, container = _load_json(spec, path)
        _backup(path)
        remaining = {k: v for k, v in container.items() if k != SERVER_NAME}
        _write_json(path, {**content, spec.container_key: remaining})
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
    if client_id == "xai":
        return _xai_state()
    return _scope_state(client_id, scope, project, url, auth_required)


def _xai_state() -> dict[str, Any]:
    return {
        "scope": "user",
        "project": None,
        "config_path": None,
        "config_exists": False,
        "state": "missing",
        "transport_detected": None,
        "current_entry": None,
        "expected_entry": _XAI_PAYLOAD,
    }


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
    if auth_required and spec.id not in {"claude-desktop", "gemini", "qwen"}:
        notes.append(_auth_note(spec))
    if spec.id == "codex":
        notes.append(_CODEX_TRUST_NOTE)
    return notes


def _skill_state(client_id: str) -> dict[str, bool]:
    supported = client_id in skill_install.AGENTS
    return {
        "supported": supported,
        "installed": skill_install.is_installed(client_id) if supported else False,
    }


def _agent(client_id: str, url: str, auth_required: bool) -> dict[str, Any]:
    if client_id == "xai":
        return {
            "id": "xai",
            "label": "Grok (xAI API)",
            "detected": False,
            "transports": [],
            "scopes": ["user"],
            "user": _xai_state(),
            "skill": {"supported": False, "installed": False},
            "notes": [_XAI_NOTE],
            "unavailable": {},
        }
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
