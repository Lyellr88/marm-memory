"""Docker routes: engine states, saved config, jobs, guards, compose file, and the Docker agents target."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_mcp_probe import FakeMcp

from marm_mcp_server.config import settings as marm_settings
from marm_mcp_server.config import user_settings
from marm_mcp_server.console.endpoints import agents, docker, setup
from marm_mcp_server.console.terminal.router import HOST_ENV
from marm_mcp_server.services import (
    client_config,
    client_paths,
    docker_commands,
    key_management,
)

SECRET = "sk-marm-docker-secret-value"
NAME = docker_commands.DEFAULT_CONTAINER_NAME
BASE = "/api/connections/docker"

HEALTHY = {"available": True, "daemon": True, "version": "27.0.3", "reason": None}
MISSING = {
    "available": False,
    "daemon": False,
    "version": None,
    "reason": "Docker is not installed or is not on PATH.",
}
DOWN = {
    "available": True,
    "daemon": False,
    "version": "27.1.1",
    "reason": "Docker is installed but its daemon is not running.",
}


class FakeDockerHost:
    """Module-level fake of the docker_commands executors, recording every call."""

    def __init__(self) -> None:
        self.engine: dict = dict(HEALTHY)
        self.state = "absent"
        self.status_error: str | None = None
        self.calls: list[tuple] = []
        self.gate: threading.Event | None = None
        self.log_lines: list[str] = []

    def status(self, name: str) -> dict:
        if self.status_error:
            raise docker_commands.DockerCommandError(self.status_error)
        if self.state == "absent":
            return {"state": "absent", "name": name}
        return {"state": self.state, "name": name, "image": "img", "ports": {}}

    def pull_image(self, tag: str) -> str:
        self.calls.append(("pull", tag))
        if self.gate is not None:
            assert self.gate.wait(5)
        return f"repo:{tag}"

    def run_container(self, options: docker_commands.DockerRunOptions) -> dict:
        self.calls.append(("run", options))
        self.state = "running"
        return {}

    def start_container(self, name: str) -> bool:
        self.calls.append(("start", name))
        self.state = "running"
        return True

    def stop_container(self, name: str) -> bool:
        self.calls.append(("stop", name))
        if self.state == "absent":
            return False
        self.state = "exited"
        return True

    def restart_container(self, name: str) -> bool:
        self.calls.append(("restart", name))
        return self.state != "absent"

    def remove_container(self, name: str) -> bool:
        self.calls.append(("remove", name))
        self.state = "absent"
        return True

    def logs_tail(self, name: str, lines: int = 200) -> list[str]:
        self.calls.append(("logs", name, lines))
        return self.log_lines[-max(1, min(lines, 1000)) :]


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name in [s.env for s in user_settings.SETTINGS] + [
        user_settings.SHADOW_ENV,
        "MARM_TRANSPORT",
    ]:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.delenv("MARM_SETTINGS_PATH", raising=False)
    monkeypatch.delenv(HOST_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setattr(user_settings, "_home", lambda: tmp_path)
    monkeypatch.setattr(user_settings, "_in_container", lambda: False)
    monkeypatch.setattr(client_paths, "_home", lambda: tmp_path)
    monkeypatch.setattr(client_paths, "_platform", lambda: "win32")
    monkeypatch.setattr(client_config.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        key_management, "managed_key_path", lambda: tmp_path / ".marm" / ".env"
    )
    monkeypatch.setattr(key_management, "read_managed_key", lambda: "")
    monkeypatch.setattr(marm_settings, "MARM_API_KEY", "")
    monkeypatch.setattr(
        "marm_mcp_server.core.runtime_manager.inspect_runtime",
        lambda: {"state": "ready", "metadata": {"port": 8001}},
    )
    return tmp_path


@pytest.fixture
def host(home, monkeypatch) -> FakeDockerHost:
    fake = FakeDockerHost()
    monkeypatch.setattr(docker_commands, "engine_status", lambda: fake.engine)
    monkeypatch.setattr(docker_commands, "docker_status", fake.status)
    monkeypatch.setattr(docker_commands, "pull_image", fake.pull_image)
    monkeypatch.setattr(docker_commands, "run_container", fake.run_container)
    monkeypatch.setattr(docker_commands, "start_container", fake.start_container)
    monkeypatch.setattr(docker_commands, "stop_container", fake.stop_container)
    monkeypatch.setattr(docker_commands, "restart_container", fake.restart_container)
    monkeypatch.setattr(docker_commands, "remove_container", fake.remove_container)
    monkeypatch.setattr(docker_commands, "logs_tail", fake.logs_tail)
    monkeypatch.setattr(docker_commands, "ensure_managed_env_file", lambda *_a: None)
    return fake


@pytest.fixture
def client(home, host):
    docker._registry.jobs.clear()
    app = FastAPI()
    app.include_router(docker.router)
    app.include_router(agents.router)
    with TestClient(app) as test_client:
        yield test_client
    docker._registry.jobs.clear()


def wait_for_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"{BASE}/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def save_config(client: TestClient, home: Path, **overrides) -> dict:
    data = home / "marm-data"
    data.mkdir(exist_ok=True)
    body = {"port": 9002, "tag": "2.55.0", "data_dir": str(data), **overrides}
    response = client.put(f"{BASE}/config", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# --- GET /docker -----------------------------------------------------------------------


def test_get_docker_reports_defaults_and_an_absent_container(client, host, home):
    body = client.get(BASE).json()

    assert body["engine"] == HEALTHY
    assert body["in_container"] is False
    assert body["read_only_reason"] is None
    assert body["container"] == {"state": "absent", "name": NAME}
    assert body["config"] == {
        "port": 8001,
        "tag": "latest",
        "data_dir": str(home / ".marm"),
        "repos": [],
        "memory": None,
        "cpus": None,
        "expose_network": False,
        "profile": "standard",
        "rate_limit_rpm": None,
    }
    assert body["url"] == "http://127.0.0.1:8001/mcp"


def test_get_docker_passes_through_the_container_state(client, host):
    host.state = "running"

    container = client.get(BASE).json()["container"]

    assert container["state"] == "running"
    assert container["image"] == "img"


@pytest.mark.parametrize(
    "engine", [MISSING, DOWN], ids=["not-installed", "daemon-down"]
)
def test_get_docker_without_a_usable_engine_never_asks_for_the_container(
    client, host, engine
):
    host.engine = dict(engine)
    host.state = "running"

    body = client.get(BASE).json()

    assert body["engine"] == engine
    assert body["container"] == {"state": "absent", "name": NAME}


def test_get_docker_reports_a_foreign_container_as_a_conflict(client, host):
    host.status_error = f"Container {NAME!r} is not a MARM container."

    container = client.get(BASE).json()["container"]

    assert container["state"] == "conflict"
    assert "not a MARM container" in container["detail"]


def test_get_docker_uses_the_saved_port_in_the_url(client, home):
    save_config(client, home, port=9123)

    assert client.get(BASE).json()["url"] == "http://127.0.0.1:9123/mcp"


# --- PUT /docker/config ----------------------------------------------------------------


def test_put_config_persists_returns_get_and_keeps_the_allowlist(client, home):
    user_settings.save({"server.port": 9100})
    missing_dir = str(home / "does-not-exist-yet")

    body = client.put(
        f"{BASE}/config",
        json={
            "port": 9002,
            "tag": "2.55.0",
            "data_dir": missing_dir,
            "repos": [str(home)],
            "memory": "2g",
            "cpus": "1.5",
            "expose_network": True,
            "profile": "swarm-max",
            "rate_limit_rpm": 120,
        },
    ).json()

    assert body["config"]["port"] == 9002
    assert body["config"]["data_dir"] == missing_dir
    assert body["config"]["profile"] == "swarm-max"
    assert body["url"] == "http://127.0.0.1:9002/mcp"
    assert not Path(missing_dir).exists()
    on_disk = json.loads((home / ".marm" / "settings.json").read_text("utf-8"))
    assert on_disk["docker"] == body["config"]
    assert on_disk["server"] == {"port": 9100}


@pytest.mark.parametrize(
    "bad",
    [
        {"port": 0},
        {"port": 70000},
        {"tag": "has space"},
        {"tag": ""},
        {"profile": "turbo"},
        {"rate_limit_rpm": -5},
        {"memory": "2 gigs"},
        {"repos": "one"},
        {"expose_network": "yes"},
        {"unknown": 1},
    ],
)
def test_put_config_rejects_invalid_values_with_422_and_writes_nothing(
    client, home, bad
):
    response = client.put(f"{BASE}/config", json=bad)

    assert response.status_code == 422
    assert response.json()["detail"]
    assert not (home / ".marm" / "settings.json").exists()


# --- Guards ----------------------------------------------------------------------------

WRITE_ROUTES = [
    ("put", f"{BASE}/config", {"port": 9001}),
    ("post", f"{BASE}/pull", None),
    ("post", f"{BASE}/start", None),
    ("post", f"{BASE}/recreate", None),
    ("post", f"{BASE}/stop", None),
    ("post", f"{BASE}/restart", None),
    ("post", f"{BASE}/compose", {"overwrite": False}),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITE_ROUTES)
def test_write_routes_are_403_off_loopback_and_touch_nothing(
    client, host, home, monkeypatch, method, path, body
):
    monkeypatch.setenv(HOST_ENV, "0.0.0.0")

    response = getattr(client, method)(path, json=body)

    assert response.status_code == 403
    assert host.calls == []
    assert not (home / ".marm").exists()
    assert docker._registry.jobs == {}
    assert client.get(BASE).status_code == 200


@pytest.mark.parametrize(("method", "path", "body"), WRITE_ROUTES)
def test_write_routes_are_409_inside_a_container_and_touch_nothing(
    client, host, home, monkeypatch, method, path, body
):
    monkeypatch.setattr(user_settings, "_in_container", lambda: True)

    response = getattr(client, method)(path, json=body)

    assert response.status_code == 409
    assert "inside a container" in response.json()["detail"]
    assert host.calls == []
    assert not (home / ".marm").exists()
    assert docker._registry.jobs == {}


def test_reads_inside_a_container_are_read_only_or_refused(client, host, monkeypatch):
    monkeypatch.setattr(user_settings, "_in_container", lambda: True)

    body = client.get(BASE).json()

    assert body["in_container"] is True
    assert "inside a container" in body["read_only_reason"]
    assert client.get(f"{BASE}/logs").status_code == 409
    assert client.get(f"{BASE}/compose").status_code == 409
    assert host.calls == []


# --- Jobs ------------------------------------------------------------------------------


def test_pull_runs_as_a_job_for_the_saved_tag(client, host, home):
    save_config(client, home, tag="2.55.0")

    response = client.post(f"{BASE}/pull")
    job = wait_for_job(client, response.json()["job_id"])

    assert response.status_code == 202
    assert job["kind"] == "pull"
    assert job["status"] == "done"
    assert job["detail"] == "Pulled repo:2.55.0"
    assert "seconds" in job
    assert host.calls == [("pull", "2.55.0")]


def test_a_second_docker_request_returns_the_running_job(client, host, home):
    host.gate = threading.Event()
    first = client.post(f"{BASE}/pull").json()["job_id"]

    second = client.post(f"{BASE}/start").json()["job_id"]
    third = client.post(f"{BASE}/recreate").json()["job_id"]

    assert first == second == third
    assert client.get(f"{BASE}/jobs/{first}").json()["kind"] == "pull"
    host.gate.set()
    wait_for_job(client, first)
    after = client.post(f"{BASE}/pull").json()["job_id"]
    assert after != first
    wait_for_job(client, after)


def test_unknown_job_is_404(client):
    assert client.get(f"{BASE}/jobs/nope").status_code == 404


def test_start_with_no_container_runs_the_saved_config(client, host, home):
    repo = home / "repo"
    repo.mkdir()
    save_config(
        client,
        home,
        repos=[str(repo)],
        profile="swarm",
        expose_network=True,
        rate_limit_rpm=90,
        memory="1g",
        cpus="2",
    )

    job = wait_for_job(client, client.post(f"{BASE}/start").json()["job_id"])

    assert job["status"] == "done"
    (call,) = host.calls
    assert call[0] == "run"
    options = call[1]
    assert options.port == 9002
    assert options.tag == "2.55.0"
    assert options.profile == "swarm"
    assert options.data_dir == home / "marm-data"
    assert options.repositories == (repo,)
    assert all(isinstance(path, Path) for path in options.repositories)
    assert options.expose_network is True
    assert options.rate_limit_rpm == 90
    assert options.memory == "1g"
    assert options.cpus == "2"
    assert options.name == NAME


def test_start_with_a_stopped_container_uses_docker_start(client, host):
    host.state = "exited"

    job = wait_for_job(client, client.post(f"{BASE}/start").json()["job_id"])

    assert job["status"] == "done"
    assert host.calls == [("start", NAME)]


def test_start_when_already_running_does_nothing(client, host):
    host.state = "running"

    job = wait_for_job(client, client.post(f"{BASE}/start").json()["job_id"])

    assert job["status"] == "done"
    assert job["detail"] == "Already running."
    assert host.calls == []


def test_job_failure_reports_the_plain_reason(client, host, monkeypatch):
    def boom(_options):
        raise docker_commands.DockerCommandError("port is already allocated")

    monkeypatch.setattr(docker_commands, "run_container", boom)

    job = wait_for_job(client, client.post(f"{BASE}/start").json()["job_id"])

    assert job["status"] == "error"
    assert job["detail"] == "port is already allocated"
    assert "seconds" not in job


def test_recreate_stops_removes_then_runs_in_order(client, host, home):
    save_config(client, home)
    host.state = "running"

    job = wait_for_job(client, client.post(f"{BASE}/recreate").json()["job_id"])

    assert job["status"] == "done"
    assert [call[0] for call in host.calls] == ["stop", "remove", "run"]


def test_recreate_with_real_lifecycle_refuses_a_foreign_container_before_acting(
    client, host, home, monkeypatch
):
    monkeypatch.setattr(docker_commands, "stop_container", _real("stop_container"))
    monkeypatch.setattr(docker_commands, "remove_container", _real("remove_container"))
    argv: list[list[str]] = []
    monkeypatch.setattr(
        docker_commands,
        "container_inspect",
        lambda _name: {"Config": {"Image": "postgres:16", "Labels": {}}, "State": {}},
    )
    monkeypatch.setattr(
        docker_commands, "_run", lambda arguments, **_k: argv.append(arguments)
    )

    job = wait_for_job(client, client.post(f"{BASE}/recreate").json()["job_id"])

    assert job["status"] == "error"
    assert "not a MARM container" in job["detail"]
    assert argv == []
    assert not any(call[0] == "run" for call in host.calls)


_REAL = {
    name: getattr(docker_commands, name)
    for name in ("stop_container", "remove_container")
}


def _real(name: str):
    return _REAL[name]


# --- Synchronous lifecycle -------------------------------------------------------------


def test_stop_returns_the_fresh_get_body(client, host):
    host.state = "running"

    body = client.post(f"{BASE}/stop").json()

    assert host.calls == [("stop", NAME)]
    assert body["container"]["state"] == "exited"
    assert set(body) == {
        "engine",
        "in_container",
        "read_only_reason",
        "container",
        "config",
        "url",
    }


def test_restart_returns_the_fresh_get_body(client, host):
    host.state = "running"

    body = client.post(f"{BASE}/restart").json()

    assert host.calls == [("restart", NAME)]
    assert body["container"]["state"] == "running"


def test_restart_with_no_container_is_409(client, host):
    response = client.post(f"{BASE}/restart")

    assert response.status_code == 409
    assert "no MARM container" in response.json()["detail"]


def test_stop_of_a_foreign_container_is_409(client, host, monkeypatch):
    def refuse(_name):
        raise docker_commands.DockerCommandError(
            f"Container {NAME!r} is not a MARM container."
        )

    monkeypatch.setattr(docker_commands, "stop_container", refuse)

    response = client.post(f"{BASE}/stop")

    assert response.status_code == 409
    assert "not a MARM container" in response.json()["detail"]


# --- Logs ------------------------------------------------------------------------------


def test_logs_returns_the_captured_tail_and_caps_at_1000(client, host):
    host.log_lines = [f"line {i}" for i in range(1500)]

    default = client.get(f"{BASE}/logs").json()["lines"]
    three = client.get(f"{BASE}/logs", params={"lines": 3}).json()["lines"]
    huge = client.get(f"{BASE}/logs", params={"lines": 99999}).json()["lines"]

    assert host.calls[0] == ("logs", NAME, 200)
    assert len(default) == 200
    assert three == ["line 1497", "line 1498", "line 1499"]
    assert len(huge) == 1000
    assert huge[-1] == "line 1499"


def test_logs_failure_is_409(client, host, monkeypatch):
    def fail(_name, _lines=200):
        raise docker_commands.DockerCommandError(
            "Docker is not installed or is not available on PATH."
        )

    monkeypatch.setattr(docker_commands, "logs_tail", fail)

    assert client.get(f"{BASE}/logs").status_code == 409


# --- Compose ---------------------------------------------------------------------------


def test_compose_preview_writes_nothing(client, home):
    save_config(client, home, port=9010, profile="swarm")

    body = client.get(f"{BASE}/compose").json()

    path = home / ".marm" / "marm-compose.yaml"
    assert body["path"] == str(path)
    assert body["exists"] is False
    assert not path.exists()
    assert 'image: "lyellr88/marm-mcp-server:2.55.0"' in body["yaml"]
    assert "127.0.0.1:9010:8001" in body["yaml"]
    assert body["command"].startswith("docker compose -f")
    assert str(path) in body["command"]
    assert body["command"].endswith("up -d --pull always")


def test_compose_write_conflicts_then_overwrites_with_a_backup(client, home):
    save_config(client, home, port=9010)
    path = home / ".marm" / "marm-compose.yaml"

    first = client.post(f"{BASE}/compose", json={"overwrite": False})

    assert first.status_code == 200
    assert first.json()["exists"] is True
    assert first.json()["backup_path"] is None
    original = path.read_text("utf-8")
    assert "127.0.0.1:9010:8001" in original

    save_config(client, home, port=9011)
    conflict = client.post(f"{BASE}/compose", json={"overwrite": False})
    default_body = client.post(f"{BASE}/compose", json={})

    assert conflict.status_code == default_body.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["reason"] == "exists"
    assert detail["path"].endswith("marm-compose.yaml")
    assert "already exists" in detail["message"]
    assert path.read_text("utf-8") == original

    replaced = client.post(f"{BASE}/compose", json={"overwrite": True})

    backup = Path(str(path.resolve()) + ".marm-backup")
    assert replaced.status_code == 200
    assert replaced.json()["backup_path"] == str(backup)
    assert backup.read_text("utf-8") == original
    assert "127.0.0.1:9011:8001" in path.read_text("utf-8")
    assert client.get(f"{BASE}/compose").json()["exists"] is True


def test_compose_with_an_invalid_saved_repo_is_409_and_writes_nothing(client, home):
    save_config(client, home, repos=[str(home / "gone")])

    response = client.post(f"{BASE}/compose", json={"overwrite": False})

    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    assert "Repository path" in response.json()["detail"]
    assert not (home / ".marm" / "marm-compose.yaml").exists()


# --- Docker target for agents ----------------------------------------------------------


def detect_cursor(home: Path) -> Path:
    (home / ".cursor").mkdir(parents=True, exist_ok=True)
    return home / ".cursor" / "mcp.json"


def test_agents_docker_target_always_requires_a_key_and_uses_the_docker_url(
    client, home
):
    save_config(client, home, port=9123)
    detect_cursor(home)

    local = client.get("/api/connections/agents").json()
    docker_target = client.get("/api/connections/agents?target=docker").json()

    assert local["auth_required"] is False
    assert docker_target["auth_required"] is True
    cursor = next(c for c in docker_target["clients"] if c["id"] == "cursor")
    assert cursor["detected"] is True
    assert client.get("/api/connections/agents?target=nope").status_code == 422


def test_docker_target_configure_writes_key_references_and_never_the_key(
    client, home, monkeypatch
):
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    save_config(client, home, port=9123)
    config_file = detect_cursor(home)

    dry = client.post(
        "/api/connections/agents/cursor/configure",
        json={"target": "docker", "transport": "http", "dry_run": True},
    ).json()
    written = client.post(
        "/api/connections/agents/cursor/configure",
        json={"target": "docker", "transport": "http", "dry_run": False},
    )

    assert dry["entry"] == {
        "url": "http://127.0.0.1:9123/mcp",
        "headers": {"Authorization": "Bearer ${env:MARM_API_KEY}"},
    }
    assert not config_file.exists() or "9123" in config_file.read_text("utf-8")
    assert written.json()["verified"] is True
    text = config_file.read_text("utf-8")
    assert json.loads(text)["mcpServers"]["marm-memory"] == dry["entry"]
    assert SECRET not in text
    assert SECRET not in written.text
    assert SECRET not in json.dumps(dry)


def test_local_target_is_unchanged_by_the_docker_config(client, home):
    save_config(client, home, port=9123)
    detect_cursor(home)

    dry = client.post(
        "/api/connections/agents/cursor/configure",
        json={"transport": "http", "dry_run": True},
    ).json()

    assert dry["entry"] == {"url": "http://127.0.0.1:8001/mcp"}


def test_docker_target_stdio_entry_uses_the_saved_tag_and_data_dir(client, home):
    save_config(client, home, tag="2.55.0")
    detect_cursor(home)

    entry = client.post(
        "/api/connections/agents/cursor/configure",
        json={"target": "docker", "transport": "docker-stdio", "dry_run": True},
    ).json()["entry"]

    assert entry["command"] == "docker"
    assert entry["args"][-1] == "lyellr88/marm-mcp-server:2.55.0"
    data_dir = str((home / "marm-data").resolve())
    assert f"type=bind,src={data_dir},dst=/home/marm/.marm" in entry["args"]


def test_docker_target_scope_state_matches_against_the_docker_entry(client, home):
    save_config(client, home, port=9123)
    detect_cursor(home)
    client.post(
        "/api/connections/agents/cursor/configure",
        json={"target": "docker", "transport": "http"},
    )

    on_docker = client.get(
        "/api/connections/agents/cursor/scope", params={"target": "docker"}
    ).json()
    on_local = client.get("/api/connections/agents/cursor/scope").json()

    assert on_docker["state"] == "configured"
    assert on_local["state"] == "different"


def test_docker_target_test_resolves_the_managed_key_not_the_local_one(
    client, home, monkeypatch
):
    monkeypatch.setattr(key_management, "read_managed_key", lambda: SECRET)
    monkeypatch.setattr(marm_settings, "MARM_API_KEY", "a-different-local-key")
    config_file = detect_cursor(home)
    with FakeMcp(key=SECRET, tools=4) as fake:
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "marm-memory": {
                            "url": fake.url,
                            "headers": {"Authorization": "Bearer ${env:MARM_API_KEY}"},
                        }
                    }
                }
            )
        )

        response = client.post(
            "/api/connections/agents/cursor/test",
            json={"target": "docker", "scope": "user"},
        )

    body = response.json()
    assert body["ok"] is True
    assert body["tools"] == 4
    assert fake.requests[0]["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in response.text
    assert "a-different-local-key" not in response.text


def test_docker_target_test_never_falls_back_to_the_local_key(
    client, home, monkeypatch
):
    monkeypatch.setattr(marm_settings, "MARM_API_KEY", "a-different-local-key")
    config_file = detect_cursor(home)
    with FakeMcp(key="a-different-local-key") as fake:
        config_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "marm-memory": {
                            "url": fake.url,
                            "headers": {"Authorization": "Bearer ${env:MARM_API_KEY}"},
                        }
                    }
                }
            )
        )

        body = client.post(
            "/api/connections/agents/cursor/test",
            json={"target": "docker", "scope": "user"},
        ).json()

    assert body["ok"] is False
    assert body["error"]["kind"] == "unauthorized"


def test_agent_posts_still_403_off_loopback_with_the_docker_target(
    client, home, monkeypatch
):
    monkeypatch.setattr(setup, "_loopback_only", lambda: False)
    detect_cursor(home)

    response = client.post(
        "/api/connections/agents/cursor/configure",
        json={"target": "docker", "transport": "http"},
    )

    assert response.status_code == 403
