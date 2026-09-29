"""Writer behavior on real temp files for marm_mcp_server.services.client_config."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from marm_mcp_server.services import client_config, docker_commands

URL = "http://127.0.0.1:8001/mcp"
SECRET = "sk-marm-test-secret-value"

# Directory whose existence marks a client as installed, relative to the fake home.
DETECT_DIRS = {
    "claude": ".claude",
    "claude-desktop": "AppData/Roaming/Claude",
    "cursor": ".cursor",
    "vscode": "AppData/Roaming/Code/User",
    "codex": ".codex",
    "grok": ".grok",
    "hermes": "AppData/Local/hermes",
    "opencode": ".config/opencode",
    "cline": ".cline",
    "antigravity": ".gemini/config",
    "qwen": ".qwen",
    "devin": "AppData/Roaming/devin",
    "kiro": ".kiro",
}

USER_FILES = {
    "claude-desktop": "AppData/Roaming/Claude/claude_desktop_config.json",
    "cursor": ".cursor/mcp.json",
    "vscode": "AppData/Roaming/Code/User/mcp.json",
    "codex": ".codex/config.toml",
    "grok": ".grok/config.toml",
    "hermes": "AppData/Local/hermes/config.yaml",
    "opencode": ".config/opencode/opencode.json",
    "cline": ".cline/data/settings/cline_mcp_settings.json",
    "antigravity": ".gemini/config/mcp_config.json",
    "qwen": ".qwen/settings.json",
    "devin": "AppData/Roaming/devin/mcp_config.json",
    "kiro": ".kiro/settings/mcp.json",
}

PROJECT_FILES = {
    "claude": ".mcp.json",
    "cursor": ".cursor/mcp.json",
    "vscode": ".vscode/mcp.json",
    "codex": ".codex/config.toml",
    "grok": ".grok/config.toml",
    "opencode": "opencode.json",
    "antigravity": ".agents/mcp_config.json",
    "qwen": ".qwen/settings.json",
    "kiro": ".kiro/settings/mcp.json",
}

CONTAINER = {
    "vscode": "servers",
    "codex": "mcp_servers",
    "grok": "mcp_servers",
    "opencode": "mcp",
}
TYPED = {"claude", "vscode", "cline"}
HTTP_TYPE = {"cline": "streamableHttp"}
URL_KEY = {
    "antigravity": "serverUrl",
    "qwen": "httpUrl",
}
AUTH_REF = {
    "claude": "${MARM_API_KEY}",
    "cursor": "${env:MARM_API_KEY}",
    "vscode": "${input:marm-api-key}",
    "hermes": "${MARM_API_KEY}",
    "opencode": "{env:MARM_API_KEY}",
    "kiro": "${MARM_API_KEY}",
}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point every path the module resolves at a tmp dir; never touch the real home."""
    monkeypatch.setattr(client_config, "_home", lambda: tmp_path)
    monkeypatch.setattr(client_config, "_platform", lambda: "win32")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("CLINE_DIR", raising=False)
    monkeypatch.delenv("CLINE_DATA_DIR", raising=False)
    monkeypatch.delenv("CLINE_MCP_SETTINGS_PATH", raising=False)
    monkeypatch.setattr(client_config.shutil, "which", lambda name: None)
    return tmp_path


def detect(home: Path, client: str) -> None:
    (home / DETECT_DIRS[client]).mkdir(parents=True, exist_ok=True)


def expected_entry(client: str, transport: str, auth: bool, docker_args=None) -> dict:
    if client == "opencode":
        if transport == "http":
            entry = {"type": "remote", "url": URL, "oauth": False}
            if auth:
                entry["headers"] = {"Authorization": "Bearer {env:MARM_API_KEY}"}
            return entry
        command = (
            ["marm-mcp-stdio"] if transport == "stdio" else ["docker", *docker_args]
        )
        return {"type": "local", "command": command}
    if transport == "http":
        if client in {"codex", "grok"}:
            entry: dict = {"url": URL}
            if auth:
                entry["bearer_token_env_var"] = "MARM_API_KEY"
            return entry
        entry = {"type": HTTP_TYPE.get(client, "http")} if client in TYPED else {}
        entry[URL_KEY.get(client, "url")] = URL
        if auth and client in AUTH_REF:
            entry["headers"] = {"Authorization": f"Bearer {AUTH_REF[client]}"}
        return entry
    entry = {"type": "stdio"} if client in TYPED else {}
    if transport == "stdio":
        entry.update({"command": "marm-mcp-stdio", "args": []})
    else:
        entry.update({"command": "docker", "args": docker_args})
    return entry


def read_marm_entry(home: Path, client: str, path: Path) -> dict:
    if client == "hermes":
        yaml = pytest.importorskip("yaml")
        return yaml.safe_load(path.read_text(encoding="utf-8"))["mcp_servers"][
            "marm-memory"
        ]
    if client in {"codex", "grok"}:
        tomllib = pytest.importorskip("tomllib")
        return tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"][
            "marm-memory"
        ]
    return json.loads(path.read_text(encoding="utf-8"))[
        CONTAINER.get(client, "mcpServers")
    ]["marm-memory"]


def docker_args_for(tmp_path: Path) -> list[str]:
    return docker_commands.stdio_command(data_dir=tmp_path)["arguments"][1:]


def unavailable(client: str, transport: str, auth: bool) -> bool:
    return (client == "claude-desktop" and transport == "http") or (
        client in {"antigravity", "qwen", "cline", "devin"}
        and transport == "http"
        and auth
    )


# --- Entry shapes: every client x transport x scope -----------------------------


@pytest.mark.parametrize("auth", [False, True])
@pytest.mark.parametrize("transport", ["http", "stdio", "docker-stdio"])
@pytest.mark.parametrize("client", sorted(USER_FILES))
def test_user_scope_entry_shape_written_to_the_client_file(
    isolated_home, client, transport, auth
):
    detect(isolated_home, client)
    kwargs = {"docker_data_dir": isolated_home} if transport == "docker-stdio" else {}
    if unavailable(client, transport, auth):
        with pytest.raises(client_config.ClientNotConfigurable):
            client_config.configure(client, URL, auth, transport=transport, **kwargs)
        assert not (isolated_home / USER_FILES[client]).exists()
        return

    result = client_config.configure(client, URL, auth, transport=transport, **kwargs)

    path = isolated_home / USER_FILES[client]
    want = expected_entry(client, transport, auth, docker_args_for(isolated_home))
    assert result["written"] is True
    assert result["verified"] is True
    assert result["method"] == "file"
    assert result["scope"] == "user"
    assert result["transport"] == transport
    assert Path(result["config_path"]) == path
    assert result["entry"] == want
    assert read_marm_entry(isolated_home, client, path) == want


@pytest.mark.parametrize("auth", [False, True])
@pytest.mark.parametrize("transport", ["http", "stdio", "docker-stdio"])
@pytest.mark.parametrize("client", sorted(PROJECT_FILES))
def test_project_scope_entry_shape_written_inside_the_project(
    isolated_home, client, transport, auth
):
    project = isolated_home / "repo"
    project.mkdir()
    kwargs = {"docker_data_dir": isolated_home} if transport == "docker-stdio" else {}
    if unavailable(client, transport, auth):
        with pytest.raises(client_config.ClientNotConfigurable):
            client_config.configure(
                client,
                URL,
                auth,
                transport=transport,
                scope="project",
                project=str(project),
                **kwargs,
            )
        return

    result = client_config.configure(
        client,
        URL,
        auth,
        transport=transport,
        scope="project",
        project=str(project),
        **kwargs,
    )

    path = project / PROJECT_FILES[client]
    want = expected_entry(client, transport, auth, docker_args_for(isolated_home))
    assert result["verified"] is True
    assert result["scope"] == "project"
    assert read_marm_entry(isolated_home, client, path) == want


@pytest.mark.parametrize("transport", ["http", "stdio", "docker-stdio"])
def test_claude_user_scope_goes_through_the_cli_for_every_transport(
    isolated_home, monkeypatch, transport
):
    detect(isolated_home, "claude")
    monkeypatch.setattr(
        client_config.shutil,
        "which",
        lambda name: str(isolated_home / "claude.exe") if name == "claude" else None,
    )
    calls: list[list[str]] = []

    def fake_runner(argv, timeout=20.0):
        calls.append(argv)
        path = isolated_home / ".claude.json"
        data = json.loads(path.read_text()) if path.exists() else {}
        data.setdefault("mcpServers", {})["marm-memory"] = json.loads(argv[-1])
        path.write_text(json.dumps(data))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(client_config, "run_cli_subprocess", fake_runner)
    kwargs = {"docker_data_dir": isolated_home} if transport == "docker-stdio" else {}

    result = client_config.configure("claude", URL, True, transport=transport, **kwargs)

    want = expected_entry("claude", transport, True, docker_args_for(isolated_home))
    assert result["method"] == "cli"
    assert result["verified"] is True
    assert result["backup_path"] is None
    assert json.loads(calls[0][6]) == want
    assert calls[0][1:6] == ["mcp", "add-json", "--scope", "user", "marm-memory"]


# --- Generic merge behavior (cursor stands in for the JSON writer) -------------------


def test_cursor_create_new_file(isolated_home):
    detect(isolated_home, "cursor")

    result = client_config.configure("cursor", URL, False)
    path = isolated_home / ".cursor" / "mcp.json"

    assert result["action"] == "create"
    assert result["backup_path"] is None
    assert json.loads(path.read_text())["mcpServers"]["marm-memory"] == {"url": URL}


def test_cursor_add_keeps_other_servers(isolated_home):
    path = isolated_home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "mcpServers": {"other-server": {"url": "http://example.test"}},
                "unrelated": True,
            }
        )
    )

    result = client_config.configure("cursor", URL, False)

    assert result["action"] == "add"
    data = json.loads(path.read_text())
    assert data["mcpServers"]["other-server"] == {"url": "http://example.test"}
    assert data["unrelated"] is True
    assert data["mcpServers"]["marm-memory"] == {"url": URL}


