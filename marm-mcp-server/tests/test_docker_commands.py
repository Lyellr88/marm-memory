from __future__ import annotations

import json
import subprocess
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


def test_linux_plans_map_bind_mount_writes_to_the_host_user(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_commands.sys, "platform", "linux")
    monkeypatch.setattr(docker_commands.os, "getuid", lambda: 1001, raising=False)
    monkeypatch.setattr(docker_commands.os, "getgid", lambda: 1002, raising=False)

    plan = docker_commands.build_run_plan(_options(tmp_path))
    compose = docker_commands.compose_document(_options(tmp_path))["document"]
    stdio = docker_commands.stdio_command(data_dir=tmp_path)

    assert plan["container_user"] == "1001:1002"
    assert ["--user", "1001:1002"] == plan["arguments"][
        plan["arguments"].index("--user") : plan["arguments"].index("--user") + 2
    ]
    assert compose["services"]["marm-mcp-server"]["user"] == "1001:1002"
    assert ["--user", "1001:1002"] == stdio["arguments"][
        stdio["arguments"].index("--user") : stdio["arguments"].index("--user") + 2
    ]
    assert "HOME=/home/marm" in plan["arguments"]
    assert "HOME=/home/marm" in stdio["arguments"]
    assert compose["services"]["marm-mcp-server"]["environment"]["HOME"] == "/home/marm"


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
    managed = tmp_path / "managed.env"
    monkeypatch.setattr(docker_commands, "managed_env_file", lambda: managed)

    def initialize_key(path):
        path.write_text("MARM_API_KEY=generated-key\n", encoding="utf-8")
        return path, True

    monkeypatch.setattr(docker_commands, "initialize_managed_key", initialize_key)

    assert docker_commands.ensure_managed_env_file() == managed
    assert managed.read_text(encoding="utf-8") == "MARM_API_KEY=generated-key\n"

    explicit = tmp_path / "explicit.env"
    explicit.write_text("OTHER=value\n", encoding="utf-8")
    with pytest.raises(docker_commands.DockerCommandError, match="does not contain"):
        docker_commands.ensure_managed_env_file(explicit)


def test_managed_docker_refuses_to_replace_a_keychain_only_key(monkeypatch, tmp_path):
    managed = tmp_path / "managed.env"
    monkeypatch.setattr(docker_commands, "managed_env_file", lambda: managed)
    monkeypatch.setattr(
        docker_commands, "keychain_lookup", lambda: ("keychain-key", "")
    )

    with pytest.raises(docker_commands.DockerCommandError, match="--env-file"):
        docker_commands.ensure_managed_env_file()

    assert not managed.exists()


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
    assert service["environment"] == {
        "SERVER_HOST": "0.0.0.0",
        "HOME": "/home/marm",
        "XDG_CACHE_HOME": "/home/marm/.marm/cache",
    }
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


class FakeDocker:
    """Records argv lists passed to subprocess.run and answers from a script."""

    def __init__(self, monkeypatch, responder):
        self.calls: list[list[str]] = []
        self.timeouts: list[object] = []
        self.kwargs: list[dict] = []
        self._responder = responder
        monkeypatch.setattr(docker_commands.subprocess, "run", self._run)

    def _run(self, arguments, **kwargs):
        assert isinstance(arguments, list)
        assert not kwargs.get("shell")
        self.calls.append(arguments)
        self.timeouts.append(kwargs.get("timeout"))
        self.kwargs.append(kwargs)
        return self._responder(arguments)


def _completed(stdout="", stderr="", returncode=0):
    return docker_commands.subprocess.CompletedProcess([], returncode, stdout, stderr)


def _marm_payload(running=True, image="lyellr88/marm-mcp-server:latest"):
    return [
        {
            "Config": {"Image": image, "Labels": {}},
            "State": {"Status": "running" if running else "exited", "Running": running},
        }
    ]


def _foreign_payload():
    return [{"Config": {"Image": "postgres:16", "Labels": {}}, "State": {}}]


def _marm_ok(arguments):
    if arguments[:3] == ["docker", "container", "inspect"]:
        return _completed(stdout=json.dumps(_marm_payload()))
    return None


