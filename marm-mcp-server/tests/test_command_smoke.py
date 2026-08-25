from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import venv
import warnings
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TRACEBACK = "Traceback (most recent call last)"
PRODUCT_ENTRYPOINT = (
    "import sys\n"
    "from marm_mcp_server.cli import main\n"
    "sys.argv = ['marm-memory', *sys.argv[1:]]\n"
    "main()\n"
)

COMMAND_HELP_PATHS = (
    ("start",),
    ("http",),
    ("fast-start-http",),
    ("stdio",),
    ("stop",),
    ("restart",),
    ("status",),
    ("console",),
    ("logs",),
    ("doctor",),
    ("knowledge",),
    ("knowledge", "status"),
    ("knowledge", "build"),
    ("knowledge", "auto"),
    ("projects",),
    ("projects", "list"),
    ("projects", "index"),
    ("projects", "status"),
    ("projects", "remove"),
    ("projects", "auto"),
    ("maintenance",),
    ("maintenance", "status"),
    ("maintenance", "embeddings"),
    ("maintenance", "embeddings", "migrate"),
    ("maintenance", "chunks"),
    ("maintenance", "chunks", "rechunk"),
    ("maintenance", "compaction"),
    ("maintenance", "compaction", "dry-run"),
    ("key",),
    ("key", "generate"),
    ("key", "init"),
    ("key", "path"),
    ("key", "reveal"),
    ("docker",),
    ("docker", "status"),
    ("docker", "pull"),
    ("docker", "run"),
    ("docker", "command"),
    ("docker", "compose"),
    ("docker", "stdio-command"),
    ("docker", "logs"),
    ("docker", "stop"),
    ("docker", "upgrade"),
    ("docker", "maintenance"),
    ("docker", "maintenance", "embeddings"),
    ("docker", "maintenance", "embeddings", "migrate"),
    ("upgrade",),
    ("update",),
    ("uninstall",),
    ("init",),
    ("version",),
)

SAFE_DISPATCHES = (
    ("version",),
    ("status",),
    ("logs", "--lines", "1"),
    ("doctor", "--json"),
    ("knowledge", "status"),
    ("maintenance", "status", "--json"),
    ("key", "generate"),
    ("key", "path"),
    ("uninstall",),
    ("docker", "command"),
    ("docker", "compose"),
    ("docker", "stdio-command"),
    ("docker", "run", "--dry-run"),
)
SAFE_DISPATCH_EXIT_CODES = {
    ("doctor", "--json"): {0, 1},
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _isolated_environment(tmp_path: Path, *, port: int | None = None) -> dict[str, str]:
    home = tmp_path / "home"
    (home / ".marm").mkdir(parents=True)
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "MARM_DB_PATH": str(home / ".marm" / "memory.db"),
            "MARM_ANALYTICS_DB_PATH": str(home / ".marm" / "analytics.db"),
            "MARM_CONCEPT_DB_PATH": str(home / ".marm" / "index" / "concepts.db"),
            "MARM_DOCS_DB_PATH": str(home / ".marm" / "docs" / "marm_docs.db"),
            "PIP_CACHE_DIR": str(tmp_path / "pip-cache"),
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": str(port or _free_port()),
        }
    )
    environment.pop("MARM_API_KEY", None)
    return environment


def _run_product(
    arguments: tuple[str, ...] | list[str],
    environment: dict[str, str],
    *,
    python_executable: Path | None = None,
    cwd: Path | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(python_executable or sys.executable),
            "-c",
            PRODUCT_ENTRYPOINT,
            *arguments,
        ],
        cwd=cwd or PACKAGE_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _assert_clean(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout + result.stderr
    assert TRACEBACK not in output, output


def _parser_command_paths(parser: argparse.ArgumentParser) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()

    def visit(current: argparse.ArgumentParser, prefix: tuple[str, ...]) -> None:
        for action in current._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, child in action.choices.items():
                path = (*prefix, name)
                paths.add(path)
                visit(child, path)

    visit(parser, ())
    return paths


@pytest.mark.smoke
def test_static_inventory_matches_registered_product_parser():
    from marm_mcp_server.services.cli_parser import _product_parser

    assert set(COMMAND_HELP_PATHS) == _parser_command_paths(_product_parser())


@pytest.mark.smoke
def test_root_help_lists_every_registered_top_level_command():
    from marm_mcp_server.services.cli_parser import _product_help, _product_parser

    help_text = _product_help()
    top_level = {path[0] for path in _parser_command_paths(_product_parser())}
    documented = set()
    command_reference, _, _ = help_text.partition("\nExamples:")
    for line in command_reference.splitlines():
        match = re.match(r"^ {2}([a-z][a-z-]*(?:\|[a-z][a-z-]*)*)\s", line)
        if match:
            documented.update(match.group(1).split("|"))

    assert documented == top_level


@pytest.mark.smoke
def test_root_help_and_version_parse_without_a_traceback(tmp_path):
    environment = _isolated_environment(tmp_path)
    for arguments in (("--help",), ("-V",), ("version",)):
        result = _run_product(arguments, environment)
        assert result.returncode == 0, result.stderr
        _assert_clean(result)


@pytest.mark.smoke
@pytest.mark.parametrize("command_path", COMMAND_HELP_PATHS)
def test_every_command_help_route_parses_cleanly(tmp_path, command_path):
    result = _run_product((*command_path, "--help"), _isolated_environment(tmp_path))
    assert result.returncode == 0, result.stderr
    _assert_clean(result)


@pytest.mark.smoke
@pytest.mark.parametrize("arguments", SAFE_DISPATCHES)
def test_safe_command_dispatches_exit_cleanly(tmp_path, arguments):
    result = _run_product(arguments, _isolated_environment(tmp_path), timeout=45)
    expected_codes = SAFE_DISPATCH_EXIT_CODES.get(arguments, {0})
    assert result.returncode in expected_codes, result.stderr
    _assert_clean(result)


@pytest.mark.smoke
@pytest.mark.smoke_lifecycle
def test_http_foreground_reaches_health_then_stops(tmp_path):
    port = _free_port()
    environment = _isolated_environment(tmp_path, port=port)
    process = subprocess.Popen(
        [sys.executable, "-c", PRODUCT_ENTRYPOINT, "http"],
        cwd=PACKAGE_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"{base_url}/health", timeout=2
                ) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, OSError) as exc:
                last_error = exc
            time.sleep(0.2)
        else:
            raise AssertionError(
                f"MARM HTTP runtime did not become healthy: {last_error}"
            )

        stop_result = _run_product(("stop",), environment)
        assert stop_result.returncode == 0, stop_result.stderr
        _assert_clean(stop_result)
        process.wait(timeout=15)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