def test_cursor_none_when_already_equal(isolated_home):
    detect(isolated_home, "cursor")
    client_config.configure("cursor", URL, False)
    backup = isolated_home / ".cursor" / "mcp.json.marm-backup"
    assert not backup.exists()

    result = client_config.configure("cursor", URL, False)

    assert result["action"] == "none"
    assert result["written"] is False
    assert result["verified"] is True
    assert not backup.exists()


def test_cursor_replace_when_different_and_backs_up(isolated_home):
    detect(isolated_home, "cursor")
    client_config.configure("cursor", "http://127.0.0.1:9999/mcp", False)
    path = isolated_home / ".cursor" / "mcp.json"
    backup = isolated_home / ".cursor" / "mcp.json.marm-backup"

    result = client_config.configure("cursor", URL, False)

    assert result["action"] == "replace"
    assert result["backup_path"] == str(backup)
    assert (
        json.loads(backup.read_text())["mcpServers"]["marm-memory"]["url"]
        == "http://127.0.0.1:9999/mcp"
    )
    assert json.loads(path.read_text())["mcpServers"]["marm-memory"] == {"url": URL}


def test_switching_transport_replaces_the_entry(isolated_home):
    detect(isolated_home, "cursor")
    client_config.configure("cursor", URL, False)

    result = client_config.configure("cursor", URL, False, transport="stdio")

    assert result["action"] == "replace"
    path = isolated_home / ".cursor" / "mcp.json"
    assert json.loads(path.read_text())["mcpServers"]["marm-memory"] == {
        "command": "marm-mcp-stdio",
        "args": [],
    }


def test_dry_run_writes_nothing_and_creates_no_directory(isolated_home):
    detect(isolated_home, "kiro")

    result = client_config.configure("kiro", URL, False, dry_run=True)

    assert result["action"] == "create"
    assert "written" not in result
    assert not (isolated_home / ".kiro" / "settings").exists()


def test_stdio_entry_uses_the_absolute_path_and_notes_the_bare_fallback(
    isolated_home, monkeypatch
):
    detect(isolated_home, "cursor")
    bare = client_config.configure(
        "cursor", URL, False, transport="stdio", dry_run=True
    )
    assert bare["entry"]["command"] == "marm-mcp-stdio"
    assert any("bare command name" in note for note in bare["notes"])

    found = str(isolated_home / "Scripts" / "marm-mcp-stdio.EXE")
    monkeypatch.setattr(
        client_config.shutil,
        "which",
        lambda name: found if name == "marm-mcp-stdio" else None,
    )
    absolute = client_config.configure(
        "cursor", URL, False, transport="stdio", dry_run=True
    )
    assert absolute["entry"]["command"] == found
    assert not any("bare command name" in note for note in absolute["notes"])


def test_docker_entry_uses_the_real_plan_with_an_absolute_data_dir(isolated_home):
    detect(isolated_home, "cursor")

    result = client_config.configure(
        "cursor",
        URL,
        False,
        transport="docker-stdio",
        docker_data_dir=isolated_home,
        docker_tag="9.9.9",
        dry_run=True,
    )

    plan = docker_commands.stdio_command(tag="9.9.9", data_dir=isolated_home)
    assert result["entry"] == {"command": "docker", "args": plan["arguments"][1:]}
    mount = result["entry"]["args"][result["entry"]["args"].index("--mount") + 1]
    assert "~" not in mount
    assert str(isolated_home.resolve()) in mount


def test_docker_entry_missing_data_dir_is_not_configurable(isolated_home):
    detect(isolated_home, "cursor")
    with pytest.raises(client_config.ClientNotConfigurable, match="existing directory"):
        client_config.configure(
            "cursor",
            URL,
            False,
            transport="docker-stdio",
            docker_data_dir=isolated_home / "missing",
        )


# --- Refusals ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["{not valid json", "[]", '"a string"', '{"mcpServers": []}', '{"mcpServers": 3}'],
)
def test_unreadable_or_wrong_shape_file_refused_and_untouched(isolated_home, text):
    path = isolated_home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text(text)

    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.configure("cursor", URL, False)

    assert path.read_text() == text
    assert not (path.parent / "mcp.json.marm-backup").exists()
    assert not (path.parent / "mcp.json.tmp").exists()
    state = client_config.status("cursor")
    assert state["state"] == "unreadable"


def test_vscode_inputs_that_are_not_a_list_refused(isolated_home):
    path = isolated_home / DETECT_DIRS["vscode"] / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"servers": {}, "inputs": {"id": "x"}}')

    with pytest.raises(client_config.ClientNotConfigurable, match="inputs"):
        client_config.configure("vscode", URL, True)

    assert path.read_text() == '{"servers": {}, "inputs": {"id": "x"}}'


def test_a_directory_where_the_file_should_be_is_unreadable_not_a_crash(isolated_home):
    (isolated_home / ".cursor" / "mcp.json").mkdir(parents=True)

    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.configure("cursor", URL, False)
    assert client_config.status("cursor")["state"] == "unreadable"


def test_os_error_while_writing_is_a_refusal_with_no_tmp_left(
    isolated_home, monkeypatch
):
    path = isolated_home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    original = json.dumps({"mcpServers": {"other": {"url": "http://x.test"}}})
    path.write_text(original)

    def locked(src, dst):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(client_config.os, "replace", locked)

    with pytest.raises(client_config.ClientNotConfigurable, match="Could not write"):
        client_config.configure("cursor", URL, False)

    assert path.read_text() == original
    assert not (path.parent / "mcp.json.tmp").exists()


def test_os_error_while_writing_codex_is_a_refusal_with_no_tmp_left(
    isolated_home, monkeypatch
):
    path = isolated_home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('model = "x"\n')

    def locked(src, dst):
        raise PermissionError(13, "locked")

    monkeypatch.setattr(client_config.os, "replace", locked)

    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.configure("codex", URL, False)

    assert path.read_text() == 'model = "x"\n'
    assert not (path.parent / "config.toml.tmp").exists()


def test_undetected_client_creates_no_directories(isolated_home):
    with pytest.raises(client_config.ClientNotConfigurable, match="not detected"):
        client_config.configure("cursor", URL, False)
    with pytest.raises(client_config.ClientNotConfigurable, match="not detected"):
        client_config.configure("cursor", URL, False, dry_run=True)

    assert not (isolated_home / ".cursor").exists()


