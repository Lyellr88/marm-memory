"""Manual-tab snippets and agent CLI commands: parseable, correctly keyed, and never carrying a key value."""

from __future__ import annotations

import json
import shlex

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

import yaml

from marm_mcp_server.services import client_config, client_snippets

URL = "http://127.0.0.1:8001/mcp"
DOCKER_URL = "http://127.0.0.1:9001/mcp"
SECRET = "sk-marm-snippet-secret-value"
CLIENTS = list(client_config.CLIENT_IDS)
OSES = client_snippets.OS_NAMES


@pytest.fixture(autouse=True)
def secret_in_env(monkeypatch):
    monkeypatch.setenv("MARM_API_KEY", SECRET)
    monkeypatch.setattr(client_config.shutil, "which", lambda name: None)


def all_cases():
    for client in CLIENTS:
        spec = client_config.REGISTRY[client]
        for os_name in OSES:
            for transport in client_config.TRANSPORTS:
                for scope in client_config._scopes(spec):
                    for auth in (False, True):
                        yield client, os_name, transport, scope, auth


def make(client, os_name, transport, scope, auth, url=URL):
    return client_snippets.snippet(client, os_name, transport, scope, url, auth)


def parsed(result):
    if result["format"] == "toml":
        assert tomllib is not None
        return tomllib.loads(result["text"])
    if result["format"] == "yaml":
        return yaml.safe_load(result["text"])
    return json.loads(result["text"])


def test_every_supported_combination_parses_with_container_key_and_url() -> None:
    checked = 0
    for client, os_name, transport, scope, auth in all_cases():
        spec = client_config.REGISTRY[client]
        try:
            result = make(client, os_name, transport, scope, auth)
        except client_config.InvalidRequest:
            continue
        checked += 1
        if result["format"] == "toml" and tomllib is None:
            continue
        data = parsed(result)
        servers = (
            data["mcp_servers"]
            if spec.format in {"toml", "yaml"}
            else data[spec.container_key]
        )
        entry = servers["marm-memory"]
        if transport == "http":
            assert URL in json.dumps(entry)
        else:
            assert isinstance(entry["command"], str)
            assert isinstance(entry["args"], list)
        assert SECRET not in result["text"]
        assert all(SECRET not in note for note in result["notes"])
        assert result["client"] == client and result["os"] == os_name
    assert checked > 200


def test_entries_match_what_configure_would_write() -> None:
    for client in ("cursor", "vscode", "antigravity", "windsurf", "kiro", "claude"):
        auth = client != "antigravity"
        expected = client_config.build_entry(client, "http", URL, auth)
        spec = client_config.REGISTRY[client]
        entry = json.loads(make(client, "linux", "http", "user", auth)["text"])[
            spec.container_key
        ]["marm-memory"]
        assert entry == expected


def test_container_keys_and_key_references() -> None:
    vscode = json.loads(make("vscode", "linux", "http", "user", True)["text"])
    assert vscode["servers"]["marm-memory"]["headers"] == {
        "Authorization": "Bearer ${input:marm-api-key}"
    }
    assert vscode["inputs"][0]["id"] == "marm-api-key"
    cursor = json.loads(make("cursor", "linux", "http", "user", True)["text"])
    assert cursor["mcpServers"]["marm-memory"]["headers"] == {
        "Authorization": "Bearer ${env:MARM_API_KEY}"
    }
    windsurf = json.loads(make("windsurf", "linux", "http", "user", True)["text"])
    assert windsurf["mcpServers"]["marm-memory"]["serverUrl"] == URL
    agy = json.loads(make("antigravity", "linux", "http", "user", False)["text"])
    assert agy["mcpServers"]["marm-memory"] == {"serverUrl": URL}


def test_codex_toml_fragment() -> None:
    result = make("codex", "linux", "http", "user", True)
    assert result["format"] == "toml"
    assert result["text"] == (
        '[mcp_servers.marm-memory]\nurl = "http://127.0.0.1:8001/mcp"\n'
        'bearer_token_env_var = "MARM_API_KEY"\n'
    )
    assert parsed(result)["mcp_servers"]["marm-memory"]["bearer_token_env_var"] == (
        "MARM_API_KEY"
    )
    stdio = make("codex", "macos", "stdio", "project", False)
    assert stdio["path"] == "<project>/.codex/config.toml"
    assert 'command = "marm-mcp-stdio"' in stdio["text"]
    assert any("trust" in note for note in stdio["notes"])


