import json
import io
import importlib
import os
import socket
import subprocess
import sys
import urllib.request
from email.message import Message
from urllib.error import HTTPError
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from marm_mcp_server import cli
from marm_mcp_server.core import runtime_manager
from marm_mcp_server.utils import dependency_check


def _active_modules():
    return (
        importlib.import_module("marm_mcp_server.cli"),
        importlib.import_module("marm_mcp_server.core.runtime_manager"),
    )


def test_runtime_state_round_trip_and_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("MARM_RUNTIME_DIR", str(tmp_path))
    state = runtime_manager.make_state(
        runtime_id="runtime-test",
        profile="swarm",
        rate_limit_rpm=200,
    )

    runtime_manager.write_state(state)

    assert runtime_manager.read_state() == state
    assert runtime_manager.process_matches(state) is True
    runtime_manager.clear_state("different-runtime")
    assert runtime_manager.state_path().exists()
    runtime_manager.clear_state("runtime-test")
    assert not runtime_manager.state_path().exists()


def test_process_identity_rejects_reused_pid_metadata():
    process = psutil.Process(os.getpid())
    state = {
        "pid": process.pid,
        "process_created_at": process.create_time() - 100,
    }

    assert runtime_manager.process_matches(state) is False


def test_product_script_is_installed_without_removing_compatibility_commands():
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    with Path("pyproject.toml").open("rb") as project_file:
        scripts = tomllib.load(project_file)["project"]["scripts"]

    assert scripts["marm-memory"] == "marm_mcp_server.cli:main"
    assert scripts["marm-mcp-server"] == "marm_mcp_server.cli:main"
    assert scripts["marm-mcp-stdio"] == "marm_mcp_server.server_stdio:main"


def test_dependency_check_requires_bundled_knowledge_runtime(monkeypatch):
    real_find_spec = dependency_check.importlib.util.find_spec

    def find_spec(name):
        if name in {"fastembed", "apscheduler", "spacy"}:
            return None
        return real_find_spec(name)

    monkeypatch.setattr(dependency_check.importlib.util, "find_spec", find_spec)

    checks = dependency_check.dependency_checks()

    optional = {check["name"] for check in checks if not check["required"]}
    assert {"fastembed", "apscheduler"}.issubset(optional)
    spacy_check = next(check for check in checks if check["name"] == "spacy")
    model_check = next(check for check in checks if check["name"] == "concept_model")
    assert spacy_check == {
        "name": "spacy",
        "ok": False,
        "detail": "spaCy concept extraction runtime",
        "required": True,
    }
    assert model_check["required"] is True
    assert model_check["ok"] is True


