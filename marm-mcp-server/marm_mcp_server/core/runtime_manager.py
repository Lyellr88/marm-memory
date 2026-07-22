"""Managed local HTTP runtime lifecycle for the marm-memory CLI."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from ..config.settings import MARM_API_KEY, SERVER_HOST, SERVER_PORT, SERVER_VERSION

MAX_LOG_BYTES = 5 * 1024 * 1024
_LOG_RETAIN_BYTES = MAX_LOG_BYTES // 2


class RuntimeUnavailable(RuntimeError):
    """The managed runtime could not be reached."""


class RuntimeRequestError(RuntimeError):
    """The managed runtime rejected a request."""

    def __init__(self, status_code: int, detail: str, retry_after: int | None = None):
        super().__init__(f"MARM runtime rejected request ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


def runtime_dir() -> Path:
    return Path(
        os.environ.get("MARM_RUNTIME_DIR", str(Path.home() / ".marm" / "runtime"))
    ).expanduser()


def state_path() -> Path:
    return runtime_dir() / "runtime.json"


def log_path() -> Path:
    return runtime_dir() / "runtime.log"


def _probe_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if MARM_API_KEY:
        headers["Authorization"] = f"Bearer {MARM_API_KEY}"
    return headers


def request_runtime_strict(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    host: str = SERVER_HOST,
    port: int = SERVER_PORT,
    timeout: float = 1.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://{_probe_host(host)}:{port}{path}",
        headers=_headers(),
        data=(json.dumps(payload or {}).encode("utf-8") if method != "GET" else None),
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = "The MARM runtime rejected this request."
        try:
            error_payload = json.load(exc)
            if isinstance(error_payload, dict):
                detail = str(
                    error_payload.get("detail")
                    or error_payload.get("message")
                    or error_payload.get("error")
                    or detail
                )
        except (OSError, ValueError):
            pass
        retry_after = exc.headers.get("Retry-After")
        raise RuntimeRequestError(
            exc.code,
            detail,
            int(retry_after) if retry_after and retry_after.isdigit() else None,
        ) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeUnavailable("The MARM runtime is unavailable.") from exc
    if not isinstance(result, dict):
        raise RuntimeUnavailable("The MARM runtime returned an invalid response.")
    return result


def request_runtime(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    host: str = SERVER_HOST,
    port: int = SERVER_PORT,
    timeout: float = 1.0,
) -> dict[str, Any] | None:
    """Probe the runtime without surfacing transport errors to passive callers."""
    try:
        return request_runtime_strict(
            path,
            method=method,
            payload=payload,
            host=host,
            port=port,
            timeout=timeout,
        )
    except (RuntimeRequestError, RuntimeUnavailable):
        return None


def bound_log_file(path: Path, *, max_bytes: int = MAX_LOG_BYTES) -> None:
    """Keep the newest complete portion of an owned runtime log."""
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return
        retain_bytes = min(max_bytes // 2, _LOG_RETAIN_BYTES)
        with path.open("r+b") as log_file:
            log_file.seek(-retain_bytes, os.SEEK_END)
            tail = log_file.read()
            newline = tail.find(b"\n")
            if newline >= 0:
                tail = tail[newline + 1 :]
            marker = b"[marm-memory] Earlier log output was rotated.\n"
            log_file.seek(0)
            log_file.write(marker + tail)
            log_file.truncate()
    except OSError:
        return


def start_log_maintenance(path: Path, *, interval: float = 5.0) -> None:
    """Bound an inherited managed-process log for the process lifetime."""
    bound_log_file(path)

    def maintain() -> None:
        while True:
            time.sleep(interval)
            bound_log_file(path)

    threading.Thread(target=maintain, daemon=True, name="marm-log-maintainer").start()


def read_state() -> dict[str, Any] | None:
    path = state_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_state(state: dict[str, Any]) -> None:
    directory = runtime_dir()
    directory.mkdir(parents=True, exist_ok=True)
    temporary = state_path().with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temporary, state_path())


def clear_state(runtime_id: str | None = None) -> None:
    state = read_state()
    if runtime_id and state and state.get("runtime_id") != runtime_id:
        return
    try:
        state_path().unlink(missing_ok=True)
    except OSError:
        pass


def process_matches(state: dict[str, Any]) -> bool:
    try:
        process = psutil.Process(int(state["pid"]))
        if not process.is_running():
            return False
        expected = float(state.get("process_created_at", 0))
        return not expected or abs(process.create_time() - expected) < 2.0
    except (KeyError, TypeError, ValueError, psutil.Error):
        return False


def inspect_runtime() -> dict[str, Any]:
    state = read_state()
    if state is None:
        return {"state": "stopped", "managed": False}
    process_alive = process_matches(state)
    remote = request_runtime(
        "/internal/runtime/status",
        host=str(state.get("host", SERVER_HOST)),
        port=int(state.get("port", SERVER_PORT)),
    )
    identity_matches = bool(
        remote
        and remote.get("runtime_id") == state.get("runtime_id")
        and remote.get("pid") == state.get("pid")
    )
    if identity_matches:
        current = "ready"
    elif process_alive:
        current = "starting"
    else:
        current = "stale"
    return {
        "state": current,
        "managed": True,
        "identity_matches": identity_matches,
        "process_alive": process_alive,
        "metadata": state,
        "runtime": remote,
    }


def make_state(
    *,
    runtime_id: str,
    profile: str,
    rate_limit_rpm: int | None,
    pid: int | None = None,
) -> dict[str, Any]:
    actual_pid = pid or os.getpid()
    try:
        created_at = psutil.Process(actual_pid).create_time()
    except psutil.Error:
        created_at = time.time()
    return {
        "runtime_id": runtime_id,
        "pid": actual_pid,
        "process_created_at": created_at,
        "version": SERVER_VERSION,
        "host": SERVER_HOST,
        "port": SERVER_PORT,
        "profile": profile,
        "rate_limit_rpm": rate_limit_rpm,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "log_path": str(log_path()),
    }


def _wait_for_ready(*, runtime_id: str | None, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = inspect_runtime()
        if current["state"] == "ready":
            return current
        if current["state"] in {"stale", "stopped"}:
            break
        time.sleep(0.2)
    current = inspect_runtime()
    if current["state"] == "stale":
        clear_state(runtime_id)
    raise RuntimeError(f"MARM runtime did not become ready. Check {log_path()}.")


def start_background(
    *, profile: str = "standard", rate_limit_rpm: int | None = None
) -> dict[str, Any]:
    current = inspect_runtime()
    if current["state"] == "ready":
        return current
    if current["state"] == "starting":
        return _wait_for_ready(
            runtime_id=(current.get("metadata") or {}).get("runtime_id")
        )
    if current["state"] == "stale":
        clear_state()

    runtime_id = str(uuid.uuid4())
    directory = runtime_dir()
    directory.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "marm_mcp_server",
        "start",
        "--foreground",
        "--profile",
        profile,
        "--runtime-id",
        runtime_id,
    ]
    if rate_limit_rpm is not None:
        command.extend(["--rate-limit-rpm", str(rate_limit_rpm)])
    env = os.environ.copy()
    env["MARM_RUNTIME_ID"] = runtime_id
    env["MARM_RUNTIME_PROFILE"] = profile
    creationflags = 0
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    bound_log_file(log_path())
    with log_path().open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=creationflags,
            **kwargs,
        )
    write_state(
        make_state(
            runtime_id=runtime_id,
            profile=profile,
            rate_limit_rpm=rate_limit_rpm,
            pid=process.pid,
        )
    )
    return _wait_for_ready(runtime_id=runtime_id)


def stop_runtime(
    *,
    force: bool = False,
    timeout: float = 15.0,
    stop_console_process: bool = True,
) -> bool:
    if stop_console_process:
        stop_console()
    current = inspect_runtime()
    if current["state"] == "stopped":
        return False
    state = current.get("metadata") or {}
    runtime_id = state.get("runtime_id")
    if current.get("identity_matches"):
        request_runtime(
            "/internal/runtime/shutdown",
            method="POST",
            host=str(state.get("host", SERVER_HOST)),
            port=int(state.get("port", SERVER_PORT)),
            timeout=2.0,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and process_matches(state):
            time.sleep(0.2)
    if process_matches(state):
        if not force:
            raise RuntimeError("MARM runtime did not stop cleanly; retry with --force.")
        psutil.Process(int(state["pid"])).terminate()
        try:
            psutil.Process(int(state["pid"])).wait(timeout=5)
        except psutil.TimeoutExpired:
            if os.name == "nt":
                psutil.Process(int(state["pid"])).kill()
            else:
                os.kill(int(state["pid"]), signal.SIGKILL)
    clear_state(runtime_id)
    return True


def stop_console() -> bool:
    path = runtime_dir() / "console.json"
    if not path.exists():
        return False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return False
    if not process_matches(state):
        path.unlink(missing_ok=True)
        return False
    try:
        process = psutil.Process(int(state["pid"]))
        process.terminate()
        process.wait(timeout=5)
    except psutil.TimeoutExpired:
        process.kill()
    except (KeyError, TypeError, ValueError, psutil.Error):
        return False
    finally:
        path.unlink(missing_ok=True)
    return True
