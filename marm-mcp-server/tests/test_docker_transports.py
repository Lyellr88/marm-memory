import os
import socket
import subprocess
import time
import uuid

import pytest
import requests


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


def test_docker_http_requires_key_and_serves_tools(docker_image, tmp_path):
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
            f"{tmp_path}:/home/marm/.marm",
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

        missing_auth = requests.get(f"{base_url}/marm_log_show", params={"session_name": "main"}, timeout=5)
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


def test_docker_stdio_import_keeps_stdout_clean(docker_image, tmp_path):
    result = _run_docker(
        [
            "run",
            "--rm",
            "-i",
            "-v",
            f"{tmp_path}:/home/marm/.marm",
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
