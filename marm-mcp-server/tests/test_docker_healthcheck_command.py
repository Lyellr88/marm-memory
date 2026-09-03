"""What the shipped healthcheck command actually does, not just what it says.

test_docker_static_config.py asserts the command's *text*: that a HEALTHCHECK
exists, that it probes localhost rather than the bind-all address, and that
docker-compose.yml mirrors it. Nothing asserted its *behavior*, and the
behavior had a hole: `/health` answers HTTP 200 even when its own database
probe failed -- endpoints/system.py:105-115 returns {"status": "unhealthy"}
from `except` with no status_code override -- so a command that only asks
urlopen not to raise reports a healthy container for a server that is saying
the opposite.

These run the command lifted verbatim out of the Dockerfile and out of
docker-compose.yml, with only host:port rewritten, against a stub serving the
two payload shapes the endpoint really returns. No Docker daemon needed, so
this guards the contract on every PR, not only on the Docker-marked runs.
"""

import json
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text()
COMPOSE = (REPO_ROOT / "docker-compose.yml").read_text()

# The payloads endpoints/system.py:88-115 returns, trimmed to the key the
# healthcheck has to decide on.
HEALTHY_BODY = {
    "status": "healthy",
    "service": "MARM MCP Server",
    "database": "connected",
}
UNHEALTHY_BODY = {
    "status": "unhealthy",
    "service": "MARM MCP Server",
    "error": "Service temporarily unavailable",
}


def _dockerfile_healthcheck_python() -> str:
    match = re.search(
        r'HEALTHCHECK.*?\n\s*CMD\s+python\s+-c\s+"(.+?)"', DOCKERFILE, re.DOTALL
    )
    assert match, 'Dockerfile has no `CMD python -c "..."` healthcheck'
    return match.group(1)


def _compose_healthcheck_python() -> str:
    match = re.search(r'test:\s*\["CMD",\s*"python",\s*"-c",\s*"(.+?)"\]', COMPOSE)
    assert match, "docker-compose.yml has no python healthcheck test command"
    return match.group(1)


class _StubHealth(BaseHTTPRequestHandler):
    body: dict = HEALTHY_BODY

    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(type(self).body).encode()
        self.send_response(200)  # the endpoint answers 200 on both branches
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def stub_health():
    server = HTTPServer(("127.0.0.1", 0), _StubHealth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _run(command: str, port: int) -> int:
    """Run the healthcheck exactly as the container would, against `port`."""
    assert "localhost:8001" in command, command
    return subprocess.run(
        [sys.executable, "-c", command.replace("localhost:8001", f"localhost:{port}")],
        capture_output=True,
        text=True,
        timeout=30,
    ).returncode


def test_healthcheck_passes_when_service_reports_healthy(stub_health):
    _StubHealth.body = HEALTHY_BODY
    assert _run(_dockerfile_healthcheck_python(), stub_health.server_address[1]) == 0


def test_healthcheck_fails_when_service_reports_unhealthy(stub_health):
    """The regression this file exists for: HTTP 200 carrying a self-declared
    unhealthy body must not be read as a healthy container."""
    _StubHealth.body = UNHEALTHY_BODY
    assert _run(_dockerfile_healthcheck_python(), stub_health.server_address[1]) != 0


def test_healthcheck_fails_when_nothing_is_listening(stub_health):
    """The case the old command did catch -- keep catching it."""
    port = stub_health.server_address[1]
    stub_health.shutdown()
    stub_health.server_close()
    assert _run(_dockerfile_healthcheck_python(), port) != 0


def test_dockerfile_and_compose_healthchecks_are_the_same_program():
    """The behavior tests above run the Dockerfile's copy. This is what makes
    them cover the compose copy too, and it is stricter than the substring
    check in test_docker_static_config.py."""
    assert _compose_healthcheck_python() == _dockerfile_healthcheck_python()