def test_cursor_snippet_mentions_the_cli_and_still_has_no_add_command() -> None:
    result = make("cursor", "linux", "http", "user", False)

    assert any("agent mcp list" in note for note in result["notes"])
    entry = json.loads(result["text"])["mcpServers"]["marm-memory"]
    assert "type" not in entry
    assert commands("http", "user")["cursor"]["command"] is None


def test_cline_json_fragment_and_paths() -> None:
    http = make("cline", "linux", "http", "user", False)
    assert http["path"] == "~/.cline/data/settings/cline_mcp_settings.json"
    assert json.loads(http["text"])["mcpServers"]["marm-memory"] == {
        "type": "streamableHttp",
        "url": URL,
    }
    assert make("cline", "windows", "http", "user", False)["path"] == (
        "~\\.cline\\data\\settings\\cline_mcp_settings.json"
    )
    assert any("VS Code and JetBrains" in note for note in http["notes"])
    stdio = json.loads(make("cline", "macos", "stdio", "user", False)["text"])
    assert stdio["mcpServers"]["marm-memory"]["type"] == "stdio"
    with pytest.raises(client_config.InvalidRequest, match="user scope only"):
        make("cline", "linux", "http", "project", False)
    with pytest.raises(client_config.InvalidRequest, match="STDIO"):
        make("cline", "linux", "http", "user", True)


def test_cline_commands_cover_transports_and_never_carry_a_key() -> None:
    assert commands("http", "user")["cline"]["command"] == (
        f"cline mcp install marm-memory --yes --transport http {URL}"
    )
    keyed = commands("http", "user", auth=True)["cline"]
    assert keyed["command"] is None and "STDIO" in keyed["note"]
    assert SECRET not in json.dumps(keyed)
    assert commands("stdio", "user")["cline"]["command"] == (
        "cline mcp install marm-memory --yes -- marm-mcp-stdio"
    )
    argv = client_snippets._docker_argv("linux", "latest")
    assert commands("docker-stdio", "user")["cline"]["command"] == (
        f"cline mcp install marm-memory --yes -- {shlex.join(argv)}"
    )
    project = commands("stdio", "project")["cline"]
    assert project["command"] is None and "user scope" in project["note"]


def test_hermes_yaml_fragment_and_paths() -> None:
    keyed = make("hermes", "linux", "http", "user", True)
    assert keyed["format"] == "yaml"
    assert keyed["path"] == "~/.hermes/config.yaml"
    assert keyed["text"] == (
        "mcp_servers:\n"
        "  marm-memory:\n"
        f'    url: "{URL}"\n'
        "    headers:\n"
        '      Authorization: "Bearer ${MARM_API_KEY}"\n'
    )
    assert parsed(keyed)["mcp_servers"]["marm-memory"]["headers"] == {
        "Authorization": "Bearer ${MARM_API_KEY}"
    }
    assert SECRET not in keyed["text"]
    assert any("HERMES_HOME" in note for note in keyed["notes"])
    assert make("hermes", "windows", "http", "user", False)["path"] == (
        "%LOCALAPPDATA%\\hermes\\config.yaml"
    )
    assert make("hermes", "macos", "http", "user", False)["path"] == (
        "~/.hermes/config.yaml"
    )
    stdio = parsed(make("hermes", "linux", "stdio", "user", False))
    assert stdio["mcp_servers"]["marm-memory"] == {
        "command": "marm-mcp-stdio",
        "args": [],
    }


def test_hermes_snippet_is_user_scope_only() -> None:
    with pytest.raises(client_config.InvalidRequest, match="user scope only"):
        make("hermes", "linux", "http", "project", False)