def test_status_json_contains_no_decorative_output(tmp_path):
    env = os.environ.copy()
    env["MARM_RUNTIME_DIR"] = str(tmp_path / "runtime")
    env["MARM_DB_PATH"] = str(tmp_path / "missing-memory.db")
    env["MARM_CONCEPT_DB_PATH"] = str(tmp_path / "missing-concept.db")
    env["MARM_ANALYTICS_DB_PATH"] = str(tmp_path / "analytics.db")
    result = subprocess.run(
        [sys.executable, "-m", "marm_mcp_server", "status", "--json"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["runtime"]["state"] == "stopped"
    assert not (tmp_path / "runtime" / "runtime.json").exists()


def test_project_index_poll_retries_transport_failure(monkeypatch, capsys, tmp_path):
    active_cli, active_runtime = _active_modules()
    repository = tmp_path / "repo"
    repository.mkdir()
    args = SimpleNamespace(
        projects_command="index", path=str(repository), mode="moderate"
    )
    responses = iter(
        [
            active_runtime.RuntimeUnavailable("temporary timeout"),
            {"status": "running"},
            {"status": "success", "project": "repo"},
        ]
    )
    monkeypatch.setattr(active_cli, "_ensure_runtime", lambda: {})
    monkeypatch.setattr(
        active_cli, "_runtime_post", lambda *_args, **_kwargs: {"job_id": "1"}
    )

    def poll(*_args, **_kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(active_runtime, "request_runtime_strict", poll)
    monkeypatch.setattr(active_cli.time, "sleep", lambda _seconds: None)

    assert active_cli._dispatch_projects(args) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out or captured.err)["status"] == "success"


def test_strict_runtime_request_preserves_http_error_detail(monkeypatch):
    headers = Message()
    headers["Retry-After"] = "7"
    error = HTTPError(
        "http://127.0.0.1/internal/projects/index",
        409,
        "Conflict",
        headers,
        io.BytesIO(b'{"detail":"An index job is already running."}'),
    )

    def reject(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(runtime_manager.urllib.request, "urlopen", reject)

    with pytest.raises(runtime_manager.RuntimeRequestError) as exc_info:
        runtime_manager.request_runtime_strict("/internal/projects/index")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "An index job is already running."
    assert exc_info.value.retry_after == 7


def test_product_cli_reports_runtime_errors_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["marm-memory", "status"])
    monkeypatch.setattr(
        cli,
        "_dispatch_product",
        lambda _args: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == "Error: boom\n"


def test_product_key_writes_one_generated_key(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["marm-memory", "key", "generate"])
    monkeypatch.setattr(cli, "generate_api_key", lambda: "generated-key")

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert output.splitlines()[0] == "generated-key"
    assert "Set this as your MARM_API_KEY environment variable." in output
    assert "Keep it secret" in output


def test_default_status_is_human_readable(capsys):
    active_cli, _active_runtime = _active_modules()
    active_cli._print_status(
        {
            "version": "2.25.0",
            "runtime": {"state": "ready", "metadata": {"profile": "swarm"}},
            "mcp": {"state": "ready", "port": 8001},
            "console": {"state": "stopped", "port": 8002},
            "memory": {
                "exists": True,
                "memories": 4,
                "sessions": 2,
                "wal_mode": "wal",
                "size_bytes": 1024,
            },
            "write_queue": {"enabled": True, "running": True, "depth": 0},
            "knowledge": {"state": "ready", "schema": "current"},
            "projects": {"state": "not_started"},
        }
    )

    captured = capsys.readouterr()
    output = captured.out or captured.err
    assert "Runtime: ready | profile: swarm" in output
    assert "Memory: 4 records | 2 sessions" in output
    assert not output.lstrip().startswith("{")


def test_owned_log_is_bounded_and_tail_reads_latest_lines(
    monkeypatch, tmp_path, capsys
):
    active_cli, active_runtime = _active_modules()
    monkeypatch.setenv("MARM_RUNTIME_DIR", str(tmp_path))
    path = active_runtime.log_path()
    with path.open("a", encoding="utf-8") as active_writer:
        active_writer.write("old\n" * 100 + "newest\n")
        active_writer.flush()
        active_runtime.bound_log_file(path, max_bytes=100)

    assert path.stat().st_size <= 100
    assert "newest" in path.read_text(encoding="utf-8")
    assert active_cli._show_logs(1, False) == 0
    captured = capsys.readouterr()
    assert (captured.out or captured.err) == "newest\n"


def test_restart_preserves_console_process(monkeypatch, capsys):
    active_cli, active_runtime = _active_modules()
    calls = []
    monkeypatch.setattr(
        active_runtime,
        "read_state",
        lambda: {"profile": "swarm-max", "rate_limit_rpm": 600},
    )
    monkeypatch.setattr(
        active_runtime,
        "stop_runtime",
        lambda **kwargs: calls.append(("stop", kwargs)) or True,
    )
    monkeypatch.setattr(
        active_runtime,
        "start_background",
        lambda **kwargs: calls.append(("start", kwargs)) or {},
    )

    assert (
        active_cli._dispatch_product(SimpleNamespace(command="restart", force=False))
        == 0
    )

    assert calls == [
        ("stop", {"force": False, "stop_console_process": False}),
        ("start", {"profile": "swarm-max", "rate_limit_rpm": 600}),
    ]
    captured = capsys.readouterr()
    assert "Console was left available" in (captured.out or captured.err)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run_product_cli(
    env: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "marm_mcp_server", *arguments],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )


def test_managed_runtime_reuses_restarts_and_stops_cleanly(tmp_path):
    port = _free_port()
    runtime_directory = tmp_path / "runtime"
    env = os.environ.copy()
    env.update(
        {
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": str(port),
            "MARM_RUNTIME_DIR": str(runtime_directory),
            "MARM_DB_PATH": str(tmp_path / "memory.db"),
            "MARM_DOCS_DB_PATH": str(tmp_path / "docs.db"),
            "MARM_CONCEPT_DB_PATH": str(tmp_path / "concepts.db"),
            "MARM_ANALYTICS_DB_PATH": str(tmp_path / "analytics.db"),
            "HOME": str(tmp_path),
            "USERPROFILE": str(tmp_path),
        }
    )
    env.pop("MARM_API_KEY", None)
    state_path = runtime_directory / "runtime.json"

    try:
        first = _run_product_cli(env, "start", "--profile", "swarm")
        assert first.returncode == 0, first.stderr
        first_state = json.loads(state_path.read_text(encoding="utf-8"))

        duplicate = _run_product_cli(env, "start")
        assert duplicate.returncode == 0, duplicate.stderr
        duplicate_state = json.loads(state_path.read_text(encoding="utf-8"))
        assert duplicate_state["runtime_id"] == first_state["runtime_id"]
        assert duplicate_state["pid"] == first_state["pid"]

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/internal/runtime/status", timeout=5
        ) as response:
            status = json.load(response)
        assert status["runtime_id"] == first_state["runtime_id"]
        assert isinstance(status["write_queue"], dict)

        restarted = _run_product_cli(env, "restart")
        assert restarted.returncode == 0, restarted.stderr
        restarted_state = json.loads(state_path.read_text(encoding="utf-8"))
        assert restarted_state["runtime_id"] != first_state["runtime_id"]
        assert restarted_state["profile"] == "swarm"

        stopped = _run_product_cli(env, "stop")
        assert stopped.returncode == 0, stopped.stderr
        assert not state_path.exists()
        assert not psutil.pid_exists(int(restarted_state["pid"]))
    finally:
        if state_path.exists():
            _run_product_cli(env, "stop", "--force")
