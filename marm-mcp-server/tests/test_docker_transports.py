import json
import os
import socket
import subprocess
import threading
import time
import uuid

import pytest
import requests

from marm_mcp_server.server import MCP_TOOL_OPERATIONS

pytestmark = pytest.mark.docker

DOCKER_IMAGE = os.environ.get("MARM_DOCKER_IMAGE", "lyellr88/marm-mcp-server:latest")


def _run_docker(args, timeout=60):
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _docker_available():
    result = _run_docker(["ps"], timeout=20)
    return result.returncode == 0


def _image_available(image):
    result = _run_docker(["image", "inspect", image], timeout=20)
    return result.returncode == 0


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(base_url, timeout=90):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/health", timeout=3)
            if response.status_code == 200 and response.json()["status"] == "healthy":
                return
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise AssertionError(f"Docker HTTP server did not become healthy: {last_error}")


@pytest.fixture(scope="module")
def docker_image():
    if not _docker_available():
        pytest.skip("Docker daemon is not available")
    if not _image_available(DOCKER_IMAGE):
        pytest.skip(f"Docker image {DOCKER_IMAGE!r} is not available")
    return DOCKER_IMAGE


@pytest.fixture
def marm_data_dir(tmp_path):
    """Host dir bind-mounted at /home/marm/.marm. Must be world-writable: on
    Linux hosts (e.g. GitHub runners) tmp_path is owned by the host user, and
    the container's non-root marm user has a different uid, so without this
    the server can't create its DB and dies at startup. Windows Docker Desktop
    mounts are world-writable regardless, which is why this only bites in CI."""
    tmp_path.chmod(0o777)
    return tmp_path