def test_hermes_commands_cover_transports_and_defer_keyed_http_to_the_snippet() -> None:
    assert commands("http", "user")["hermes"]["command"] == (
        f"hermes mcp add marm-memory --url {URL}"
    )
    keyed = commands("http", "user", auth=True)["hermes"]
    assert keyed["command"] is None
    assert "MARM_API_KEY" in keyed["note"] and "snippet" in keyed["note"]
    assert SECRET not in json.dumps(keyed)
    assert commands("stdio", "user")["hermes"]["command"] == (
        "hermes mcp add marm-memory --command marm-mcp-stdio"
    )
    argv = client_snippets._docker_argv("linux", "latest")
    assert commands("docker-stdio", "user")["hermes"]["command"] == (
        f"hermes mcp add marm-memory --command docker --args {shlex.join(argv[1:])}"
    )
    project = commands("stdio", "project")["hermes"]
    assert project["command"] is None and "user scope" in project["note"]


def test_grok_toml_fragment_and_paths() -> None:
    keyed = make("grok", "linux", "http", "user", True)
    assert keyed["format"] == "toml"
    assert keyed["path"] == "~/.grok/config.toml"
    assert keyed["text"] == (
        '[mcp_servers.marm-memory]\nurl = "http://127.0.0.1:8001/mcp"\n'
        'bearer_token_env_var = "MARM_API_KEY"\n'
    )
    project = make("grok", "windows", "stdio", "project", False)
    assert project["path"] == "<project>\\.grok\\config.toml"
    assert 'command = "marm-mcp-stdio"' in project["text"]
    assert not any("trust" in note for note in project["notes"])


@pytest.mark.parametrize(
    ("client", "os_name", "expected"),
    [
        ("vscode", "windows", "%APPDATA%\\Code\\User\\mcp.json"),
        ("vscode", "macos", "~/Library/Application Support/Code/User/mcp.json"),
        ("vscode", "linux", "~/.config/Code/User/mcp.json"),
        ("claude-desktop", "windows", "%APPDATA%\\Claude\\claude_desktop_config.json"),
        (
            "claude-desktop",
            "macos",
            "~/Library/Application Support/Claude/claude_desktop_config.json",
        ),
        ("windsurf", "windows", "%APPDATA%\\devin\\mcp_config.json"),
        ("windsurf", "linux", "~/.config/devin/mcp_config.json"),
        ("cursor", "windows", "~\\.cursor\\mcp.json"),
        ("cursor", "linux", "~/.cursor/mcp.json"),
        ("claude", "macos", "~/.claude.json"),
        ("kiro", "windows", "~\\.kiro\\settings\\mcp.json"),
        ("antigravity", "macos", "~/.gemini/config/mcp_config.json"),
        ("antigravity", "windows", "~\\.gemini\\config\\mcp_config.json"),
        ("codex", "linux", "~/.codex/config.toml"),
    ],
)
def test_user_paths_per_os(client, os_name, expected) -> None:
    transport = "stdio" if client == "claude-desktop" else "http"
    assert make(client, os_name, transport, "user", False)["path"] == expected


def test_project_paths_use_the_placeholder() -> None:
    assert (
        make("cursor", "windows", "http", "project", False)["path"]
        == "<project>\\.cursor\\mcp.json"
    )
    assert (
        make("claude", "linux", "http", "project", False)["path"]
        == "<project>/.mcp.json"
    )


def test_no_absolute_local_home_leaks_into_paths_or_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(client_config, "_home", lambda: tmp_path)
    for client, os_name, transport, scope, auth in all_cases():
        try:
            result = make(client, os_name, transport, scope, auth)
        except client_config.InvalidRequest:
            continue
        assert str(tmp_path) not in result["path"] + result["text"]


def test_unsupported_combinations_are_422_with_a_reason() -> None:
    with pytest.raises(client_config.InvalidRequest, match="not available on linux"):
        make("claude-desktop", "linux", "stdio", "user", False)
    with pytest.raises(client_config.InvalidRequest, match="STDIO"):
        make("claude-desktop", "macos", "http", "user", False)
    with pytest.raises(client_config.InvalidRequest, match="user scope only"):
        make("windsurf", "linux", "http", "project", False)
    with pytest.raises(client_config.InvalidRequest, match="STDIO"):
        make("antigravity", "linux", "http", "user", True)
    with pytest.raises(client_config.InvalidRequest, match="Unknown transport"):
        make("cursor", "linux", "carrier-pigeon", "user", False)
    with pytest.raises(client_config.InvalidRequest, match="Unknown scope"):
        make("cursor", "linux", "http", "team", False)
    with pytest.raises(client_config.InvalidRequest, match="Unknown os"):
        make("cursor", "plan9", "http", "user", False)
    with pytest.raises(client_config.ClientNotFound):
        make("nope", "linux", "http", "user", False)


