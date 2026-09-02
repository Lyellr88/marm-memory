"""Real PTY behavior tests. Every test spawns an actual shell."""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from marm_mcp_server.console.terminal.pty_session import (
    TerminalSession,
    backend_status,
    default_cwd,
    default_shell,
    shell_args,
)

IS_WINDOWS = os.name == "nt"
BACKEND = backend_status()
requires_backend = pytest.mark.skipif(
    not BACKEND.available, reason=f"No PTY backend available: {BACKEND.reason}"
)


class Collector:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.exited = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, event: dict) -> None:
        with self._lock:
            self.events.append(event)
        if event.get("type") == "exit":
            self.exited.set()

    def text(self) -> str:
        with self._lock:
            return "".join(
                event["data"] for event in self.events if event["type"] == "data"
            )

    def kinds(self) -> list[str]:
        with self._lock:
            return [event["type"] for event in self.events]

    def exit_events(self) -> list[dict]:
        with self._lock:
            return [event for event in self.events if event["type"] == "exit"]

    def wait_for(self, needle: str, timeout: float = 20.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = self.text()
            if needle in body:
                return body
            time.sleep(0.05)
        raise AssertionError(f"{needle!r} never appeared. Got:\n{self.text()[-2000:]}")


def _line(command: str) -> str:
    return f"{command}\r\n" if IS_WINDOWS else f"{command}\n"


def echo_command(marker_head: str, marker_tail: str) -> str:
    """Split the marker so a match proves execution rather than input echo."""
    if IS_WINDOWS:
        return _line(f'Write-Output ("{marker_head}" + "{marker_tail}")')
    return _line(f'echo "{marker_head}""{marker_tail}"')


def width_command() -> str:
    if IS_WINDOWS:
        return _line("$Host.UI.RawUI.WindowSize.Width")
    return _line("stty size")


_ready_marks = itertools.count()


def wait_ready(
    session: TerminalSession, collector: Collector, timeout: float = 30.0
) -> str:
    """Readiness is proven by real command output, since prompt text is shell specific."""
    marker = f"MARM_READY_{next(_ready_marks)}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session.write(echo_command(marker[:4], marker[4:]))
        try:
            return collector.wait_for(marker, timeout=3.0)
        except AssertionError:
            continue
    raise AssertionError(f"shell never became ready: {collector.text()[-2000:]}")


@pytest.fixture
def collector() -> Collector:
    return Collector()


@pytest.fixture
def session(collector: Collector):
    live = TerminalSession.spawn(emit=collector, use_profile=False, cols=80, rows=24)
    try:
        yield live
    finally:
        live.kill()
        live.wait_closed(10)


@requires_backend
def test_spawn_emits_running_status_and_registers_ids(
    session: TerminalSession, collector: Collector
) -> None:
    assert collector.kinds()[0] == "status"
    assert collector.events[0]["state"] == "running"
    assert collector.events[0]["sessionId"] == session.session_id
    assert len(session.session_id) == 36
    wait_ready(session, collector)


@requires_backend
def test_written_command_is_executed_and_output_returned(
    session: TerminalSession, collector: Collector
) -> None:
    wait_ready(session, collector)
    session.write(echo_command("MARM", "_PTY_OK"))
    body = collector.wait_for("MARM_PTY_OK")
    assert body.count("MARM_PTY_OK") >= 1


@requires_backend
def test_resize_is_visible_to_the_child_shell(
    session: TerminalSession, collector: Collector
) -> None:
    wait_ready(session, collector)
    session.resize(132, 40)
    time.sleep(0.5)
    session.write(width_command())
    body = collector.wait_for("132")
    assert "132" in body


@requires_backend
def test_kill_emits_exit_event_and_closes_session(
    session: TerminalSession, collector: Collector
) -> None:
    wait_ready(session, collector)
    session.kill()
    assert collector.exited.wait(20), "no exit event after kill"
    assert session.wait_closed(5)
    assert len(collector.exit_events()) == 1
    assert collector.exit_events()[0]["sessionId"] == session.session_id


@requires_backend
def test_clean_shell_exit_reports_the_shell_exit_code(collector: Collector) -> None:
    live = TerminalSession.spawn(emit=collector, use_profile=False)
    wait_ready(live, collector)
    live.write(_line("exit 7"))
    assert collector.exited.wait(25), "no exit event after clean exit"
    assert live.exit_code == 7
    assert collector.exit_events()[0]["code"] == 7


@requires_backend
def test_input_is_not_blocked_by_pending_output(collector: Collector) -> None:
    live = TerminalSession.spawn(emit=collector, use_profile=False, cols=80, rows=24)
    try:
        wait_ready(live, collector)
        noisy = (
            "1..500 | ForEach-Object { $_ }"
            if IS_WINDOWS
            else "for i in $(seq 1 500); do echo $i; done"
        )
        live.write(_line(noisy))
        live.resize(120, 40)
        live.write(echo_command("MARM", "_AFTER_FLOOD"))
        collector.wait_for("MARM_AFTER_FLOOD", timeout=30)
    finally:
        live.kill()
        live.wait_closed(10)


@requires_backend
def test_spawn_rejects_a_missing_working_directory(
    collector: Collector, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError, match="Working directory"):
        TerminalSession.spawn(emit=collector, cwd=str(tmp_path / "no-such-dir"))


@requires_backend
def test_spawn_rejects_an_unknown_shell(collector: Collector) -> None:
    with pytest.raises(RuntimeError, match="Shell not found"):
        TerminalSession.spawn(emit=collector, shell="definitely-not-a-shell-xyz")


def test_default_cwd_is_the_home_directory() -> None:
    assert default_cwd() == str(Path.home())
    assert default_cwd() not in {"C:\\", "/"}


def test_default_shell_matches_the_platform() -> None:
    shell = default_shell()
    assert shell is not None
    name = Path(shell).name.lower()
    if IS_WINDOWS:
        assert name in {"pwsh.exe", "powershell.exe", "cmd.exe"}
    else:
        assert name in {Path(os.environ.get("SHELL", "")).name, "bash", "sh"}


@pytest.mark.skipif(not IS_WINDOWS, reason="PowerShell argument policy is Windows only")
def test_windows_shell_args_carry_powershell_flags_only_for_powershell() -> None:
    assert shell_args("C:\\pwsh.exe", True) == ["-NoLogo"]
    assert shell_args("C:\\pwsh.exe", False) == ["-NoLogo", "-NoProfile"]
    assert shell_args("C:\\Windows\\System32\\cmd.exe", True) == []


@pytest.mark.skipif(IS_WINDOWS, reason="POSIX shell argument policy")
def test_posix_shell_args_never_carry_powershell_flags() -> None:
    assert shell_args("/bin/bash", True) == []
    assert shell_args("/bin/bash", False) == ["--norc"]
    assert shell_args("/bin/zsh", False) == ["-f"]
    assert shell_args("/bin/sh", False) == []


def test_module_imports_and_degrades_when_the_backend_is_missing() -> None:
    blocked = "winpty" if IS_WINDOWS else "pty"
    code = (
        "import sys;"
        f"sys.modules[{blocked!r}] = None;"
        "from marm_mcp_server.console.terminal.pty_session import TerminalSession, backend_status;"
        "s = backend_status();"
        "assert not s.available, s;"
        "print('REASON:' + s.reason);"
        "\ntry:\n"
        "    TerminalSession.spawn(emit=lambda e: None)\n"
        "except RuntimeError as exc:\n"
        "    print('RAISED:' + str(exc))\n"
        "else:\n"
        "    raise AssertionError('spawn should have refused')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert "REASON:" in result.stdout
    if IS_WINDOWS:
        assert "pywinpty" in result.stdout
    assert "RAISED:" in result.stdout
