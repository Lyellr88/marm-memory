from __future__ import annotations

import json
from pathlib import Path

import pytest

from marm_mcp_server.services import docker_commands


def _options(tmp_path: Path, **overrides: object) -> docker_commands.DockerRunOptions:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    values: dict[str, object] = {
        "data_dir": data_dir,
        "env_file": tmp_path / ".env",
    }
    values.update(overrides)
    return docker_commands.DockerRunOptions(**values)


def test_docker_run_plan_uses_safe_http_defaults(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()

    plan = docker_commands.build_run_plan(
        _options(
            tmp_path,
            profile="swarm",
            repositories=(repository,),
            rate_limit_rpm=200,
        )
    )
    command = plan["arguments"]

    assert command[:8] == [
        "docker",
        "run",
        "-d",
        "--name",
        "marm-mcp-server",
        "--restart",
        "unless-stopped",
        "--label",
    ]
    assert "com.marm.profile=swarm" in command
    assert (
        f"type=bind,src={(tmp_path / 'data').resolve()},dst=/home/marm/.marm" in command
    )
    assert "127.0.0.1:8001:8001" in command
    assert "SERVER_HOST=0.0.0.0" in command
    assert "MARM_RATE_LIMIT_RPM=200" in command
    assert (
        f"type=bind,src={repository.resolve()},dst=/workspace/repo-1,readonly"
        in command
    )
    assert command[-2:] == ["lyellr88/marm-mcp-server:latest", "--swarm"]
    assert all("MARM_API_KEY=" not in argument for argument in command)
    assert plan["repository_mappings"] == [
        f"{repository.resolve()} -> /workspace/repo-1"
    ]


def test_docker_run_plan_requires_explicit_network_opt_in(tmp_path):
    local = docker_commands.build_run_plan(_options(tmp_path))
    exposed = docker_commands.build_run_plan(
        _options(tmp_path, expose_network=True, port=9123)
    )

    assert "127.0.0.1:8001:8001" in local["arguments"]
    assert "0.0.0.0:9123:8001" in exposed["arguments"]


def test_docker_run_plan_rejects_invalid_inputs(tmp_path):
    with pytest.raises(docker_commands.DockerCommandError, match="--port"):
        docker_commands.build_run_plan(_options(tmp_path, port=0))
    with pytest.raises(docker_commands.DockerCommandError, match="Repository path"):
        docker_commands.build_run_plan(
            _options(tmp_path, repositories=(tmp_path / "missing",))
        )


def test_docker_previews_allow_a_new_data_directory(tmp_path):
    options = _options(tmp_path, data_dir=tmp_path / "new-data")

    command = docker_commands.build_run_plan(options, require_data_dir=False)
    compose = docker_commands.compose_document(options)

    assert command["data_dir"] == str((tmp_path / "new-data").resolve())
    assert compose["plan"]["data_dir"] == str((tmp_path / "new-data").resolve())
    assert not (tmp_path / "new-data").exists()


def test_managed_env_file_creates_key_but_explicit_file_must_contain_one(
    monkeypatch, tmp_path
):
    from marm_mcp_server.services import key_management

    managed = tmp_path / "managed.env"
    monkeypatch.setattr(docker_commands, "managed_env_file", lambda: managed)
    monkeypatch.setattr(key_management, "generate_api_key", lambda: "generated-key")

    assert docker_commands.ensure_managed_env_file() == managed
    assert managed.read_text(encoding="utf-8") == "MARM_API_KEY=generated-key\n"

    explicit = tmp_path / "explicit.env"
    explicit.write_text("OTHER=value\n", encoding="utf-8")
    with pytest.raises(docker_commands.DockerCommandError, match="does not contain"):
        docker_commands.ensure_managed_env_file(explicit)


def test_docker_status_redacts_container_environment(monkeypatch):
    monkeypatch.setattr(
        docker_commands,
        "container_inspect",
        lambda _name: {
            "Config": {
                "Image": "lyellr88/marm-mcp-server:latest",
                "Env": ["MARM_API_KEY=should-not-appear"],
                "Labels": {
                    "mcp.name": "marm-mcp-server",
                    "com.marm.profile": "swarm",
                },
            },
            "Image": "sha256:abc123",
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
            "Mounts": [{"Source": "/host/marm", "Destination": "/home/marm/.marm"}],
            "NetworkSettings": {"Ports": {"8001/tcp": [{"HostPort": "8001"}]}},
        },
    )

    status = docker_commands.docker_status()

    assert status["state"] == "running"
    assert status["image_id"] == "sha256:abc123"
    assert status["profile"] == "swarm"
    assert "should-not-appear" not in json.dumps(status)
    assert status["mounts"] == [
        {"source": "/host/marm", "destination": "/home/marm/.marm"}
    ]


def test_docker_run_refuses_to_replace_an_existing_container(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_commands, "container_inspect", lambda _name: {"Id": "1"})
    monkeypatch.setattr(
        docker_commands,
        "ensure_managed_env_file",
        lambda *_args: pytest.fail(
            "existing container must be checked before key creation"
        ),
    )

    with pytest.raises(docker_commands.DockerCommandError, match="already exists"):
        docker_commands.run_container(_options(tmp_path))


def test_docker_embedding_migration_refuses_while_http_container_runs(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        docker_commands,
        "docker_status",
        lambda _name: {"state": "running"},
    )

    with pytest.raises(
        docker_commands.DockerCommandError, match="requires the managed HTTP container"
    ):
        docker_commands.migrate_embeddings(data_dir=tmp_path)


def test_docker_embedding_migration_streams_and_returns_docker_exit_code(
    monkeypatch, tmp_path
):
    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(
        docker_commands,
        "docker_status",
        lambda _name: {"state": "absent"},
    )

    def fake_call(arguments):
        captured["arguments"] = arguments
        return 17

    monkeypatch.setattr(docker_commands.subprocess, "call", fake_call)

    assert docker_commands.migrate_embeddings(data_dir=tmp_path) == 17
    assert captured["arguments"][-1] == "--migrate-embeddings"


def test_docker_stdio_command_uses_the_real_stdio_entrypoint(tmp_path):
    plan = docker_commands.stdio_command(data_dir=tmp_path)

    assert plan["arguments"][-2:] == [
        "marm-mcp-stdio",
        "lyellr88/marm-mcp-server:latest",
    ]
    assert "MARM_API_KEY" not in " ".join(plan["arguments"])


def test_shell_command_quotes_windows_and_posix_mount_paths():
    arguments = [
        "docker",
        "run",
        "--mount",
        "type=bind,src=C:\\Users\\Marm User\\.marm,dst=/home/marm/.marm",
    ]

    windows = docker_commands.shell_command(arguments, windows=True)
    linux = docker_commands.shell_command(
        [
            "docker",
            "run",
            "--mount",
            "type=bind,src=/Users/Marm User/.marm,dst=/home/marm/.marm",
        ],
        windows=False,
    )
    macos = docker_commands.shell_command(
        [
            "docker",
            "run",
            "--mount",
            "type=bind,src=/Users/Marm User/.marm,dst=/home/marm/.marm",
        ],
        windows=False,
    )

    assert '"type=bind,src=C:\\Users\\Marm User\\.marm,dst=/home/marm/.marm"' in windows
    assert "'type=bind,src=/Users/Marm User/.marm,dst=/home/marm/.marm'" in linux
    assert macos == linux


def test_compose_document_matches_safe_run_defaults(tmp_path):
    document = docker_commands.compose_document(_options(tmp_path, profile="swarm"))[
        "document"
    ]
    service = document["services"]["marm-mcp-server"]

    assert service["image"] == "lyellr88/marm-mcp-server:latest"
    assert service["ports"] == ["127.0.0.1:8001:8001"]
    assert service["restart"] == "unless-stopped"
    assert service["command"] == ["--swarm"]
    assert service["environment"] == {"SERVER_HOST": "0.0.0.0"}
    assert service["env_file"] == [str((tmp_path / ".env").resolve())]
    assert service["volumes"][0]["target"] == "/home/marm/.marm"


def test_compose_yaml_is_human_readable_yaml(tmp_path):
    document = docker_commands.compose_document(_options(tmp_path))["document"]

    rendered = docker_commands.compose_yaml(document)

    assert rendered.startswith("services:\n")
    assert 'image: "lyellr88/marm-mcp-server:latest"' in rendered
    assert "env_file:\n" in rendered
    assert not rendered.lstrip().startswith("{")


def test_write_compose_file_refuses_overwrite_before_creating_a_key(
    monkeypatch, tmp_path
):
    output = tmp_path / "marm-compose.yaml"
    output.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(
        docker_commands,
        "ensure_managed_env_file",
        lambda *_args: pytest.fail("existing Compose file must be checked first"),
    )

    with pytest.raises(docker_commands.DockerCommandError, match="already exists"):
        docker_commands.write_compose_file(_options(tmp_path), output)
