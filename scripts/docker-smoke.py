#!/usr/bin/env python3
"""Local Docker smoke test for MARM MCP HTTP and STDIO modes."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

ROOT = Path(__file__).resolve().parent.parent
SERVER_ROOT = ROOT / "marm-mcp-server"
IMAGE = "marm-mcp-server:smoke"
API_KEY = "MarmDockerSmokeKey_12345"


def run(command: list[str], cwd: Path = ROOT, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def print_result(name: str, ok: bool, detail: str = "") -> None:
    color = GREEN if ok else RED
    status = "PASS" if ok else "FAIL"
    print(f"{color}{status}: {name}{RESET}")
    if detail:
        print(detail.rstrip())


def docker_available() -> bool:
    result = run(["docker", "ps"], timeout=30)
    if result.returncode != 0:
        print_result("Docker daemon reachable", False, result.stderr)
        return False
    print_result("Docker daemon reachable", True)
    return True


def image_available() -> bool:
    result = run(["docker", "image", "inspect", IMAGE], timeout=30)
    return result.returncode == 0


def ask_build_image() -> bool:
    if image_available():
        answer = input(f"\nRebuild {IMAGE} before smoke test? [y/N]: ").strip().lower()
        return answer in {"y", "yes"}
    print(f"{YELLOW}{IMAGE} not found. Building it now.{RESET}")
    return True


def build_image() -> bool:
    print(f"\n{CYAN}==> Docker build {IMAGE}{RESET}")
    result = subprocess.run(["docker", "build", "-t", IMAGE, "."], cwd=SERVER_ROOT)
    ok = result.returncode == 0
    print_result("Docker image build", ok)
    return ok


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 5) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed


def wait_for_health(base_url: str) -> bool:
    deadline = time.time() + 90
    last: str = ""
    while time.time() < deadline:
        try:
            status, body = request_json(f"{base_url}/health", timeout=3)
            if status == 200 and body.get("status") == "healthy":
                print_result("HTTP health check", True)
                return True
            last = f"{status} {body}"
        except Exception as exc:
            last = repr(exc)
        time.sleep(1)
    print_result("HTTP health check", False, last)
    return False


def smoke_http() -> bool:
    container = f"marm-smoke-{uuid.uuid4().hex[:8]}"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    volume = str(Path.home() / ".marm")
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        container,
        "-p",
        f"127.0.0.1:{port}:8001",
        "-e",
        "SERVER_HOST=0.0.0.0",
        "-e",
        f"MARM_API_KEY={API_KEY}",
        "-v",
        f"{volume}:/home/marm/.marm",
        IMAGE,
    ]

    print(f"\n{CYAN}==> Docker HTTP smoke{RESET}")
    result = run(command, timeout=120)
    if result.returncode != 0:
        print_result("HTTP container start", False, result.stderr)
        return False

    try:
        if not wait_for_health(base_url):
            return False

        missing_status, _ = request_json(f"{base_url}/marm_current_context")
        wrong_status, _ = request_json(
            f"{base_url}/marm_current_context",
            {"Authorization": "Bearer wrong"},
        )
        correct_status, correct_body = request_json(
            f"{base_url}/marm_current_context",
            {"Authorization": f"Bearer {API_KEY}"},
        )

        checks = [
            ("missing bearer returns 401", missing_status == 401, str(missing_status)),
            ("wrong bearer returns 401", wrong_status == 401, str(wrong_status)),
            (
                "correct bearer reaches MCP API",
                correct_status == 200 and correct_body.get("system_status") == "operational",
                f"{correct_status} {correct_body}",
            ),
        ]

        ok = True
        for name, passed, detail in checks:
            print_result(name, passed, "" if passed else detail)
            ok = ok and passed
        return ok
    finally:
        run(["docker", "rm", "-f", container], timeout=30)


def smoke_stdio() -> bool:
    print(f"\n{CYAN}==> Docker STDIO smoke{RESET}")
    result = run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "-v",
            f"{Path.home() / '.marm'}:/home/marm/.marm",
            IMAGE,
            "python",
            "-c",
            "import marm_mcp_server.server_stdio; assert marm_mcp_server.server_stdio.mcp is not None",
        ],
        timeout=120,
    )
    ok = result.returncode == 0 and result.stdout == ""
    detail = ""
    if result.returncode != 0:
        detail = result.stderr
    elif result.stdout:
        detail = f"STDOUT was not clean:\n{result.stdout}"
    print_result("STDIO import keeps stdout clean", ok, detail)
    return ok


def main() -> int:
    if not docker_available():
        return 1
    if ask_build_image() and not build_image():
        return 1
    if not image_available():
        print_result(f"Image {IMAGE} exists", False)
        return 1

    http_ok = smoke_http()
    stdio_ok = smoke_stdio()

    if http_ok and stdio_ok:
        print(f"\n{GREEN}Docker smoke passed.{RESET}")
        return 0
    print(f"\n{RED}Docker smoke failed.{RESET}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