def test_engine_status_not_installed_is_distinct_from_daemon_down(monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(docker_commands.subprocess, "run", missing)
    not_installed = docker_commands.engine_status()

    FakeDocker(
        monkeypatch,
        lambda _a: _completed(
            stdout=json.dumps({"Client": {"Version": "27.1.1"}}),
            stderr="failed to connect to the docker API",
            returncode=1,
        ),
    )
    daemon_down = docker_commands.engine_status()

    assert not_installed["available"] is False
    assert "not installed" in not_installed["reason"]
    assert daemon_down["available"] is True
    assert daemon_down["daemon"] is False
    assert daemon_down["version"] == "27.1.1"
    assert "daemon is not running" in daemon_down["reason"]
    assert not_installed["reason"] != daemon_down["reason"]


def test_engine_status_healthy_uses_the_server_version_and_a_5s_timeout(monkeypatch):
    fake = FakeDocker(
        monkeypatch,
        lambda _a: _completed(
            stdout=json.dumps(
                {"Client": {"Version": "27.1.1"}, "Server": {"Version": "27.0.3"}}
            )
        ),
    )

    status = docker_commands.engine_status()

    assert status == {
        "available": True,
        "daemon": True,
        "version": "27.0.3",
        "reason": None,
    }
    assert fake.calls == [["docker", "version", "--format", "json"]]
    assert fake.timeouts == [5]


def test_engine_status_hung_daemon_times_out_as_unavailable_daemon(monkeypatch):
    def hang(arguments, **kwargs):
        raise docker_commands.subprocess.TimeoutExpired(arguments, kwargs["timeout"])

    monkeypatch.setattr(docker_commands.subprocess, "run", hang)

    status = docker_commands.engine_status()

    assert status["available"] is True
    assert status["daemon"] is False
    assert "5 seconds" in status["reason"]


def test_logs_tail_reads_one_merged_stream_and_caps_lines(monkeypatch):
    merged = "\n".join(f"out {i}" for i in range(1500)) + "\nerr last\n"
    fake = FakeDocker(monkeypatch, lambda a: _marm_ok(a) or _completed(stdout=merged))

    lines = docker_commands.logs_tail("marm-mcp-server", 5000)
    small = docker_commands.logs_tail("marm-mcp-server", 3)

    log_calls = [c for c in fake.calls if c[:2] == ["docker", "logs"]]
    assert log_calls[0] == ["docker", "logs", "--tail", "1000", "marm-mcp-server"]
    assert log_calls[1] == ["docker", "logs", "--tail", "3", "marm-mcp-server"]
    log_kwargs = [
        k
        for a, k in zip(fake.calls, fake.kwargs, strict=True)
        if a[:2] == ["docker", "logs"]
    ]
    assert all(k["stderr"] == docker_commands.subprocess.STDOUT for k in log_kwargs)
    assert len(lines) == 1000
    assert lines[-1] == "err last"
    assert small == ["out 1498", "out 1499", "err last"]


def test_docker_commands_have_a_finite_timeout_and_pull_gets_a_longer_one(monkeypatch):
    fake = FakeDocker(
        monkeypatch,
        lambda a: _marm_ok(a) or _completed(),
    )

    docker_commands.stop_container("marm-mcp-server")
    docker_commands.start_container("marm-mcp-server")
    docker_commands.restart_container("marm-mcp-server")
    docker_commands.pull_image("1.0")

    by_verb = {call[1]: t for call, t in zip(fake.calls, fake.timeouts, strict=True)}
    assert by_verb["container"] == docker_commands.DOCKER_TIMEOUT_SECONDS
    assert by_verb["stop"] == docker_commands.DOCKER_TIMEOUT_SECONDS
    assert by_verb["start"] == docker_commands.DOCKER_TIMEOUT_SECONDS
    assert by_verb["restart"] == docker_commands.DOCKER_TIMEOUT_SECONDS
    assert by_verb["pull"] == docker_commands.DOCKER_PULL_TIMEOUT_SECONDS


def test_lifecycle_commands_refuse_a_container_that_is_not_marm(monkeypatch):
    fake = FakeDocker(
        monkeypatch, lambda _a: _completed(stdout=json.dumps(_foreign_payload()))
    )

    for action in (
        docker_commands.start_container,
        docker_commands.restart_container,
        docker_commands.remove_container,
        docker_commands.stop_container,
        docker_commands.logs_tail,
    ):
        with pytest.raises(docker_commands.DockerCommandError, match="not a MARM"):
            action("postgres")

    assert all(call[:3] == ["docker", "container", "inspect"] for call in fake.calls)


def test_lifecycle_commands_on_a_marm_container_use_the_right_argv(monkeypatch):
    fake = FakeDocker(monkeypatch, lambda a: _marm_ok(a) or _completed())

    assert docker_commands.start_container("marm-mcp-server") is True
    assert docker_commands.restart_container("marm-mcp-server") is True

    actions = [c for c in fake.calls if c[1] in {"start", "restart"}]
    assert actions == [
        ["docker", "start", "marm-mcp-server"],
        ["docker", "restart", "marm-mcp-server"],
    ]


def test_lifecycle_commands_report_absent_container_without_acting(monkeypatch):
    fake = FakeDocker(monkeypatch, lambda _a: _completed(returncode=1, stderr="none"))

    assert docker_commands.start_container("marm-mcp-server") is False
    assert docker_commands.restart_container("marm-mcp-server") is False
    assert docker_commands.remove_container("marm-mcp-server") is False
    assert docker_commands.logs_tail("marm-mcp-server") == []
    assert all(call[:3] == ["docker", "container", "inspect"] for call in fake.calls)


def test_remove_container_refuses_a_running_container_and_removes_a_stopped_one(
    monkeypatch,
):
    state = {"running": True}

    def responder(arguments):
        if arguments[:3] == ["docker", "container", "inspect"]:
            return _completed(stdout=json.dumps(_marm_payload(state["running"])))
        return _completed()

    fake = FakeDocker(monkeypatch, responder)

    with pytest.raises(docker_commands.DockerCommandError, match="Stop it first"):
        docker_commands.remove_container("marm-mcp-server")
    assert not any(call[:2] == ["docker", "rm"] for call in fake.calls)

    state["running"] = False
    assert docker_commands.remove_container("marm-mcp-server") is True
    assert ["docker", "rm", "marm-mcp-server"] in fake.calls
    assert not any("-f" in call or "--force" in call for call in fake.calls)


def test_is_marm_container_honors_the_repository_override(monkeypatch):
    private = _marm_payload(image="registry.example.com/team/marm:1.0")[0]

    assert docker_commands._is_marm_container(private) is False

    monkeypatch.setenv("MARM_DOCKER_REPOSITORY", "registry.example.com/team/marm")
    assert docker_commands._is_marm_container(private) is True
    assert docker_commands._is_marm_container(_marm_payload()[0]) is True
    assert docker_commands._is_marm_container(_foreign_payload()[0]) is False


def test_is_marm_container_ignores_an_empty_override_and_a_shared_prefix(monkeypatch):
    monkeypatch.setenv("MARM_DOCKER_REPOSITORY", "")

    assert docker_commands._is_marm_container(_foreign_payload()[0]) is False
    assert docker_commands.image_reference("1.0") == "lyellr88/marm-mcp-server:1.0"

    fork = _marm_payload(image="lyellr88/marm-mcp-server-fork:1")[0]
    assert docker_commands._is_marm_container(fork) is False
    for image in (
        "lyellr88/marm-mcp-server",
        "lyellr88/marm-mcp-server:1.0",
        "lyellr88/marm-mcp-server@sha256:abc",
    ):
        assert docker_commands._is_marm_container(_marm_payload(image=image)[0]) is True


def test_write_compose_file_overwrite_backs_up_the_previous_file(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_commands, "ensure_managed_env_file", lambda *_a: None)
    output = tmp_path / "marm-compose.yaml"
    output.write_text("old: content\n", encoding="utf-8")

    payload = docker_commands.write_compose_file(
        _options(tmp_path), output, overwrite=True
    )

    backup = Path(str(output.resolve()) + ".marm-backup")
    assert payload["backup_path"] == str(backup)
    assert backup.read_text(encoding="utf-8") == "old: content\n"
    assert output.read_text(encoding="utf-8").startswith("services:\n")


def test_write_compose_file_without_an_existing_file_makes_no_backup(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(docker_commands, "ensure_managed_env_file", lambda *_a: None)
    output = tmp_path / "fresh.yaml"

    payload = docker_commands.write_compose_file(
        _options(tmp_path), output, overwrite=True
    )

    assert "backup_path" not in payload
    assert not Path(str(output.resolve()) + ".marm-backup").exists()


def test_polled_docker_calls_never_open_a_console_window(monkeypatch):
    from marm_mcp_server.utils.subprocess_flags import no_window_flags

    seen = []

    def fake_run(arguments, **kwargs):
        seen.append((arguments[1], kwargs.get("creationflags")))
        return subprocess.CompletedProcess(arguments, 1, "", "no such container")

    monkeypatch.setattr(docker_commands.subprocess, "run", fake_run)

    docker_commands.engine_status()
    docker_commands.container_inspect("marm-mcp-server")

    assert seen == [
        ("version", no_window_flags()),
        ("container", no_window_flags()),
    ]