def test_project_scope_creates_the_client_directory(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()

    client_config.configure("cursor", URL, False, scope="project", project=str(project))

    assert (project / ".cursor" / "mcp.json").is_file()


def test_antigravity_and_qwen_http_with_auth_are_unavailable_and_suggest_stdio(
    isolated_home,
):
    for client in ("antigravity", "qwen"):
        detect(isolated_home, client)
        with pytest.raises(client_config.ClientNotConfigurable, match="STDIO"):
            client_config.configure(client, URL, True)
        stdio = client_config.configure(client, URL, True, transport="stdio")
        assert stdio["verified"] is True
        assert "headers" not in stdio["entry"]
        agent = next(
            a for a in client_config.list_agents(URL, True) if a["id"] == client
        )
        assert "STDIO" in agent["unavailable"]["http"]
        assert "stdio" not in agent["unavailable"]
    assert not (isolated_home / ".qwen" / "settings.json.marm-backup").exists()


def test_claude_desktop_http_is_unavailable_with_the_reason(isolated_home):
    detect(isolated_home, "claude-desktop")

    with pytest.raises(client_config.ClientNotConfigurable, match="mcp-remote"):
        client_config.configure("claude-desktop", URL, False)
    agent = next(
        a for a in client_config.list_agents(URL, False) if a["id"] == "claude-desktop"
    )
    assert "mcp-remote" in agent["unavailable"]["http"]
    assert agent["scopes"] == ["user"]
    assert set(agent["unavailable"]) == {"http"}


def test_claude_desktop_has_no_config_on_linux(isolated_home, monkeypatch):
    monkeypatch.setattr(client_config, "_platform", lambda: "linux")

    agent = next(
        a for a in client_config.list_agents(URL, False) if a["id"] == "claude-desktop"
    )

    assert agent["detected"] is False
    assert agent["user"]["config_path"] is None
    assert set(agent["unavailable"]) == {"http", "stdio", "docker-stdio"}
    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.configure("claude-desktop", URL, False, transport="stdio")


def test_claude_desktop_mac_path(isolated_home, monkeypatch):
    monkeypatch.setattr(client_config, "_platform", lambda: "darwin")

    state = client_config.status("claude-desktop")

    assert state["config_path"] == str(
        isolated_home
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json"
    )


def test_bad_transport_scope_and_project_are_invalid_requests(isolated_home, tmp_path):
    detect(isolated_home, "cursor")
    (tmp_path / "afile").write_text("x")
    cases = [
        {"transport": "grpc"},
        {"scope": "everywhere"},
        {"scope": "project"},
        {"scope": "project", "project": "relative/dir"},
        {"scope": "project", "project": str(tmp_path / "does-not-exist")},
        {"scope": "project", "project": str(tmp_path / "afile")},
    ]
    for case in cases:
        with pytest.raises(client_config.InvalidRequest):
            client_config.configure("cursor", URL, False, **case)
    with pytest.raises(client_config.InvalidRequest, match="user scope only"):
        client_config.configure(
            "devin", URL, False, scope="project", project=str(tmp_path)
        )
    with pytest.raises(client_config.InvalidRequest):
        client_config.status("cursor", "project", str(tmp_path / "nope"))
    with pytest.raises(client_config.ClientNotFound):
        client_config.configure("nope", URL, False)


def make_dir_link(link: Path, target: Path) -> None:
    """A directory symlink, or a junction on Windows accounts that cannot symlink."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("this OS refuses to create symlinks")
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            pytest.skip("this OS refuses to create symlinks or junctions")


def test_project_write_target_that_resolves_outside_is_refused(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()
    outside = isolated_home / "elsewhere"
    outside.mkdir()
    make_dir_link(project / ".cursor", outside)

    with pytest.raises(client_config.ClientNotConfigurable, match="outside"):
        client_config.configure(
            "cursor", URL, False, scope="project", project=str(project)
        )

    assert list(outside.iterdir()) == []


def test_symlinked_file_keeps_its_link_and_updates_the_real_target(isolated_home):
    detect(isolated_home, "cursor")
    real = isolated_home / "dotfiles" / "cursor-mcp.json"
    real.parent.mkdir()
    real.write_text(json.dumps({"mcpServers": {"other": {"url": "http://x.test"}}}))
    link = isolated_home / ".cursor" / "mcp.json"
    try:
        os.symlink(real, link)
    except OSError:
        pytest.skip("this OS refuses to create symlinks")

    result = client_config.configure("cursor", URL, False)

    assert link.is_symlink()
    assert result["verified"] is True
    data = json.loads(real.read_text())
    assert data["mcpServers"]["marm-memory"] == {"url": URL}
    assert data["mcpServers"]["other"] == {"url": "http://x.test"}
    assert not list((isolated_home / "dotfiles").glob("*.tmp"))


def test_write_through_a_linked_directory_lands_in_the_real_directory(isolated_home):
    real_dir = isolated_home / "dotfiles" / "cursor"
    real_dir.mkdir(parents=True)
    make_dir_link(isolated_home / ".cursor", real_dir)

    client_config.configure("cursor", URL, False)

    assert json.loads((real_dir / "mcp.json").read_text())["mcpServers"][
        "marm-memory"
    ] == {"url": URL}


# --- VS Code auth input ------------------------------------------------------------


def test_vscode_auth_adds_one_input_not_duplicated_on_replace(isolated_home):
    detect(isolated_home, "vscode")
    first = client_config.configure("vscode", URL, True)
    path = isolated_home / DETECT_DIRS["vscode"] / "mcp.json"
    data = json.loads(path.read_text())
    assert first["action"] == "create"
    assert len(data["inputs"]) == 1
    assert data["inputs"][0]["id"] == "marm-api-key"

    second = client_config.configure("vscode", "http://127.0.0.1:9999/mcp", True)
    data = json.loads(path.read_text())

    assert second["action"] == "replace"
    assert len(data["inputs"]) == 1


def test_vscode_stdio_adds_no_input(isolated_home):
    detect(isolated_home, "vscode")
    client_config.configure("vscode", URL, True, transport="stdio")
    path = isolated_home / DETECT_DIRS["vscode"] / "mcp.json"
    assert "inputs" not in json.loads(path.read_text())


# --- Codex TOML ----------------------------------------------------------------------


def test_codex_append_keeps_prior_content_byte_for_byte(isolated_home):
    path = isolated_home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    original = '[some_other]\nfoo = "bar"\n'
    path.write_text(original)

    result = client_config.configure("codex", URL, False)

    assert result["action"] == "add"
    text = path.read_text()
    assert text.startswith(original)
    assert "[mcp_servers.marm-memory]" in text
    assert f'url = "{URL}"' in text


def test_codex_existing_differing_table_refused_even_at_preview(isolated_home):
    path = isolated_home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('[mcp_servers.marm-memory]\nurl = "http://127.0.0.1:9999/mcp"\n')
    before = path.read_text()

    for dry_run in (False, True):
        with pytest.raises(client_config.ClientNotConfigurable):
            client_config.configure("codex", URL, False, dry_run=dry_run)

    assert path.read_text() == before


def test_codex_none_when_equal(isolated_home):
    detect(isolated_home, "codex")
    client_config.configure("codex", URL, True)
    result = client_config.configure("codex", URL, True)
    assert result["action"] == "none"
    assert result["written"] is False


def test_codex_stdio_table_escapes_windows_paths(isolated_home, monkeypatch):
    detect(isolated_home, "codex")
    exe = "C:\\Users\\Marm User\\Scripts\\marm-mcp-stdio.EXE"
    monkeypatch.setattr(
        client_config.shutil,
        "which",
        lambda name: exe if name == "marm-mcp-stdio" else None,
    )

    result = client_config.configure("codex", URL, False, transport="stdio")

    assert result["verified"] is True
    tomllib = pytest.importorskip("tomllib")
    path = isolated_home / ".codex" / "config.toml"
    table = tomllib.loads(path.read_text())["mcp_servers"]["marm-memory"]
    assert table == {"command": exe, "args": []}


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_codex_append_preserves_bytes_and_line_endings(isolated_home, newline):
    path = isolated_home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    original = f'model = "gpt-5"{newline}[some_other]{newline}foo = "bar"'.encode()
    path.write_bytes(original)

    result = client_config.configure("codex", URL, False)

    written = path.read_bytes()
    assert result["verified"] is True
    assert written.startswith(original + newline.encode())
    appended = written[len(original) :].decode()
    assert appended.count("\r\n") == (appended.count("\n") if newline == "\r\n" else 0)
    assert (path.parent / "config.toml.marm-backup").read_bytes() == original


def test_codex_docs_entry_with_extra_keys_counts_as_configured(isolated_home):
    path = isolated_home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[mcp_servers."marm-memory"]\n'
        f'url = "{URL}"\n'
        "enabled = true\n"
        'bearer_token_env_var = "MARM_API_KEY"\n'
    )
    before = path.read_bytes()

    state = client_config.status("codex", url=URL, auth_required=True)
    result = client_config.configure("codex", URL, True)

    assert state["state"] == "configured"
    assert result["action"] == "none"
    assert path.read_bytes() == before


def test_codex_project_scope_notes_the_trust_requirement(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()

    result = client_config.configure(
        "codex", URL, False, scope="project", project=str(project), dry_run=True
    )

    assert any("trust" in note for note in result["notes"])


def test_json_merge_keeps_non_ascii_text(isolated_home):
    path = isolated_home / ".gemini" / "config" / "mcp_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"ui": {"greeting": "héllo 世界"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    client_config.configure("antigravity", URL, False)

    text = path.read_text(encoding="utf-8")
    assert "héllo 世界" in text
    assert json.loads(text)["mcpServers"]["marm-memory"] == {"serverUrl": URL}


# --- Status ------------------------------------------------------------------------------


def test_docs_localhost_entries_count_as_configured(isolated_home):
    docs_url = "http://localhost:8001/mcp"
    for folder in (".qwen", ".codex"):
        (isolated_home / folder).mkdir()
    (isolated_home / ".qwen" / "settings.json").write_text(
        json.dumps({"mcpServers": {"marm-memory": {"httpUrl": docs_url}}})
    )
    (isolated_home / ".codex" / "config.toml").write_text(
        f'[mcp_servers.marm-memory]\nurl = "{docs_url}"\n'
    )

    states = {
        a["id"]: a["user"]["state"] for a in client_config.list_agents(URL, False)
    }

    assert states["qwen"] == "configured"
    assert states["codex"] == "configured"
    other = client_config.list_agents("http://127.0.0.1:9000/mcp", False)
    assert {a["id"]: a["user"]["state"] for a in other}["qwen"] == "different"


def test_status_reports_the_detected_transport(isolated_home):
    detect(isolated_home, "cursor")
    path = isolated_home / ".cursor" / "mcp.json"

    def write(entry):
        path.write_text(json.dumps({"mcpServers": {"marm-memory": entry}}))
        return client_config.status("cursor", url=URL, auth_required=False)

    stdio = write({"command": "C:\\tools\\marm-mcp-stdio.exe", "args": []})
    assert (stdio["state"], stdio["transport_detected"]) == ("configured", "stdio")
    docker = write({"command": "docker", "args": ["run", "marm-mcp-stdio", "img"]})
    assert (docker["state"], docker["transport_detected"]) == (
        "configured",
        "docker-stdio",
    )
    http = write({"url": URL})
    assert (http["state"], http["transport_detected"]) == ("configured", "http")
    stale = write({"url": "http://127.0.0.1:1/mcp"})
    assert stale["state"] == "different"
    assert stale["current_entry"] == {"url": "http://127.0.0.1:1/mcp"}
    junk = write({"nothing": "useful"})
    assert (junk["state"], junk["transport_detected"]) == ("different", None)
    assert client_config.status("cursor")["state"] == "configured"


def test_status_missing_before_any_file(isolated_home):
    state = client_config.status("cursor", url=URL)
    assert state == {
        "scope": "user",
        "project": None,
        "config_path": str(isolated_home / ".cursor" / "mcp.json"),
        "config_exists": False,
        "state": "missing",
        "transport_detected": None,
        "current_entry": None,
    }


def test_project_status_reads_the_project_file(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()
    client_config.configure("claude", URL, False, scope="project", project=str(project))

    state = client_config.status("claude", "project", str(project), URL)

    assert state["state"] == "configured"
    assert state["project"] == str(project)
    assert state["config_path"] == str(project / ".mcp.json")


def test_claude_notes_project_scoped_entry(isolated_home):
    (isolated_home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {},
                "projects": {"C:/repo": {"mcpServers": {"marm-memory": {"url": URL}}}},
            }
        )
    )

    claude = next(
        a for a in client_config.list_agents(URL, False) if a["id"] == "claude"
    )

    assert claude["user"]["state"] == "missing"
    assert claude["notes"][0].startswith("MARM is already set up for some projects")


def test_claude_detection_is_not_the_home_directory(isolated_home, monkeypatch):
    (isolated_home / ".claude.json").write_text("{}")

    def claude_agent():
        return next(
            a for a in client_config.list_agents(URL, False) if a["id"] == "claude"
        )

    assert claude_agent()["detected"] is False

    (isolated_home / ".claude").mkdir()
    assert claude_agent()["detected"] is True

    (isolated_home / ".claude").rmdir()
    monkeypatch.setattr(client_config.shutil, "which", lambda name: "C:/bin/claude.exe")
    assert claude_agent()["detected"] is True


def test_agent_list_shape(isolated_home):
    agents = client_config.list_agents(URL, False)

    assert [a["id"] for a in agents] == client_config.CLIENT_IDS
    by_id = {a["id"]: a for a in agents}
    assert by_id["devin"]["scopes"] == ["user"]
    assert by_id["devin"]["skill"] == {"supported": True, "installed": False}
    assert by_id["cursor"]["scopes"] == ["user", "project"]
    assert by_id["cursor"]["transports"] == ["http", "stdio", "docker-stdio"]
    assert by_id["cursor"]["skill"] == {"supported": True, "installed": False}
    assert by_id["vscode"]["skill"] == {"supported": False, "installed": False}
    assert by_id["antigravity"]["skill"] == {"supported": True, "installed": False}
    assert by_id["kiro"]["skill"]["supported"] is True
    assert by_id["grok"]["skill"] == {"supported": True, "installed": False}


def test_skill_state_follows_the_installed_file(isolated_home):
    detect(isolated_home, "antigravity")
    skill = isolated_home / ".gemini" / "config" / "skills" / "marm-init" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("skill")

    agent = next(
        a for a in client_config.list_agents(URL, False) if a["id"] == "antigravity"
    )

    assert agent["skill"] == {"supported": True, "installed": True}


# --- Remove ------------------------------------------------------------------------------


def test_remove_deletes_only_marms_entry(isolated_home):
    path = isolated_home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"url": "http://x.test"},
                    "marm-memory": {"url": URL},
                },
                "keep": 1,
            }
        )
    )

    result = client_config.remove("cursor")

    assert result["action"] == "remove"
    assert result["method"] == "file"
    assert result["written"] is True
    assert result["verified"] is True
    assert result["backup_path"] == str(path.with_name("mcp.json.marm-backup"))
    data = json.loads(path.read_text())
    assert data == {"mcpServers": {"other": {"url": "http://x.test"}}, "keep": 1}
    assert (
        "marm-memory"
        in json.loads((path.parent / "mcp.json.marm-backup").read_text())["mcpServers"]
    )


def test_remove_is_none_when_absent_and_dry_run_writes_nothing(isolated_home):
    assert client_config.remove("cursor")["action"] == "none"
    path = isolated_home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"marm-memory": {"url": URL}}}))
    before = path.read_text()

    result = client_config.remove("cursor", dry_run=True)

    assert result["action"] == "remove"
    assert "written" not in result
    assert path.read_text() == before


def test_remove_project_scope_json(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()
    (project / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"a": {"command": "x"}, "marm-memory": {"url": URL}}})
    )

    result = client_config.remove("claude", "project", str(project))

    assert result["method"] == "file"
    assert json.loads((project / ".mcp.json").read_text()) == {
        "mcpServers": {"a": {"command": "x"}}
    }


def test_remove_unreadable_file_refused(isolated_home):
    path = isolated_home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2]")

    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.remove("cursor")
    assert path.read_text() == "[1, 2]"


def test_remove_os_error_is_a_refusal_with_no_tmp_left(isolated_home, monkeypatch):
    path = isolated_home / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"marm-memory": {"url": URL}}}))
    monkeypatch.setattr(
        client_config.os,
        "replace",
        lambda *_: (_ for _ in ()).throw(PermissionError(13, "locked")),
    )

    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.remove("cursor")

    assert not (path.parent / "mcp.json.tmp").exists()
    assert "marm-memory" in path.read_text()


def test_claude_remove_uses_the_cli_with_user_scope(isolated_home, monkeypatch):
    monkeypatch.setattr(client_config.shutil, "which", lambda name: "C:/bin/claude.exe")
    claude_json = isolated_home / ".claude.json"
    claude_json.write_text(
        json.dumps(
            {"mcpServers": {"marm-memory": {"type": "http", "url": URL}, "o": {}}}
        )
    )
    calls: list[list[str]] = []

    def fake_runner(argv, timeout=20.0):
        calls.append(argv)
        data = json.loads(claude_json.read_text())
        data["mcpServers"].pop("marm-memory")
        claude_json.write_text(json.dumps(data))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(client_config, "run_cli_subprocess", fake_runner)

    result = client_config.remove("claude")

    assert calls == [
        ["C:/bin/claude.exe", "mcp", "remove", "--scope", "user", "marm-memory"]
    ]
    assert result["method"] == "cli"
    assert result["verified"] is True
    assert "o" in json.loads(claude_json.read_text())["mcpServers"]


def test_codex_remove_uses_the_cli_when_present_else_is_manual(
    isolated_home, monkeypatch
):
    path = isolated_home / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    original = f'other = 1\n\n[mcp_servers.marm-memory]\nurl = "{URL}"\n'
    path.write_text(original)

    with pytest.raises(client_config.ClientNotConfigurable, match="by hand"):
        client_config.remove("codex")
    assert path.read_text() == original

    monkeypatch.setattr(client_config.shutil, "which", lambda name: "C:/bin/codex.exe")
    calls: list[list[str]] = []

    def fake_runner(argv, timeout=20.0):
        calls.append(argv)
        path.write_text("other = 1\n")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(client_config, "run_cli_subprocess", fake_runner)

    result = client_config.remove("codex")

    assert calls == [["C:/bin/codex.exe", "mcp", "remove", "marm-memory"]]
    assert result["method"] == "cli"
    assert result["verified"] is True


def test_codex_remove_project_scope_is_manual(isolated_home):
    project = isolated_home / "repo"
    (project / ".codex").mkdir(parents=True)
    (project / ".codex" / "config.toml").write_text(
        f'[mcp_servers.marm-memory]\nurl = "{URL}"\n'
    )

    with pytest.raises(client_config.ClientNotConfigurable, match="by hand"):
        client_config.remove("codex", "project", str(project))


# --- Grok Build TOML -----------------------------------------------------------------


def test_grok_append_keeps_prior_content_and_writes_the_bearer_env_var(isolated_home):
    path = isolated_home / ".grok" / "config.toml"
    path.parent.mkdir(parents=True)
    original = '[models]\ndefault = "grok-build"\n'
    path.write_text(original)

    result = client_config.configure("grok", URL, True)

    assert result["action"] == "add"
    assert result["verified"] is True
    text = path.read_text()
    assert text.startswith(original)
    tomllib = pytest.importorskip("tomllib")
    table = tomllib.loads(text)["mcp_servers"]["marm-memory"]
    assert table == {"url": URL, "bearer_token_env_var": "MARM_API_KEY"}


def test_grok_project_scope_writes_grok_config_without_a_trust_note(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()

    result = client_config.configure(
        "grok", URL, False, scope="project", project=str(project)
    )

    assert (project / ".grok" / "config.toml").is_file()
    assert result["verified"] is True
    assert not any("trust" in note for note in result["notes"])


def test_grok_existing_differing_table_is_refused(isolated_home):
    path = isolated_home / ".grok" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('[mcp_servers.marm-memory]\nurl = "http://127.0.0.1:9999/mcp"\n')
    before = path.read_text()

    with pytest.raises(client_config.ClientNotConfigurable, match="edit it manually"):
        client_config.configure("grok", URL, False)

    assert path.read_text() == before


def test_grok_docs_entry_with_headers_instead_of_the_env_var_is_different(
    isolated_home,
):
    path = isolated_home / ".grok" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        f'[mcp_servers.marm-memory]\nurl = "{URL}"\n'
        'headers = { Authorization = "Bearer ${MARM_API_KEY}" }\n'
    )

    state = client_config.status("grok", url=URL, auth_required=True)

    assert state["state"] == "different"
    assert client_config.status("grok", url=URL, auth_required=False)["state"] == (
        "configured"
    )


def test_grok_remove_uses_the_cli_and_project_scope_is_manual(
    isolated_home, monkeypatch
):
    path = isolated_home / ".grok" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f'other = 1\n\n[mcp_servers.marm-memory]\nurl = "{URL}"\n')
    with pytest.raises(client_config.ClientNotConfigurable, match="by hand"):
        client_config.remove("grok")

    monkeypatch.setattr(client_config.shutil, "which", lambda name: "C:/bin/grok.exe")
    calls: list[list[str]] = []

    def fake_runner(argv, timeout=20.0):
        calls.append(argv)
        path.write_text("other = 1\n")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(client_config, "run_cli_subprocess", fake_runner)
    result = client_config.remove("grok")

    assert calls == [["C:/bin/grok.exe", "mcp", "remove", "marm-memory"]]
    assert result["verified"] is True

    project = isolated_home / "repo"
    (project / ".grok").mkdir(parents=True)
    (project / ".grok" / "config.toml").write_text(
        f'[mcp_servers.marm-memory]\nurl = "{URL}"\n'
    )
    with pytest.raises(
        client_config.ClientNotConfigurable, match="Grok Build cannot edit"
    ):
        client_config.remove("grok", "project", str(project))


def test_grok_notes_when_claude_code_already_lists_marm(isolated_home):
    detect(isolated_home, "grok")

    def grok_notes():
        agent = next(
            a for a in client_config.list_agents(URL, False) if a["id"] == "grok"
        )
        return agent["notes"]

    assert not any("Claude Code" in note for note in grok_notes())
    (isolated_home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"marm-memory": {"type": "http", "url": URL}}})
    )
    assert any("Claude Code" in note for note in grok_notes())
    client_config.configure("grok", URL, False)
    assert not any("Claude Code" in note for note in grok_notes())


# --- Hermes Agent YAML ---------------------------------------------------------------


def hermes_file(home: Path) -> Path:
    return home / "AppData" / "Local" / "hermes" / "config.yaml"


def load_yaml(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_hermes_creates_the_file_with_a_keyed_http_entry(isolated_home):
    detect(isolated_home, "hermes")

    result = client_config.configure("hermes", URL, True)

    assert result["action"] == "create"
    assert result["verified"] is True
    entry = load_yaml(hermes_file(isolated_home))["mcp_servers"]["marm-memory"]
    assert entry == {"url": URL, "headers": {"Authorization": "Bearer ${MARM_API_KEY}"}}
    assert SECRET not in hermes_file(isolated_home).read_text()
    assert any("/reload-mcp" in note for note in result["notes"])


def test_hermes_appends_without_touching_comments_or_other_content(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    original = "# my hermes setup\nmodel:   gpt-x   # keep spacing\nterminal:\n    backend: docker\n"
    path.write_text(original)

    result = client_config.configure("hermes", URL, False)

    assert result["action"] == "add"
    text = path.read_text()
    assert text.startswith(original)
    assert load_yaml(path)["mcp_servers"]["marm-memory"] == {"url": URL}
    assert load_yaml(path)["terminal"] == {"backend": "docker"}


def test_hermes_appends_after_a_file_with_no_final_newline(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"model: gpt-x")

    client_config.configure("hermes", URL, False)

    assert load_yaml(path)["model"] == "gpt-x"
    assert load_yaml(path)["mcp_servers"]["marm-memory"] == {"url": URL}


def test_hermes_keeps_crlf_line_endings(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"model: gpt-x\r\n")

    client_config.configure("hermes", URL, False)

    data = path.read_bytes()
    assert b"\r\n" in data
    assert data.count(b"\n") == data.count(b"\r\n")


@pytest.mark.parametrize("indent", [2, 4])
def test_hermes_inserts_under_an_existing_mcp_servers_block(isolated_home, indent):
    pad = " " * indent
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    original = (
        "model: gpt-x\n"
        "mcp_servers:\n"
        f"{pad}# my other server\n"
        f"{pad}github:\n"
        f"{pad}{pad}command: npx\n"
        f'{pad}{pad}args: ["-y", "gh"]\n'
        "terminal:\n"
        f"{pad}backend: local\n"
    )
    path.write_text(original)

    client_config.configure("hermes", URL, False)

    text = path.read_text()
    data = load_yaml(path)
    assert data["mcp_servers"]["github"] == {"command": "npx", "args": ["-y", "gh"]}
    assert data["mcp_servers"]["marm-memory"] == {"url": URL}
    assert data["terminal"] == {"backend": "local"}
    assert f"{pad}# my other server\n{pad}github:" in text
    assert text.count("mcp_servers:") == 1


@pytest.mark.parametrize(
    "header",
    [
        "mcp_servers: {}",
        "mcp_servers:",
        "mcp_servers: null",
        "mcp_servers: {}  # none yet",
    ],
)
def test_hermes_fills_an_empty_mcp_servers_section(isolated_home, header):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(f"model: gpt-x\n{header}\nterminal:\n  backend: local\n")

    client_config.configure("hermes", URL, False)

    data = load_yaml(path)
    assert data["mcp_servers"] == {"marm-memory": {"url": URL}}
    assert data["terminal"] == {"backend": "local"}


@pytest.mark.parametrize(
    "body",
    [
        "mcp_servers: {github: {command: npx}}\n",
        "mcp_servers: &servers\n  github:\n    command: npx\n",
        "mcp_servers:\n  - github\n",
        "mcp_servers: nope\n",
        "- just\n- a list\n",
        "model: [unclosed\n",
    ],
)
def test_hermes_refuses_layouts_it_will_not_edit_and_leaves_the_file_alone(
    isolated_home, body
):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(body)

    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.configure("hermes", URL, False)

    assert path.read_text() == body
    assert not (path.parent / "config.yaml.marm-backup").exists()


def test_hermes_existing_differing_entry_is_refused_even_at_preview(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(
        'mcp_servers:\n  marm-memory:\n    url: "http://127.0.0.1:9999/mcp"\n'
    )
    before = path.read_text()

    for dry_run in (False, True):
        with pytest.raises(
            client_config.ClientNotConfigurable, match="edit it manually"
        ):
            client_config.configure("hermes", URL, False, dry_run=dry_run)

    assert path.read_text() == before


def test_hermes_entry_with_extra_keys_counts_as_configured(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(
        f'mcp_servers:\n  marm-memory:\n    url: "{URL}"\n    timeout: 300\n'
    )

    assert client_config.status("hermes", url=URL)["state"] == "configured"
    assert client_config.configure("hermes", URL, False)["action"] == "none"


def test_hermes_backs_up_before_editing(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text("model: gpt-x\n")

    result = client_config.configure("hermes", URL, False)

    assert result["backup_path"] == str(path) + ".marm-backup"
    assert (path.parent / "config.yaml.marm-backup").read_text() == "model: gpt-x\n"


def test_hermes_restores_the_file_when_the_entry_does_not_land(
    isolated_home, monkeypatch
):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text("model: gpt-x\n")
    monkeypatch.setattr(
        client_config, "_yaml_insert", lambda text, entry: text + "other: 1\n"
    )

    with pytest.raises(client_config.ClientNotConfigurable, match="left as it was"):
        client_config.configure("hermes", URL, False)

    assert path.read_text() == "model: gpt-x\n"


def test_hermes_removes_a_file_it_created_when_the_entry_does_not_land(
    isolated_home, monkeypatch
):
    detect(isolated_home, "hermes")
    monkeypatch.setattr(
        client_config, "_yaml_insert", lambda text, entry: "model: gpt-x\n"
    )

    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.configure("hermes", URL, False)

    assert not hermes_file(isolated_home).exists()


def test_hermes_without_pyyaml_is_unreadable_not_a_crash(isolated_home, monkeypatch):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text("model: gpt-x\n")
    monkeypatch.setattr(client_config, "yaml", None)

    with pytest.raises(client_config.ClientNotConfigurable, match="PyYAML"):
        client_config.configure("hermes", URL, False)

    assert client_config.status("hermes", url=URL)["state"] == "unreadable"


def test_hermes_home_env_var_moves_the_config_and_detection(isolated_home, monkeypatch):
    custom = isolated_home / "elsewhere" / "hermes-data"
    monkeypatch.setenv("HERMES_HOME", str(custom))
    assert client_config.status("hermes")["config_path"] == str(custom / "config.yaml")
    agent = next(
        a for a in client_config.list_agents(URL, False) if a["id"] == "hermes"
    )
    assert agent["detected"] is False

    custom.mkdir(parents=True)
    result = client_config.configure("hermes", URL, False)

    assert result["config_path"] == str(custom / "config.yaml")
    assert load_yaml(custom / "config.yaml")["mcp_servers"]["marm-memory"] == {
        "url": URL
    }
    assert not hermes_file(isolated_home).exists()


def test_hermes_default_home_per_platform(isolated_home, monkeypatch):
    assert client_config.hermes_home() == isolated_home / "AppData" / "Local" / "hermes"
    monkeypatch.delenv("LOCALAPPDATA")
    assert client_config.hermes_home() == isolated_home / "AppData" / "Local" / "hermes"
    monkeypatch.setattr(client_config, "_platform", lambda: "linux")
    assert client_config.hermes_home() == isolated_home / ".hermes"
    monkeypatch.setattr(client_config, "_platform", lambda: "darwin")
    assert client_config.hermes_home() == isolated_home / ".hermes"


def test_hermes_only_supports_the_user_scope(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()
    agent = next(
        a for a in client_config.list_agents(URL, False) if a["id"] == "hermes"
    )

    assert agent["scopes"] == ["user"]
    with pytest.raises(client_config.InvalidRequest, match="user scope only"):
        client_config.configure(
            "hermes", URL, False, scope="project", project=str(project)
        )


@pytest.mark.parametrize("key", ["'mcp_servers'", '"mcp_servers"'])
def test_hermes_quoted_mcp_servers_key_keeps_existing_servers(isolated_home, key):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(f"model: gpt-x\n{key}:\n  github:\n    command: npx\n")

    client_config.configure("hermes", URL, False)

    text = path.read_text()
    data = load_yaml(path)
    assert data["mcp_servers"]["github"] == {"command": "npx"}
    assert data["mcp_servers"]["marm-memory"] == {"url": URL}
    assert text.count("mcp_servers") == 1
    assert f"{key}:" in text
    client_config.remove("hermes")
    assert set(load_yaml(path)["mcp_servers"]) == {"github"}


@pytest.mark.parametrize(
    ("header", "comment"),
    [
        ("mcp_servers: {}  # none yet", "# none yet"),
        ("mcp_servers: ~ # nothing", "# nothing"),
        ("mcp_servers: null   # empty", "# empty"),
        ("mcp_servers:  # my servers", "# my servers"),
        ("'mcp_servers': {}  # quoted", "# quoted"),
    ],
)
def test_hermes_keeps_the_comment_on_the_mcp_servers_line(
    isolated_home, header, comment
):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(f"model: gpt-x\n{header}\nterminal:\n  backend: local\n")

    client_config.configure("hermes", URL, False)

    assert comment in path.read_text()
    assert load_yaml(path)["mcp_servers"] == {"marm-memory": {"url": URL}}
    client_config.remove("hermes")
    text = path.read_text()
    assert comment in text
    assert load_yaml(path)["mcp_servers"] == {}
    assert load_yaml(path)["terminal"] == {"backend": "local"}


def test_hermes_refuses_any_edit_that_changes_more_than_marms_entry(
    isolated_home, monkeypatch
):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    original = "mcp_servers:\n  github:\n    command: npx\nmodel: gpt-x\n"
    path.write_text(original)
    monkeypatch.setattr(
        client_config,
        "_yaml_insert",
        lambda text, entry: text + f'mcp_servers:\n  marm-memory:\n    url: "{URL}"\n',
    )

    with pytest.raises(client_config.ClientNotConfigurable, match="left as it was"):
        client_config.configure("hermes", URL, False)

    assert path.read_text() == original
    assert load_yaml(path)["mcp_servers"]["github"] == {"command": "npx"}


def test_hermes_remove_takes_only_marms_entry_and_keeps_the_rest(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(
        "# top\n"
        "mcp_servers:\n"
        "  github:\n"
        "    command: npx\n"
        "  marm-memory:\n"
        f'    url: "{URL}"\n'
        "    headers:\n"
        '      Authorization: "Bearer ${MARM_API_KEY}"\n'
        "  # trailing note for the next server\n"
        "  docs:\n"
        "    url: http://x\n"
        "terminal:\n"
        "  backend: local\n"
    )

    result = client_config.remove("hermes")

    assert result["action"] == "remove"
    assert result["verified"] is True
    data = load_yaml(path)
    assert set(data["mcp_servers"]) == {"github", "docs"}
    assert data["terminal"] == {"backend": "local"}
    text = path.read_text()
    assert text.startswith("# top\n")
    assert "  # trailing note for the next server\n  docs:" in text
    assert (path.parent / "config.yaml.marm-backup").exists()


def test_hermes_remove_of_the_last_server_leaves_an_empty_mapping(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(
        f'model: gpt-x\nmcp_servers:\n  marm-memory:\n    url: "{URL}"\nterminal:\n  backend: local\n'
    )

    client_config.remove("hermes")

    data = load_yaml(path)
    assert data["mcp_servers"] == {}
    assert data["terminal"] == {"backend": "local"}
    assert "mcp_servers: {}" in path.read_text()


def test_hermes_remove_is_a_no_op_when_the_entry_is_absent(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text("model: gpt-x\n")

    result = client_config.remove("hermes")

    assert result["action"] == "none"
    assert path.read_text() == "model: gpt-x\n"


def test_hermes_remove_refuses_a_flow_style_section(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    body = f'mcp_servers: {{marm-memory: {{url: "{URL}"}}}}\n'
    path.write_text(body)

    with pytest.raises(client_config.ClientNotConfigurable, match="by hand"):
        client_config.remove("hermes")

    assert path.read_text() == body


def test_hermes_install_then_remove_round_trips_the_original_file(isolated_home):
    path = hermes_file(isolated_home)
    path.parent.mkdir(parents=True)
    original = "# keep me\nmodel: gpt-x\n"
    path.write_text(original)

    client_config.configure("hermes", URL, True)
    client_config.remove("hermes")

    data = load_yaml(path)
    assert data["model"] == "gpt-x"
    assert data["mcp_servers"] == {}
    assert path.read_text().startswith(original)


def test_hermes_skill_lands_in_hermes_home_skills(isolated_home, monkeypatch):
    custom = isolated_home / "data" / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(custom))
    detect_dir = custom
    detect_dir.mkdir(parents=True)

    agent = next(
        a for a in client_config.list_agents(URL, False) if a["id"] == "hermes"
    )
    assert agent["skill"] == {"supported": True, "installed": False}

    result = client_config.skill_install.install_for_agent("hermes")

    assert result["target"] == str(custom / "skills" / "marm-init" / "SKILL.md")
    agent = next(
        a for a in client_config.list_agents(URL, False) if a["id"] == "hermes"
    )
    assert agent["skill"] == {"supported": True, "installed": True}


# --- Cline CLI -----------------------------------------------------------------------


def cline_file(home: Path) -> Path:
    return home / ".cline" / "data" / "settings" / "cline_mcp_settings.json"


def test_cline_http_entry_names_the_streamable_transport_explicitly(isolated_home):
    detect(isolated_home, "cline")

    result = client_config.configure("cline", URL, False)

    assert result["entry"] == {"type": "streamableHttp", "url": URL}
    data = json.loads(cline_file(isolated_home).read_text())
    assert data["mcpServers"]["marm-memory"] == {"type": "streamableHttp", "url": URL}


def test_cline_keeps_other_servers_and_top_level_keys(isolated_home):
    path = cline_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "$schema": "x",
                "mcpServers": {"github": {"command": "npx", "autoApprove": ["a"]}},
            }
        )
    )

    client_config.configure("cline", URL, False, transport="stdio")
    client_config.remove("cline")

    data = json.loads(path.read_text())
    assert data["$schema"] == "x"
    assert data["mcpServers"] == {"github": {"command": "npx", "autoApprove": ["a"]}}


def test_cline_keyed_http_is_manual_and_suggests_stdio(isolated_home):
    detect(isolated_home, "cline")

    with pytest.raises(client_config.ClientNotConfigurable, match="STDIO"):
        client_config.configure("cline", URL, True)
    stdio = client_config.configure("cline", URL, True, transport="stdio")

    assert stdio["verified"] is True
    assert "headers" not in stdio["entry"]
    agent = next(a for a in client_config.list_agents(URL, True) if a["id"] == "cline")
    assert "has not confirmed" in agent["unavailable"]["http"]
    assert "stdio" not in agent["unavailable"]


def test_cline_entry_from_its_own_installer_counts_as_configured(isolated_home):
    path = cline_file(isolated_home)
    path.parent.mkdir(parents=True)
    nested = {
        "mcpServers": {
            "marm-memory": {"transport": {"type": "streamableHttp", "url": URL}}
        }
    }
    path.write_text(json.dumps(nested))

    assert client_config.status("cline", url=URL)["state"] == "configured"
    result = client_config.configure("cline", URL, False)

    assert result["action"] == "none"
    assert json.loads(path.read_text()) == nested
    assert client_config.read_entry("cline") == {"type": "streamableHttp", "url": URL}


def test_cline_nested_entry_for_another_url_is_replaced_with_the_flat_shape(
    isolated_home,
):
    path = cline_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "marm-memory": {
                        "transport": {"type": "sse", "url": "http://127.0.0.1:9/mcp"}
                    }
                }
            }
        )
    )

    result = client_config.configure("cline", URL, False)

    assert result["action"] == "replace"
    assert json.loads(path.read_text())["mcpServers"]["marm-memory"] == {
        "type": "streamableHttp",
        "url": URL,
    }


def test_cline_path_precedence_across_its_environment_overrides(
    isolated_home, monkeypatch
):
    default = isolated_home / ".cline" / "data" / "settings" / "cline_mcp_settings.json"
    assert client_config.cline_mcp_settings_path() == default

    monkeypatch.setenv("CLINE_DIR", str(isolated_home / "base"))
    assert client_config.cline_home() == isolated_home / "base"
    assert client_config.cline_mcp_settings_path() == (
        isolated_home / "base" / "data" / "settings" / "cline_mcp_settings.json"
    )
    monkeypatch.setenv("CLINE_DATA_DIR", str(isolated_home / "datadir"))
    assert client_config.cline_mcp_settings_path() == (
        isolated_home / "datadir" / "settings" / "cline_mcp_settings.json"
    )
    monkeypatch.setenv("CLINE_MCP_SETTINGS_PATH", str(isolated_home / "one.json"))
    assert client_config.cline_mcp_settings_path() == isolated_home / "one.json"


def test_cline_override_moves_detection_config_and_skill(isolated_home, monkeypatch):
    base = isolated_home / "elsewhere"
    monkeypatch.setenv("CLINE_DIR", str(base))
    agent = next(a for a in client_config.list_agents(URL, False) if a["id"] == "cline")
    assert agent["detected"] is False

    base.mkdir()
    result = client_config.configure("cline", URL, False)
    skill = client_config.skill_install.install_for_agent("cline")

    assert result["config_path"] == str(
        base / "data" / "settings" / "cline_mcp_settings.json"
    )
    assert skill["target"] == str(base / "skills" / "marm-init" / "SKILL.md")
    assert not (isolated_home / ".cline").exists()


def test_cline_is_detected_through_data_dir_and_settings_path_overrides(
    isolated_home, monkeypatch
):
    def detected() -> bool:
        return next(
            a for a in client_config.list_agents(URL, False) if a["id"] == "cline"
        )["detected"]

    assert detected() is False
    data = isolated_home / "data-elsewhere"
    monkeypatch.setenv("CLINE_DATA_DIR", str(data))
    assert detected() is False
    data.mkdir()
    assert detected() is True
    result = client_config.configure("cline", URL, False)
    assert result["config_path"] == str(data / "settings" / "cline_mcp_settings.json")
    assert (data / "settings" / "cline_mcp_settings.json").is_file()
    assert not (isolated_home / ".cline").exists()

    monkeypatch.delenv("CLINE_DATA_DIR")
    assert detected() is False
    custom = isolated_home / "custom" / "mcp.json"
    monkeypatch.setenv("CLINE_MCP_SETTINGS_PATH", str(custom))
    assert detected() is False
    custom.parent.mkdir()
    assert detected() is True
    assert client_config.configure("cline", URL, False)["config_path"] == str(custom)


def test_cline_data_dir_override_does_not_move_the_skill_folder(
    isolated_home, monkeypatch
):
    data = isolated_home / "data-elsewhere"
    data.mkdir()
    monkeypatch.setenv("CLINE_DATA_DIR", str(data))

    skill = client_config.skill_install.install_for_agent("cline")

    assert skill["target"] == str(
        isolated_home / ".cline" / "skills" / "marm-init" / "SKILL.md"
    )


@pytest.mark.parametrize(
    "marker",
    [
        ".gemini/config",
        ".gemini/antigravity",
        ".gemini/antigravity-cli",
        ".gemini/antigravity-ide",
        ".antigravity",
    ],
)
def test_antigravity_is_detected_from_any_of_its_install_folders(isolated_home, marker):
    def detected() -> bool:
        return next(
            a for a in client_config.list_agents(URL, False) if a["id"] == "antigravity"
        )["detected"]

    assert detected() is False
    (isolated_home / marker).mkdir(parents=True)
    assert detected() is True


def test_antigravity_writes_the_old_ide_file_only_when_it_is_the_one_in_use(
    isolated_home,
):
    gemini = isolated_home / ".gemini"
    current = gemini / "config" / "mcp_config.json"
    legacy = gemini / "antigravity" / "mcp_config.json"

    assert client_config.status("antigravity")["config_path"] == str(current)

    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    assert client_config.status("antigravity")["config_path"] == str(legacy)
    result = client_config.configure("antigravity", URL, False)
    assert result["config_path"] == str(legacy)
    written = json.loads(legacy.read_text())["mcpServers"]
    assert written["other"] == {"command": "x"}
    assert written["marm-memory"] == {"serverUrl": URL}
    assert not current.exists()

    current.parent.mkdir(parents=True)
    assert client_config.status("antigravity")["config_path"] == str(current)


def test_old_gemini_cli_folder_alone_is_not_taken_for_antigravity(isolated_home):
    (isolated_home / ".gemini").mkdir()
    (isolated_home / ".gemini" / "settings.json").write_text("{}")

    agent = next(
        a for a in client_config.list_agents(URL, False) if a["id"] == "antigravity"
    )

    assert agent["detected"] is False


def test_shared_file_agents_say_which_surfaces_read_it(isolated_home):
    agents = {a["id"]: a for a in client_config.list_agents(URL, False)}

    assert any("IDE, CLI and 2.0 app" in n for n in agents["antigravity"]["notes"])
    assert any("VS Code and JetBrains" in n for n in agents["cline"]["notes"])


def test_cline_only_supports_the_user_scope(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()
    agent = next(a for a in client_config.list_agents(URL, False) if a["id"] == "cline")

    assert agent["scopes"] == ["user"]
    assert any("Cline extensions" in note for note in agent["notes"])
    with pytest.raises(client_config.InvalidRequest, match="user scope only"):
        client_config.configure(
            "cline", URL, False, scope="project", project=str(project)
        )


# --- Claude Code via subprocess -----------------------------------------------------------


def test_claude_not_configurable_without_binary_or_home_dir(isolated_home):
    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.configure("claude", URL, False)


def test_claude_with_home_dir_but_no_binary_is_refused_at_write_not_preview(
    isolated_home,
):
    detect(isolated_home, "claude")

    preview = client_config.configure("claude", URL, False, dry_run=True)
    assert preview["method"] == "cli"
    with pytest.raises(client_config.ClientNotConfigurable, match="binary"):
        client_config.configure("claude", URL, False)


def test_claude_argv_built_correctly(isolated_home, monkeypatch):
    monkeypatch.setattr(
        client_config.shutil, "which", lambda name: str(isolated_home / "claude.cmd")
    )
    claude_json = isolated_home / ".claude.json"
    calls: list[list[str]] = []

    def fake_runner(argv, timeout=20.0):
        calls.append(argv)
        entry = json.loads(argv[-1])
        data = json.loads(claude_json.read_text()) if claude_json.exists() else {}
        data.setdefault("mcpServers", {})["marm-memory"] = entry
        claude_json.write_text(json.dumps(data))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(client_config, "run_cli_subprocess", fake_runner)

    result = client_config.configure("claude", URL, True)

    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == str(isolated_home / "claude.cmd")
    assert argv[1:6] == ["mcp", "add-json", "--scope", "user", "marm-memory"]
    assert json.loads(argv[6]) == {
        "type": "http",
        "url": URL,
        "headers": {"Authorization": "Bearer ${MARM_API_KEY}"},
    }
    assert result["written"] is True
    assert result["verified"] is True


def test_claude_different_entry_removes_before_adding(isolated_home, monkeypatch):
    monkeypatch.setattr(
        client_config.shutil, "which", lambda name: str(isolated_home / "claude.cmd")
    )
    claude_json = isolated_home / ".claude.json"
    claude_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "marm-memory": {"type": "http", "url": "http://127.0.0.1:9999/mcp"}
                }
            }
        )
    )
    calls: list[list[str]] = []

    def fake_runner(argv, timeout=20.0):
        calls.append(argv)
        if "add-json" in argv:
            entry = json.loads(argv[-1])
            claude_json.write_text(json.dumps({"mcpServers": {"marm-memory": entry}}))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(client_config, "run_cli_subprocess", fake_runner)

    result = client_config.configure("claude", URL, False)

    assert result["action"] == "replace"
    assert calls[0][1:] == ["mcp", "remove", "--scope", "user", "marm-memory"]
    assert "add-json" in calls[1]


def test_claude_cli_failure_is_a_refusal(isolated_home, monkeypatch):
    monkeypatch.setattr(client_config.shutil, "which", lambda name: "C:/bin/claude.exe")
    monkeypatch.setattr(
        client_config,
        "run_cli_subprocess",
        lambda argv, timeout=20.0: subprocess.CompletedProcess(argv, 1, "", "boom"),
    )

    with pytest.raises(client_config.ClientNotConfigurable, match="boom"):
        client_config.configure("claude", URL, False)


# --- Key value never leaks -------------------------------------------------------------------


def test_key_value_absent_from_files_and_responses(isolated_home):
    detect(isolated_home, "cursor")
    result = client_config.configure("cursor", URL, True)
    path = isolated_home / ".cursor" / "mcp.json"

    assert SECRET not in json.dumps(result)
    assert SECRET not in path.read_text()
    assert "${env:MARM_API_KEY}" in path.read_text()

    with pytest.raises(client_config.ClientNotConfigurable) as excinfo:
        client_config.configure("antigravity", URL, True)
    assert SECRET not in str(excinfo.value)


# --- OpenCode ------------------------------------------------------------------------


def opencode_dir(home: Path) -> Path:
    return home / ".config" / "opencode"


def test_opencode_http_and_stdio_entries_use_its_native_shapes(isolated_home):
    detect(isolated_home, "opencode")

    http = client_config.configure("opencode", URL, False, dry_run=True)
    stdio = client_config.configure(
        "opencode", URL, False, transport="stdio", dry_run=True
    )

    assert http["entry"] == {"type": "remote", "url": URL, "oauth": False}
    assert stdio["entry"] == {"type": "local", "command": ["marm-mcp-stdio"]}
    assert any("new OpenCode session" in note for note in http["notes"])


def test_opencode_keyed_http_is_one_click_and_never_writes_the_key(isolated_home):
    detect(isolated_home, "opencode")

    result = client_config.configure("opencode", URL, True)

    text = (opencode_dir(isolated_home) / "opencode.json").read_text()
    assert result["verified"] is True
    assert result["entry"]["headers"] == {"Authorization": "Bearer {env:MARM_API_KEY}"}
    assert SECRET not in text
    agent = next(
        a for a in client_config.list_agents(URL, True) if a["id"] == "opencode"
    )
    assert agent["unavailable"] == {}


def test_opencode_reads_a_jsonc_file_and_says_its_comments_are_not_kept(isolated_home):
    path = opencode_dir(isolated_home) / "opencode.jsonc"
    path.parent.mkdir(parents=True)
    original = (
        "{\n"
        "  // my providers\n"
        '  "provider": {"note": "see http://x//y, and }"},\n'
        '  "mcp": {\n'
        '    "github": {"type": "remote", "url": "https://g.test/mcp",}, /* keep */\n'
        "  },\n"
        "}\n"
    )
    path.write_text(original)

    result = client_config.configure("opencode", URL, False)

    data = json.loads(path.read_text())
    assert result["action"] == "add"
    assert any("comments or trailing commas" in note for note in result["notes"])
    assert data["provider"] == {"note": "see http://x//y, and }"}
    assert data["mcp"]["github"] == {"type": "remote", "url": "https://g.test/mcp"}
    assert data["mcp"]["marm-memory"]["url"] == URL
    assert Path(result["backup_path"]).read_text() == original


def test_opencode_plain_json_gets_no_comment_warning(isolated_home):
    path = opencode_dir(isolated_home) / "opencode.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcp": {}}))

    result = client_config.configure("opencode", URL, False)

    assert not any("comments" in note for note in result["notes"])


def test_opencode_writes_into_the_v2_servers_map_and_keeps_its_siblings(isolated_home):
    path = opencode_dir(isolated_home) / "opencode.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "mcp": {
                    "timeout": {"startup": 45000},
                    "servers": {
                        "sentry": {"type": "remote", "url": "https://s.test/mcp"}
                    },
                }
            }
        )
    )

    client_config.configure("opencode", URL, False)
    added = json.loads(path.read_text())["mcp"]
    client_config.remove("opencode")
    removed = json.loads(path.read_text())["mcp"]

    assert added["timeout"] == {"startup": 45000}
    assert set(added["servers"]) == {"sentry", "marm-memory"}
    assert "marm-memory" not in added
    assert removed["servers"] == {
        "sentry": {"type": "remote", "url": "https://s.test/mcp"}
    }
    assert removed["timeout"] == {"startup": 45000}


def test_opencode_v2_settings_without_a_servers_map_get_the_native_layout(
    isolated_home,
):
    path = opencode_dir(isolated_home) / "opencode.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcp": {"timeout": {"startup": 45000}}}))

    client_config.configure("opencode", URL, False)
    added = json.loads(path.read_text())["mcp"]
    client_config.remove("opencode")
    removed = json.loads(path.read_text())["mcp"]

    assert added["timeout"] == {"startup": 45000}
    assert set(added["servers"]) == {"marm-memory"}
    assert "marm-memory" not in added
    assert removed == {"timeout": {"startup": 45000}, "servers": {}}


def test_opencode_server_named_timeout_stays_in_the_v1_layout(isolated_home):
    path = opencode_dir(isolated_home) / "opencode.json"
    path.parent.mkdir(parents=True)
    other = {"type": "remote", "url": "https://t.test/mcp"}
    path.write_text(json.dumps({"mcp": {"timeout": other}}))

    client_config.configure("opencode", URL, False)

    mcp = json.loads(path.read_text())["mcp"]
    assert mcp["timeout"] == other
    assert mcp["marm-memory"]["url"] == URL
    assert "servers" not in mcp


def test_opencode_project_scope_uses_an_existing_jsonc_file(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()
    (project / "opencode.jsonc").write_text('{\n  // mine\n  "theme": "x",\n}\n')

    result = client_config.configure(
        "opencode", URL, False, scope="project", project=str(project)
    )

    assert Path(result["config_path"]) == project / "opencode.jsonc"
    assert not (project / "opencode.json").exists()
    data = json.loads((project / "opencode.jsonc").read_text())
    assert data["theme"] == "x" and data["mcp"]["marm-memory"]["url"] == URL
    assert (
        client_config.status("opencode", "project", str(project), URL)["state"]
        == "configured"
    )


def test_opencode_v1_layout_keeps_other_servers_on_add_and_remove(isolated_home):
    path = opencode_dir(isolated_home) / "opencode.json"
    path.parent.mkdir(parents=True)
    other = {"type": "local", "command": ["npx", "-y", "x"], "enabled": True}
    path.write_text(json.dumps({"$schema": "s", "mcp": {"x": other}}))

    client_config.configure("opencode", URL, False, transport="stdio")
    client_config.remove("opencode")

    assert json.loads(path.read_text()) == {"$schema": "s", "mcp": {"x": other}}


def test_opencode_command_list_reads_back_as_the_flat_shape(isolated_home):
    detect(isolated_home, "opencode")
    client_config.configure("opencode", URL, False, transport="stdio")

    state = client_config.status("opencode", url=URL)

    assert state["state"] == "configured"
    assert state["transport_detected"] == "stdio"
    assert client_config.read_entry("opencode") == {
        "type": "local",
        "command": "marm-mcp-stdio",
        "args": [],
    }


def test_opencode_docker_command_list_is_detected_as_docker_stdio(isolated_home):
    detect(isolated_home, "opencode")
    client_config.configure(
        "opencode", URL, False, transport="docker-stdio", docker_data_dir=isolated_home
    )

    state = client_config.status("opencode", url=URL)

    assert state["transport_detected"] == "docker-stdio"
    assert state["state"] == "configured"


def test_opencode_entry_without_oauth_off_is_replaced(isolated_home):
    path = opencode_dir(isolated_home) / "opencode.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"mcp": {"marm-memory": {"type": "remote", "url": URL}}})
    )

    assert client_config.status("opencode", url=URL)["state"] == "different"
    result = client_config.configure("opencode", URL, False)

    assert result["action"] == "replace"
    assert json.loads(path.read_text())["mcp"]["marm-memory"]["oauth"] is False


def test_opencode_entry_with_extra_user_keys_counts_as_configured(isolated_home):
    path = opencode_dir(isolated_home) / "opencode.json"
    path.parent.mkdir(parents=True)
    entry = {
        "type": "remote",
        "url": URL,
        "oauth": False,
        "enabled": True,
        "timeout": 9,
    }
    path.write_text(json.dumps({"mcp": {"marm-memory": entry}}))

    assert client_config.configure("opencode", URL, False)["action"] == "none"
    assert json.loads(path.read_text())["mcp"]["marm-memory"] == entry


def test_opencode_prefers_an_existing_jsonc_then_json_then_defaults_to_json(
    isolated_home,
):
    base = opencode_dir(isolated_home)
    assert client_config._opencode_path() == base / "opencode.json"

    base.mkdir(parents=True)
    (base / "opencode.json").write_text("{}")
    assert client_config._opencode_path() == base / "opencode.json"

    (base / "opencode.jsonc").write_text("{}")
    assert client_config._opencode_path() == base / "opencode.jsonc"


def test_opencode_xdg_config_home_moves_the_file_and_detection(
    isolated_home, monkeypatch
):
    xdg = isolated_home / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    (xdg / "opencode").mkdir(parents=True)

    result = client_config.configure("opencode", URL, False)

    assert Path(result["config_path"]) == xdg / "opencode" / "opencode.json"
    assert (xdg / "opencode" / "opencode.json").is_file()
    assert not opencode_dir(isolated_home).exists()
    monkeypatch.setenv("XDG_CONFIG_HOME", "   ")
    assert client_config.opencode_home() == opencode_dir(isolated_home)


@pytest.mark.parametrize("text", ['{"mcp": []}', '{"mcp": 3}', '{"mcp": "x"}'])
def test_opencode_unexpected_mcp_shape_is_refused_and_untouched(isolated_home, text):
    path = opencode_dir(isolated_home) / "opencode.json"
    path.parent.mkdir(parents=True)
    path.write_text(text)

    with pytest.raises(client_config.ClientNotConfigurable):
        client_config.configure("opencode", URL, False)

    assert path.read_text() == text
    assert not (path.parent / "opencode.json.marm-backup").exists()


def test_opencode_project_scope_writes_opencode_json_in_the_project(isolated_home):
    project = isolated_home / "repo"
    project.mkdir()

    result = client_config.configure(
        "opencode", URL, False, scope="project", project=str(project)
    )

    assert Path(result["config_path"]) == project / "opencode.json"
    assert json.loads((project / "opencode.json").read_text())["mcp"]["marm-memory"]


def test_opencode_skill_lands_in_the_opencode_config_skills_folder(isolated_home):
    from marm_mcp_server.services import skill_install

    assert skill_install.is_installed("opencode") is False
    result = skill_install.install_for_agent("opencode")

    expected = opencode_dir(isolated_home) / "skills" / "marm-init" / "SKILL.md"
    assert result["target"] == str(expected)
    assert skill_install.is_installed("opencode") is True


# --- Devin ---------------------------------------------------------------------------


def devin_file(home: Path) -> Path:
    return home / "AppData" / "Roaming" / "devin" / "mcp_config.json"


def test_devin_writes_url_for_http_and_plain_command_and_args_for_stdio(isolated_home):
    detect(isolated_home, "devin")

    http = client_config.configure("devin", URL, False)
    stdio = client_config.configure("devin", URL, False, transport="stdio")

    assert http["entry"] == {"url": URL}
    assert stdio["entry"] == {"command": "marm-mcp-stdio", "args": []}
    data = json.loads(devin_file(isolated_home).read_text())
    assert data["mcpServers"]["marm-memory"] == stdio["entry"]
    agent = next(a for a in client_config.list_agents(URL, False) if a["id"] == "devin")
    assert any("Devin Desktop" in note for note in agent["notes"])


def test_devin_keyed_http_is_manual_and_suggests_stdio(isolated_home):
    detect(isolated_home, "devin")

    with pytest.raises(client_config.ClientNotConfigurable, match="STDIO"):
        client_config.configure("devin", URL, True)
    stdio = client_config.configure("devin", URL, True, transport="stdio")

    assert stdio["verified"] is True
    agent = next(a for a in client_config.list_agents(URL, True) if a["id"] == "devin")
    assert "Devin expands" in agent["unavailable"]["http"]
    assert not any("MARM_API_KEY" in note for note in agent["notes"])


def test_devin_keeps_other_servers_and_top_level_keys(isolated_home):
    path = devin_file(isolated_home)
    path.parent.mkdir(parents=True)
    other = {"url": "https://mcp.notion.com/mcp", "transport": "http"}
    path.write_text(json.dumps({"other": 1, "mcpServers": {"notion": other}}))

    client_config.configure("devin", URL, False)
    client_config.remove("devin")

    assert json.loads(path.read_text()) == {"other": 1, "mcpServers": {"notion": other}}


def test_devin_old_serverurl_entry_is_replaced_with_url(isolated_home):
    path = devin_file(isolated_home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"marm-memory": {"serverUrl": URL}}}))

    assert client_config.status("devin", url=URL)["state"] == "different"
    result = client_config.configure("devin", URL, False)

    assert result["action"] == "replace"
    assert json.loads(path.read_text())["mcpServers"]["marm-memory"] == {"url": URL}


def test_devin_never_uses_the_old_codeium_windsurf_file(isolated_home):
    codeium = isolated_home / ".codeium" / "windsurf" / "mcp_config.json"
    codeium.parent.mkdir(parents=True)
    codeium.write_text(json.dumps({"mcpServers": {"marm-memory": {"serverUrl": URL}}}))

    state = client_config.status("devin")

    assert state["config_path"] == str(devin_file(isolated_home))
    assert state["state"] == "missing"
    assert (
        client_config.list_agents(URL, False)[client_config.CLIENT_IDS.index("devin")][
            "detected"
        ]
        is False
    )


@pytest.mark.parametrize(
    ("platform", "marker"),
    [
        ("win32", "AppData/Roaming/Devin"),
        ("darwin", "Library/Application Support/Devin"),
        ("linux", ".config/Devin"),
    ],
)
def test_devin_is_detected_from_the_desktop_data_folder(
    isolated_home, monkeypatch, platform, marker
):
    monkeypatch.setattr(client_config, "_platform", lambda: platform)
    (isolated_home / marker).mkdir(parents=True)

    agent = next(a for a in client_config.list_agents(URL, False) if a["id"] == "devin")

    assert agent["detected"] is True


def test_devin_connect_leaves_an_old_codeium_windsurf_file_untouched(isolated_home):
    codeium = isolated_home / ".codeium" / "windsurf" / "mcp_config.json"
    codeium.parent.mkdir(parents=True)
    codeium.write_text(json.dumps({"mcpServers": {"marm-memory": {"serverUrl": URL}}}))
    before = codeium.read_bytes()
    detect(isolated_home, "devin")

    client_config.configure("devin", URL, False)

    assert codeium.read_bytes() == before
    assert not codeium.with_name(codeium.name + ".marm-backup").exists()


def test_devin_path_on_posix_is_the_xdg_style_config_folder(isolated_home, monkeypatch):
    monkeypatch.setattr(client_config, "_platform", lambda: "linux")

    assert client_config.status("devin")["config_path"] == str(
        isolated_home / ".config" / "devin" / "mcp_config.json"
    )
    assert client_config.devin_home() == isolated_home / ".config" / "devin"


def test_devin_xdg_config_home_moves_the_file_detection_and_skill(
    isolated_home, monkeypatch
):
    from marm_mcp_server.services import skill_install

    monkeypatch.setattr(client_config, "_platform", lambda: "linux")
    xdg = isolated_home / "xdg"
    (xdg / "devin").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    result = client_config.configure("devin", URL, False)
    skill = skill_install.install_for_agent("devin")

    assert Path(result["config_path"]) == xdg / "devin" / "mcp_config.json"
    assert skill["target"] == str(xdg / "devin" / "skills" / "marm-init" / "SKILL.md")
    assert not (isolated_home / ".config" / "devin").exists()
    monkeypatch.setenv("XDG_CONFIG_HOME", "   ")
    assert client_config.devin_home() == isolated_home / ".config" / "devin"


def test_devin_windows_ignores_xdg_config_home(isolated_home, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(isolated_home / "xdg"))

    assert client_config.devin_home() == isolated_home / "AppData" / "Roaming" / "devin"


def test_devin_only_supports_the_user_scope_and_windsurf_is_an_alias(isolated_home):
    with pytest.raises(client_config.InvalidRequest, match="user scope only"):
        client_config.configure(
            "devin", URL, False, scope="project", project=str(isolated_home)
        )
    detect(isolated_home, "devin")

    result = client_config.configure("windsurf", URL, False)

    assert result["client"] == "devin"
    assert "windsurf" not in client_config.CLIENT_IDS
    assert client_config.status("windsurf")["state"] == "configured"


def test_devin_skill_lands_in_the_devin_config_skills_folder(isolated_home):
    from marm_mcp_server.services import skill_install

    result = skill_install.install_for_agent("devin")

    expected = isolated_home / "AppData" / "Roaming" / "devin" / "skills" / "marm-init"
    assert result["target"] == str(expected / "SKILL.md")
    assert skill_install.is_installed("devin") is True