@pytest.mark.parametrize(
    ("os_name", "data_dir"),
    [
        ("windows", "C:\\Users\\you\\.marm"),
        ("macos", "/Users/you/.marm"),
        ("linux", "/home/you/.marm"),
    ],
)
def test_docker_stdio_uses_the_planner_argv_with_a_placeholder_data_dir(
    os_name, data_dir
) -> None:
    result = make("cursor", os_name, "docker-stdio", "user", False)
    entry = json.loads(result["text"])["mcpServers"]["marm-memory"]
    assert entry["command"] == "docker"
    assert f"type=bind,src={data_dir},dst=/home/marm/.marm" in entry["args"]
    assert entry["args"][-3:-1] == ["--entrypoint", "marm-mcp-stdio"]
    assert entry["args"][-1].endswith(":latest")
    assert ("--user" in entry["args"]) == (os_name == "linux")
    assert any("absolute path" in note for note in result["notes"])


def test_docker_stdio_honors_the_tag() -> None:
    result = client_snippets.snippet(
        "cursor", "linux", "docker-stdio", "user", URL, False, docker_tag="v2.55.0"
    )
    assert json.loads(result["text"])["mcpServers"]["marm-memory"]["args"][-1].endswith(
        ":v2.55.0"
    )


def test_stdio_uses_the_bare_command_and_warns_about_gui_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        client_config.shutil, "which", lambda name: "C:\\somewhere\\marm-mcp-stdio.exe"
    )
    result = make("cursor", "windows", "stdio", "user", False)
    entry = json.loads(result["text"])["mcpServers"]["marm-memory"]
    assert entry == {"command": "marm-mcp-stdio", "args": []}
    assert "where marm-mcp-stdio" in result["notes"][0]
    assert (
        "which marm-mcp-stdio"
        in make("cursor", "linux", "stdio", "user", False)["notes"][0]
    )


def test_docker_http_snippet_uses_the_docker_url_with_reference() -> None:
    result = make("cursor", "linux", "http", "user", True, url=DOCKER_URL)
    entry = json.loads(result["text"])["mcpServers"]["marm-memory"]
    assert entry["url"] == DOCKER_URL
    assert entry["headers"]["Authorization"] == "Bearer ${env:MARM_API_KEY}"


def commands(transport, scope, auth=False, url=URL, os_name="linux"):
    return {
        c["client"]: c
        for c in client_snippets.agent_commands(
            transport, scope, url, auth, os_name=os_name
        )
    }


def test_agent_commands_http_exact_strings() -> None:
    plain = commands("http", "user")
    assert plain["claude"]["command"] == (
        f"claude mcp add --transport http --scope user marm-memory {URL}"
    )
    assert plain["codex"]["command"] == f"codex mcp add marm-memory --url {URL}"
    assert plain["antigravity"]["command"] == (
        f"agy mcp add marm-memory --type http {URL}"
    )
    assert plain["qwen"]["command"] == (
        f"qwen mcp add --transport http --scope user marm-memory {URL}"
    )
    assert plain["vscode"]["command"] == (
        f'code --add-mcp \'{{"name":"marm-memory","type":"http","url":"{URL}"}}\''
    )
    for client in ("cursor", "windsurf", "kiro", "claude-desktop"):
        assert plain[client]["command"] is None
        assert "config file snippet" in plain[client]["note"]