@pytest.mark.smoke
@pytest.mark.smoke_lifecycle
def test_managed_key_round_trip_stays_inside_isolated_home(tmp_path):
    environment = _isolated_environment(tmp_path)
    init = _run_product(("key", "init"), environment)
    assert init.returncode == 0, init.stderr
    _assert_clean(init)

    reveal = _run_product(("key", "reveal"), environment)
    assert reveal.returncode == 0, reveal.stderr
    key = reveal.stdout.strip()
    assert key
    assert "terminal capture" in reveal.stderr

    path = _run_product(("key", "path"), environment)
    assert path.returncode == 0, path.stderr
    assert key not in path.stdout
    assert Path(path.stdout.strip()).exists()


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "ps"], capture_output=True, text=True, timeout=20
        )
    except OSError:
        return False
    return result.returncode == 0


@pytest.mark.smoke_docker
def test_real_docker_command_lifecycle(tmp_path):
    if not _docker_available():
        pytest.skip("Docker daemon is not available")

    environment = _isolated_environment(tmp_path)
    container = f"marm-command-smoke-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    data_dir = tmp_path / "docker-data"
    data_dir.mkdir()
    run_arguments = (
        "docker",
        "run",
        "--name",
        container,
        "--port",
        str(port),
        "--data-dir",
        str(data_dir),
    )
    try:
        pull = _run_product(("docker", "pull"), environment, timeout=180)
        assert pull.returncode == 0, pull.stderr
        run = _run_product(run_arguments, environment, timeout=90)
        assert run.returncode == 0, run.stderr
        status = _run_product(("docker", "status", "--name", container), environment)
        assert status.returncode == 0, status.stderr
        assert '"state": "running"' in status.stdout
        logs = _run_product(("docker", "logs", "--name", container), environment)
        assert logs.returncode == 0, logs.stderr
    finally:
        stop = _run_product(("docker", "stop", "--name", container), environment)
        if stop.returncode != 0:
            warnings.warn(f"Docker smoke cleanup failed: {stop.stderr}", stacklevel=2)


@pytest.mark.smoke_destructive
def test_destructive_uninstall_reinstalls_in_disposable_environment(tmp_path):
    wheel_dir = tmp_path / "wheel"
    pip_environment = os.environ.copy()
    pip_environment["PIP_CACHE_DIR"] = str(tmp_path / "pip-cache")
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(wheel_dir),
        ],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        text=True,
        env=pip_environment,
        timeout=240,
    )
    assert build.returncode == 0, build.stderr
    wheel = next(wheel_dir.glob("marm_mcp_server-*.whl"))

    environment_dir = tmp_path / "destructive-venv"
    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment_dir)
    python = environment_dir / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
        capture_output=True,
        text=True,
        env=pip_environment,
        timeout=180,
    )
    assert install.returncode == 0, install.stderr

    environment = _isolated_environment(tmp_path)
    environment["VIRTUAL_ENV"] = str(environment_dir)
    environment["PATH"] = str(python.parent) + os.pathsep + environment["PATH"]
    result = _run_product(
        ("uninstall", "--yes"),
        environment,
        python_executable=python,
        cwd=tmp_path,
        timeout=120,
    )
    _assert_clean(result)

    if os.name == "nt":
        assert result.returncode == 1
        assert "not safe" in result.stderr
        return

    try:
        assert result.returncode == 0, result.stderr
    finally:
        reinstall = subprocess.run(
            [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
            capture_output=True,
            text=True,
            env=pip_environment,
            timeout=180,
        )
        if reinstall.returncode != 0:
            warnings.warn(
                f"Destructive smoke reinstall cleanup failed: {reinstall.stderr}",
                stacklevel=2,
            )

    version = _run_product(
        ("version",), environment, python_executable=python, cwd=tmp_path
    )
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip()
