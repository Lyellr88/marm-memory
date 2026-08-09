"""Managed launcher for the bundled MARM Console host."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from typing import Any

import psutil
import uvicorn


def _host() -> str:
    return os.environ.get("MARM_CONSOLE_HOST", "127.0.0.1")


def _port() -> int:
    return int(os.environ.get("MARM_CONSOLE_PORT", "8002"))


def _console_environment() -> dict[str, str]:
    from ..config.settings import MARM_API_KEY

    environment = os.environ.copy()
    if MARM_API_KEY:
        environment["MARM_API_KEY"] = MARM_API_KEY
    return environment


def _healthy(timeout: float = 0.75) -> bool:
    host = "127.0.0.1" if _host() in {"0.0.0.0", "::", "[::]"} else _host()
    try:
        with urllib.request.urlopen(
            f"http://{host}:{_port()}/health", timeout=timeout
        ) as response:
            payload = json.load(response)
            return payload.get("service") == "marm-console"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _serve() -> None:
    from ..core.runtime_manager import runtime_dir, start_log_maintenance

    start_log_maintenance(runtime_dir() / "console.log")
    uvicorn.run(
        "marm_mcp_server.console.app:app",
        host=_host(),
        port=_port(),
        log_level="info",
    )


def run_console(
    *,
    open_browser: bool = True,
    foreground: bool = False,
    import_key: bool = False,
) -> int:
    from ..core.runtime_manager import bound_log_file, runtime_dir

    url = f"http://127.0.0.1:{_port()}"
    if import_key:
        from ..config.settings import MARM_API_KEY
        from ..services.key_management import read_managed_key

        managed_key = read_managed_key()
        if not managed_key:
            raise RuntimeError(
                "No managed MARM API key exists. Run `marm-memory key init` first."
            )
        if MARM_API_KEY and not secrets.compare_digest(managed_key, MARM_API_KEY):
            raise RuntimeError(
                "The managed key does not match this runtime. Use Console Settings "
                "to enter the runtime's bearer key."
            )
        from .auth import create_bootstrap_token

        url = f"{url}/#marm-bootstrap={create_bootstrap_token(runtime_dir())}"
    if not _healthy():
        if foreground:
            if open_browser:
                webbrowser.open(url)
            _serve()
            return 0
        runtime_dir().mkdir(parents=True, exist_ok=True)
        log_path = runtime_dir() / "console.log"
        bound_log_file(log_path)
        flags = 0
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        with log_path.open("a", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [sys.executable, "-m", "marm_mcp_server.console.cli", "--serve"],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=_console_environment(),
                creationflags=flags,
                **kwargs,
            )
        (runtime_dir() / "console.json").write_text(
            json.dumps(
                {
                    "pid": process.pid,
                    "process_created_at": psutil.Process(process.pid).create_time(),
                    "host": _host(),
                    "port": _port(),
                    "log_path": str(log_path),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not _healthy():
            if process.poll() is not None:
                raise RuntimeError(f"MARM Console failed to start. Check {log_path}.")
            time.sleep(0.2)
        if not _healthy():
            raise RuntimeError(f"MARM Console did not become ready. Check {log_path}.")
    if open_browser:
        webbrowser.open(url)
    print(f"MARM Console: {url.split('/#', 1)[0]}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.serve:
        _serve()
        return
    raise SystemExit(run_console())


if __name__ == "__main__":
    main()
