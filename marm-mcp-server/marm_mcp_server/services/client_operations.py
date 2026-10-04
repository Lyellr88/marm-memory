from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import skill_install
from .client_config import (
    _ANTIGRAVITY_SHARED_NOTE,
    _CLINE_SHARED_NOTE,
    _CODEX_TRUST_NOTE,
    _CURSOR_SHARED_NOTE,
    _DEVIN_SHARED_NOTE,
    _GROK_CLAUDE_NOTE,
    _OPENCODE_COMMENTS_NOTE,
    _ZED_NOTE,
    CLIENT_IDS,
    STDIO_COMMAND,
    TRANSPORTS,
    ClientNotConfigurable,
    InvalidRequest,
    _atomic_write_text,
    _auth_note,
    _backup,
    _backup_path,
    _build_entry,
    _configure_notes,
    _detected,
    _load_json,
    _matches,
    _native_entry,
    _read_current,
    _read_text,
    _run_cli,
    _scopes,
    _spec,
    _target,
    _unavailable,
    _with_servers,
    _write_json,
    _write_jsonc,
    _write_yaml,
    detect_transport,
    tomllib,
)
from .client_registry import REGISTRY, ClientSpec
from .client_text_edit import SERVER_NAME, _strip_jsonc, _Unreadable


def _plan_action(state: str, exists: bool) -> str:
    if state == "configured":
        return "none"
    if state == "missing":
        return "add" if exists else "create"
    return "replace"


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