def test_grok_commands_cover_transports_scopes_and_the_key_reference() -> None:
    plain = commands("http", "user")["grok"]["command"]
    assert plain == f"grok mcp add --transport http marm-memory {URL}"
    keyed = commands("http", "user", auth=True)["grok"]
    assert keyed["command"] is None
    assert "MARM_API_KEY" in keyed["note"] and "snippet" in keyed["note"]
    assert SECRET not in json.dumps(keyed)
    assert commands("http", "project")["grok"]["command"] == (
        f"grok mcp add --transport http --scope project marm-memory {URL}"
    )
    assert commands("stdio", "user")["grok"]["command"] == (
        "grok mcp add marm-memory -- marm-mcp-stdio"
    )
    assert commands("stdio", "project")["grok"]["command"] == (
        "grok mcp add --scope project marm-memory -- marm-mcp-stdio"
    )
    tail = shlex.join(client_snippets._docker_argv("linux", "latest"))
    assert commands("docker-stdio", "user")["grok"]["command"] == (
        f"grok mcp add marm-memory -- {tail}"
    )


def test_agent_commands_with_a_key_use_references_only() -> None:
    keyed = commands("http", "user", auth=True)
    assert keyed["claude"]["command"] == (
        f"claude mcp add --transport http --scope user marm-memory {URL} "
        '--header "Authorization: Bearer ${MARM_API_KEY}"'
    )
    assert keyed["codex"]["command"] == (
        f"codex mcp add marm-memory --url {URL} --bearer-token-env-var MARM_API_KEY"
    )
    assert keyed["antigravity"]["command"] is None
    assert "STDIO" in keyed["antigravity"]["note"]
    assert keyed["qwen"]["command"] is None
    assert keyed["vscode"]["command"] is None
    assert SECRET not in json.dumps(keyed)


def test_agent_commands_stdio_and_project_scope() -> None:
    stdio = commands("stdio", "user")
    assert stdio["claude"]["command"] == (
        "claude mcp add --transport stdio --scope user marm-memory -- marm-mcp-stdio"
    )
    assert stdio["codex"]["command"] == "codex mcp add marm-memory -- marm-mcp-stdio"
    assert stdio["antigravity"]["command"] == (
        "agy mcp add marm-memory --type stdio -- marm-mcp-stdio"
    )
    assert json.loads(stdio["vscode"]["command"].split("'")[1]) == {
        "name": "marm-memory",
        "type": "stdio",
        "command": "marm-mcp-stdio",
        "args": [],
    }
    project = commands("stdio", "project")
    assert project["claude"]["command"] == (
        "claude mcp add --transport stdio --scope project marm-memory -- marm-mcp-stdio"
    )
    assert project["antigravity"]["command"] is None
    assert "config file snippet" in project["antigravity"]["note"]
    assert project["codex"]["command"] is None
    assert project["vscode"]["command"] is None


def test_agent_commands_docker_stdio_put_the_argv_after_double_dash() -> None:
    docker = commands("docker-stdio", "user")
    argv = client_snippets._docker_argv("linux", "latest")
    tail = shlex.join(argv)
    assert docker["claude"]["command"] == (
        f"claude mcp add --transport stdio --scope user marm-memory -- {tail}"
    )
    assert docker["codex"]["command"] == f"codex mcp add marm-memory -- {tail}"
    assert docker["antigravity"]["command"] == (
        f"agy mcp add marm-memory --type stdio -- {tail}"
    )
    payload = json.loads(docker["vscode"]["command"].split("'")[1])
    assert payload["command"] == "docker" and payload["args"] == argv[1:]


def test_agent_commands_windows_quoting_uses_the_windows_convention() -> None:
    docker = commands("docker-stdio", "user", os_name="windows")
    assert (
        "type=bind,src=C:\\Users\\you\\.marm,dst=/home/marm/.marm"
        in (docker["claude"]["command"])
    )
    assert (
        "single quotes" in commands("http", "user", os_name="windows")["vscode"]["note"]
    )


def test_agent_commands_reject_bad_input() -> None:
    with pytest.raises(client_config.InvalidRequest):
        client_snippets.agent_commands("smoke", "user", URL, False)
    with pytest.raises(client_config.InvalidRequest):
        client_snippets.agent_commands("http", "team", URL, False)
    with pytest.raises(client_config.InvalidRequest):
        client_snippets.agent_commands("http", "user", URL, False, os_name="beos")