def test_docker_http_requires_key_and_serves_tools(docker_image, marm_data_dir):
    container = f"marm-test-http-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    api_key = "TestDockerKey_12345#abcDEF"
    base_url = f"http://127.0.0.1:{port}"

    run = _run_docker(
        [
            "run",
            "-d",
            "--name",
            container,
            "-p",
            f"127.0.0.1:{port}:8001",
            "-e",
            "SERVER_HOST=0.0.0.0",
            "-e",
            f"MARM_API_KEY={api_key}",
            "-v",
            f"{marm_data_dir}:/home/marm/.marm",
            docker_image,
        ],
        timeout=90,
    )
    assert run.returncode == 0, run.stderr

    try:
        _wait_for_health(base_url)

        ready = requests.get(f"{base_url}/ready", timeout=5)
        assert ready.status_code == 200
        assert "websocket" not in ready.text.lower()

        openapi = requests.get(f"{base_url}/openapi.json", timeout=5)
        assert openapi.status_code == 200
        operation_ids = {
            operation.get("operationId")
            for path_item in openapi.json()["paths"].values()
            for operation in path_item.values()
            if isinstance(operation, dict)
        }
        assert set(MCP_TOOL_OPERATIONS).issubset(operation_ids)

        missing_auth = requests.get(
            f"{base_url}/marm_log_show", params={"session_name": "main"}, timeout=5
        )
        wrong_auth = requests.get(
            f"{base_url}/marm_log_show",
            params={"session_name": "main"},
            headers={"Authorization": "Bearer wrong"},
            timeout=5,
        )
        correct_auth = requests.get(
            f"{base_url}/marm_log_show",
            params={"session_name": "main"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5,
        )

        assert missing_auth.status_code == 401
        assert wrong_auth.status_code == 401
        assert correct_auth.status_code == 200

        no_websocket = requests.get(
            f"{base_url}/mcp/ws",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5,
        )
        assert no_websocket.status_code == 404
    finally:
        _run_docker(["rm", "-f", container], timeout=30)


def test_docker_stdio_import_keeps_stdout_clean(docker_image, marm_data_dir):
    result = _run_docker(
        [
            "run",
            "--rm",
            "-i",
            "-v",
            f"{marm_data_dir}:/home/marm/.marm",
            "--entrypoint",
            "python",
            docker_image,
            "-c",
            "import marm_mcp_server.server_stdio; assert marm_mcp_server.server_stdio.mcp is not None",
        ],
        timeout=90,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_docker_env_passthrough_reaches_runtime_settings(docker_image, marm_data_dir):
    """Environment variables passed to docker run must reach Python settings.

    This catches regressions where the image entrypoint or packaging path stops
    honoring documented runtime knobs such as MARM_DB_PATH and WRITE_QUEUE_ENABLED.
    """
    custom_db = "/home/marm/.marm/custom-env-test.db"
    result = _run_docker(
        [
            "run",
            "--rm",
            "-i",
            "-v",
            f"{marm_data_dir}:/home/marm/.marm",
            "-e",
            f"MARM_DB_PATH={custom_db}",
            "-e",
            "WRITE_QUEUE_ENABLED=0",
            "--entrypoint",
            "python",
            docker_image,
            "-c",
            (
                "from marm_mcp_server.config.settings import "
                "DEFAULT_DB_PATH, WRITE_QUEUE_ENABLED; "
                f"assert DEFAULT_DB_PATH == {custom_db!r}; "
                "assert WRITE_QUEUE_ENABLED is False"
            ),
        ],
        timeout=60,
    )

    assert result.returncode == 0, result.stderr


def test_docker_runs_as_non_root_user(docker_image):
    """Dockerfile drops to USER marm before ENTRYPOINT (see
    test_docker_static_config.py's static check on the Dockerfile itself) --
    this proves the *running* container actually honors it, not just that
    the directive is present in the file."""
    result = _run_docker(
        ["run", "--rm", "--entrypoint", "whoami", docker_image],
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "marm"


def test_docker_healthcheck_status_becomes_healthy(docker_image, marm_data_dir):
    """Exercises the container's own built-in HEALTHCHECK mechanism (docker
    inspect's Health.Status), not just our own HTTP polling of /health like
    test_docker_http_requires_key_and_serves_tools does -- these are
    different code paths (Docker's healthcheck runner vs. a plain HTTP
    client) and either can be broken independently."""
    container = f"marm-test-health-{uuid.uuid4().hex[:10]}"
    port = _free_port()

    run = _run_docker(
        [
            "run",
            "-d",
            "--name",
            container,
            "-p",
            f"127.0.0.1:{port}:8001",
            "-e",
            "SERVER_HOST=0.0.0.0",
            "-v",
            f"{marm_data_dir}:/home/marm/.marm",
            docker_image,
        ],
        timeout=90,
    )
    assert run.returncode == 0, run.stderr

    try:
        _wait_for_health(f"http://127.0.0.1:{port}")

        deadline = time.time() + 60
        status = None
        while time.time() < deadline:
            inspect = _run_docker(
                ["inspect", "--format={{.State.Health.Status}}", container],
                timeout=20,
            )
            status = inspect.stdout.strip()
            if status == "healthy":
                break
            time.sleep(2)

        assert status == "healthy", (
            f"container health status never became healthy (last: {status})"
        )
    finally:
        _run_docker(["rm", "-f", container], timeout=30)


def test_docker_dashboard_mounted_and_reachable(docker_image, marm_data_dir):
    """The v2.16.1 packaging unification made the dashboard bundled into the
    same process/port as the main server (see docker-compose.yml's comment:
    'memory + graph + dashboard, one port') -- this must hold for every
    build of the image, not just the one it was true for at the time."""
    container = f"marm-test-dashboard-{uuid.uuid4().hex[:10]}"
    port = _free_port()

    run = _run_docker(
        [
            "run",
            "-d",
            "--name",
            container,
            "-p",
            f"127.0.0.1:{port}:8001",
            "-e",
            "SERVER_HOST=0.0.0.0",
            "-v",
            f"{marm_data_dir}:/home/marm/.marm",
            docker_image,
        ],
        timeout=90,
    )
    assert run.returncode == 0, run.stderr

    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_health(base_url)

        response = requests.get(f"{base_url}/dashboard/health", timeout=5)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        _run_docker(["rm", "-f", container], timeout=30)


def test_docker_http_container_stops_gracefully(docker_image, marm_data_dir):
    """SIGTERM from docker stop should shut down the HTTP server cleanly."""
    container = f"marm-test-stop-{uuid.uuid4().hex[:10]}"
    port = _free_port()

    run = _run_docker(
        [
            "run",
            "-d",
            "--name",
            container,
            "-p",
            f"127.0.0.1:{port}:8001",
            "-e",
            "SERVER_HOST=0.0.0.0",
            "-e",
            "MARM_API_KEY=TestStopKey_12345#abcDEF",
            "-v",
            f"{marm_data_dir}:/home/marm/.marm",
            docker_image,
        ],
        timeout=90,
    )
    assert run.returncode == 0, run.stderr

    try:
        _wait_for_health(f"http://127.0.0.1:{port}")
        stopped = _run_docker(["stop", "-t", "10", container], timeout=30)
        assert stopped.returncode == 0, stopped.stderr

        inspect = _run_docker(
            ["inspect", "--format={{.State.ExitCode}}", container], timeout=20
        )
        assert inspect.returncode == 0, inspect.stderr
        assert inspect.stdout.strip() == "0"
    finally:
        _run_docker(["rm", "-f", container], timeout=30)


def test_docker_data_persists_across_container_restart(docker_image, marm_data_dir):
    """~/.marm is meant to be the durable state; a fresh container over the
    same volume mount must see data written by a previous, now-removed
    container -- proves the volume mount actually round-trips the memory DB,
    not just that the container can read/write within its own lifetime."""
    api_key = "TestPersistKey_12345#abcDEF"
    session_name = f"persist-test-{uuid.uuid4().hex[:8]}"

    def _start(name):
        port = _free_port()
        run = _run_docker(
            [
                "run",
                "-d",
                "--name",
                name,
                "-p",
                f"127.0.0.1:{port}:8001",
                "-e",
                "SERVER_HOST=0.0.0.0",
                "-e",
                f"MARM_API_KEY={api_key}",
                "-v",
                f"{marm_data_dir}:/home/marm/.marm",
                docker_image,
            ],
            timeout=90,
        )
        assert run.returncode == 0, run.stderr
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_health(base_url)
        return base_url

    first_container = f"marm-test-persist-a-{uuid.uuid4().hex[:10]}"
    second_container = f"marm-test-persist-b-{uuid.uuid4().hex[:10]}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        base_url = _start(first_container)
        # This is the first marm_log_entry call in a brand-new container, so it
        # also pays the one-time cold-start cost of loading the semantic encoder
        # (dual-write now embeds every log entry) -- measured ~4.5s locally, so
        # 5s was too tight and flaked under any extra container overhead.
        write = requests.post(
            f"{base_url}/marm_log_entry",
            json={
                "entry": f"2026-07-07-persist-check-wrote from {first_container}",
                "session_name": session_name,
            },
            headers=headers,
            timeout=20,
        )
        assert write.status_code == 200
    finally:
        _run_docker(["rm", "-f", first_container], timeout=30)

    try:
        base_url = _start(second_container)
        read = requests.get(
            f"{base_url}/marm_log_show",
            params={"session_name": session_name},
            headers=headers,
            timeout=5,
        )
        assert read.status_code == 200
        assert "persist-check" in read.text
    finally:
        _run_docker(["rm", "-f", second_container], timeout=30)


def test_docker_stdio_tool_count_matches_http_registered_tools(
    docker_image, marm_data_dir
):
    """STDIO and HTTP must expose the same tool surface from the same image
    (see CHANGELOG's "STDIO Graph Tool Parity" entry) -- this proves parity
    inside the actual built image, not just in the in-process test suite.

    Stdin stays open until the tools/list response is read: writing all
    messages and closing immediately (subprocess.run with input=) races the
    server's EOF shutdown against its processing of the still-queued request,
    which flaked on slow CI runners. Real MCP clients hold stdin open too."""
    container = f"marm-test-stdio-{uuid.uuid4().hex[:10]}"

    def message(msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    stdin_data = (
        message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "docker-test-client", "version": "0.1"},
                },
            }
        )
        + message(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        + message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    )

    proc = subprocess.Popen(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            container,
            "-v",
            f"{marm_data_dir}:/home/marm/.marm",
            "--entrypoint",
            "python",
            docker_image,
            "-m",
            "marm_mcp_server.server_stdio",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    watchdog = threading.Timer(90, proc.kill)
    responses = {}
    try:
        watchdog.start()
        proc.stdin.write(stdin_data)
        proc.stdin.flush()
        while 2 not in responses:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in msg:
                responses[msg["id"]] = msg
        proc.stdin.close()
        proc.wait(timeout=30)
    finally:
        watchdog.cancel()
        proc.kill()
        proc.stdout.close()
        stderr_text = proc.stderr.read().decode("utf-8", errors="replace")[:500]
        proc.stderr.close()
        _run_docker(["rm", "-f", container], timeout=30)

    assert 2 in responses, f"No tools/list response; stderr: {stderr_text}"
    tool_names = {t["name"] for t in responses[2]["result"]["tools"]}
    assert tool_names == set(MCP_TOOL_OPERATIONS)
