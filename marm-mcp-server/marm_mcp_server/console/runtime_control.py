"""Restart job owned by the Console process, so a runtime restart never takes the UI down."""

from __future__ import annotations

from typing import Any

from ..core import runtime_manager
from .jobs import JobConflict, JobRegistry

RESTART_COMMAND = "marm-memory restart"

_registry = JobRegistry("marm-console-runtime", reject_different_kind=True)
_jobs = _registry.jobs


class NotManaged(RuntimeError):
    """The runtime was not started by `marm-memory`, so the Console cannot restart it."""

    def __init__(self) -> None:
        super().__init__("The runtime is not managed by MARM, restart it yourself.")
        self.command = RESTART_COMMAND


class PortInUse(RuntimeError):
    reason = "port_in_use"


class PortUnchecked(RuntimeError):
    reason = "port_unchecked"


def _guard(kind: str) -> dict[str, Any]:
    current = runtime_manager.inspect_runtime()
    state = current["state"]
    if state in {"ready", "starting"}:
        if kind == "start":
            raise JobConflict("The runtime is already running or starting.")
        if current.get("managed") and current.get("identity_matches"):
            return current
        raise NotManaged
    if kind == "stop":
        raise NotManaged
    owner = runtime_manager.port_owner()
    port = runtime_manager.intended_address()[1]
    if owner == "unknown":
        raise PortUnchecked(f"Could not check port {port}. Try again.")
    if owner != "none":
        if kind == "restart":
            raise NotManaged
        raise PortInUse(f"Port {port} is in use by another program.")
    return current


def _start() -> None:
    from ..cli import resolve_restart_preset

    current = _guard("start")
    profile, rate_limit_rpm = resolve_restart_preset(runtime_manager.read_state() or {})
    if current["state"] == "stale":
        runtime_manager.clear_state((current.get("metadata") or {}).get("runtime_id"))
        _guard("start")
    runtime_manager.start_background(
        profile=profile, rate_limit_rpm=rate_limit_rpm, cleanup_on_failure=True
    )


def _stop() -> None:
    _guard("stop")
    if not runtime_manager.stop_runtime(stop_console_process=False):
        raise RuntimeError("The runtime was no longer running.")


def _restart() -> None:
    from ..cli import resolve_restart_preset

    current = _guard("restart")
    profile, rate_limit_rpm = resolve_restart_preset(runtime_manager.read_state() or {})
    if current["state"] in {"stopped", "stale"}:
        _start()
        return
    runtime_manager.stop_runtime(stop_console_process=False)
    _guard("start")
    runtime_manager.start_background(
        profile=profile, rate_limit_rpm=rate_limit_rpm, cleanup_on_failure=True
    )


def start_restart() -> str:
    return _registry.start(
        "restart", "runtime", _restart, validate=lambda: _guard("restart")
    )


def start_runtime() -> str:
    return _registry.start("start", "runtime", _start, validate=lambda: _guard("start"))


def stop_runtime() -> str:
    return _registry.start("stop", "runtime", _stop, validate=lambda: _guard("stop"))


def get_job(job_id: str) -> dict[str, Any] | None:
    return _registry.get(job_id)
