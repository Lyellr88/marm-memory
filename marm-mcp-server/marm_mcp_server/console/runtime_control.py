"""Restart job owned by the Console process, so a runtime restart never takes the UI down."""

from __future__ import annotations

from typing import Any

from ..core import runtime_manager
from .jobs import JobRegistry

RESTART_COMMAND = "marm-memory restart"

_registry = JobRegistry("marm-console-restart")
_jobs = _registry.jobs


class NotManaged(RuntimeError):
    """The runtime was not started by `marm-memory`, so the Console cannot restart it."""

    def __init__(self) -> None:
        super().__init__("The runtime is not managed by MARM, restart it yourself.")
        self.command = RESTART_COMMAND


def _restart() -> None:
    from ..cli import resolve_restart_preset

    profile, rate_limit_rpm = resolve_restart_preset(runtime_manager.read_state() or {})
    runtime_manager.stop_runtime(stop_console_process=False)
    runtime_manager.start_background(profile=profile, rate_limit_rpm=rate_limit_rpm)


def start_restart() -> str:
    if not runtime_manager.inspect_runtime().get("managed"):
        raise NotManaged
    return _registry.start("restart", "runtime", _restart)


def get_job(job_id: str) -> dict[str, Any] | None:
    return _registry.get(job_id)
