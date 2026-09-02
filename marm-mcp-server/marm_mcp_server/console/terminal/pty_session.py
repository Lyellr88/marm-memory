"""Cross-platform PTY backend and session threads for the MARM Console terminal plugin."""

from __future__ import annotations

import codecs
import os
import queue
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import Kill, PtyCommand, Resize, Write

READ_SIZE = 8192
DEFAULT_COLS = 80
DEFAULT_ROWS = 24
SCROLLBACK_BUFFER_LIMIT = 200_000
_WINDOWS_SHELLS = ("pwsh", "powershell.exe", "cmd.exe")
_POSIX_SHELLS = ("bash", "sh")


@dataclass(frozen=True)
class BackendStatus:
    available: bool
    reason: str
    backend: str
    shell: str | None


def in_container() -> bool:
    """A shell inside the container is never the host shell the user meant to reach."""
    if os.environ.get("MARM_IN_DOCKER") or os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(
        marker in cgroup for marker in ("docker", "containerd", "kubepods", "lxc")
    )


def default_shell() -> str | None:
    if os.name == "nt":
        candidates: tuple[str | None, ...] = _WINDOWS_SHELLS
    else:
        candidates = (os.environ.get("SHELL"), *_POSIX_SHELLS)
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def default_cwd() -> str:
    home = Path.home()
    if home.is_dir():
        return str(home)
    return str(Path.cwd())


def shell_args(shell: str, use_profile: bool) -> list[str]:
    name = Path(shell).name.lower()
    if os.name == "nt":
        if name in {"pwsh", "pwsh.exe", "powershell", "powershell.exe"}:
            args = ["-NoLogo"]
            if not use_profile:
                args.append("-NoProfile")
            return args
        return []
    if use_profile:
        return []
    if name.startswith("bash"):
        return ["--norc"]
    if name.startswith("zsh"):
        return ["-f"]
    return []


def backend_status() -> BackendStatus:
    """Report whether a PTY can be opened here without importing the backend eagerly."""
    if in_container():
        return BackendStatus(
            False,
            "Terminal is unavailable inside a container. A container shell is not the host shell.",
            "none",
            None,
        )
    backend = "conpty" if os.name == "nt" else "posix-pty"
    if os.name == "nt":
        try:
            import winpty  # noqa: F401
        except Exception as exc:
            return BackendStatus(
                False,
                f"Windows terminal support needs the pywinpty package on Windows 10 1809+: {exc}",
                backend,
                None,
            )
    else:
        try:
            import pty  # noqa: F401
            import termios  # noqa: F401
        except Exception as exc:
            return BackendStatus(
                False,
                f"This platform has no usable PTY module: {exc}",
                backend,
                None,
            )
    shell = default_shell()
    if shell is None:
        return BackendStatus(False, "No usable shell was found on PATH.", backend, None)
    return BackendStatus(True, "", backend, shell)


class PosixPty:
    def __init__(
        self, argv: list[str], cwd: str, env: dict[str, str], cols: int, rows: int
    ) -> None:
        import pty

        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._closed = False
        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(cwd)
                os.execvpe(argv[0], argv, env)
            except BaseException:
                os._exit(127)
        self._pid = pid
        self._fd = fd
        self.resize(cols, rows)

    def read(self) -> str:
        try:
            chunk = os.read(self._fd, READ_SIZE)
        except OSError:
            return ""
        if not chunk:
            return ""
        return self._decoder.decode(chunk)

    def write(self, data: str) -> None:
        payload = data.encode("utf-8")
        while payload:
            payload = payload[os.write(self._fd, payload) :]

    def resize(self, cols: int, rows: int) -> None:
        import fcntl
        import struct
        import termios

        fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def kill(self) -> None:
        import signal

        try:
            os.killpg(os.getpgid(self._pid), signal.SIGKILL)
        except OSError:
            try:
                os.kill(self._pid, signal.SIGKILL)
            except OSError:
                pass

    def wait(self) -> int | None:
        code: int | None
        try:
            _, status = os.waitpid(self._pid, 0)
        except ChildProcessError:
            code = None
        else:
            if os.WIFEXITED(status):
                code = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                code = -os.WTERMSIG(status)
            else:
                code = None
        return code

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self._fd)
        except OSError:
            pass


class WinPty:
    def __init__(
        self, argv: list[str], cwd: str, env: dict[str, str], cols: int, rows: int
    ) -> None:
        from winpty import PtyProcess

        self._proc: Any = PtyProcess.spawn(
            argv, cwd=cwd, env=env, dimensions=(rows, cols)
        )

    def read(self) -> str:
        try:
            return str(self._proc.read(READ_SIZE))
        except (EOFError, OSError):
            return ""

    def write(self, data: str) -> None:
        self._proc.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self._proc.setwinsize(rows, cols)

    def kill(self) -> None:
        try:
            self._proc.terminate(force=True)
        except Exception:
            pass

    def wait(self) -> int | None:
        code = self._proc.wait()
        return None if code is None else int(code)

    def close(self) -> None:
        try:
            self._proc.close()
        except Exception:
            pass


class TerminalSession:
    """One PTY, one reader thread, one command thread."""

    def __init__(
        self,
        *,
        shell: str,
        cwd: str,
        emit: Callable[[dict], None],
        cols: int = DEFAULT_COLS,
        rows: int = DEFAULT_ROWS,
        use_profile: bool = True,
        on_start: Callable[[TerminalSession], None] | None = None,
    ) -> None:
        self.session_id = str(uuid.uuid4())
        self.shell = shell
        self.cwd = cwd
        self.exit_code: int | None = None
        self._emit = emit
        self._emit_lock = threading.Lock()
        self._buffer = ""
        self._buffer_lock = threading.Lock()
        self._commands: queue.Queue[PtyCommand] = queue.Queue()
        self._finished = threading.Event()

        env = os.environ.copy()
        if os.name != "nt":
            env.setdefault("TERM", "xterm-256color")
        argv = [shell, *shell_args(shell, use_profile)]
        backend = WinPty if os.name == "nt" else PosixPty
        self._pty: Any = backend(argv, cwd, env, cols, rows)

        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"marm-pty-read-{self.session_id[:8]}",
            daemon=True,
        )
        self._commander = threading.Thread(
            target=self._command_loop,
            name=f"marm-pty-cmd-{self.session_id[:8]}",
            daemon=True,
        )
        # Registration must precede the first event or a client can act on an unknown id.
        if on_start is not None:
            on_start(self)
        self._reader.start()
        self._commander.start()
        self._safe_emit(
            {"type": "status", "sessionId": self.session_id, "state": "running"}
        )

    @classmethod
    def spawn(
        cls,
        *,
        emit: Callable[[dict], None],
        shell: str | None = None,
        cwd: str | None = None,
        cols: int = DEFAULT_COLS,
        rows: int = DEFAULT_ROWS,
        use_profile: bool = True,
        on_start: Callable[[TerminalSession], None] | None = None,
    ) -> TerminalSession:
        status = backend_status()
        if not status.available:
            raise RuntimeError(status.reason)
        resolved_shell = shutil.which(shell) if shell else status.shell
        if not resolved_shell:
            raise RuntimeError(f"Shell not found: {shell}")
        resolved_cwd = cwd or default_cwd()
        if not Path(resolved_cwd).is_dir():
            raise RuntimeError(f"Working directory does not exist: {resolved_cwd}")
        return cls(
            shell=resolved_shell,
            cwd=resolved_cwd,
            emit=emit,
            cols=max(1, int(cols)),
            rows=max(1, int(rows)),
            use_profile=use_profile,
            on_start=on_start,
        )

    def send(self, command: PtyCommand) -> None:
        if self._finished.is_set():
            return
        self._commands.put(command)

    def write(self, data: str) -> None:
        self.send(Write(data))

    def resize(self, cols: int, rows: int) -> None:
        self.send(Resize(max(1, int(cols)), max(1, int(rows))))

    def kill(self) -> None:
        self.send(Kill())

    def finished(self) -> bool:
        return self._finished.is_set()

    def wait_closed(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def attach(self, emit: Callable[[dict], None]) -> None:
        """Point this session's output at a new client and replay scrollback.

        The reader and command threads are untouched -- only the emit target
        changes, so a client reconnecting after a page refresh sees the shell
        exactly as it left it."""
        with self._emit_lock:
            self._emit = emit
        with self._buffer_lock:
            snapshot = self._buffer
        if snapshot:
            self._safe_emit(
                {"type": "data", "sessionId": self.session_id, "data": snapshot}
            )

    def detach(self) -> None:
        """Stop emitting to the now-disconnected client. The shell keeps running."""
        with self._emit_lock:
            self._emit = lambda _event: None

    def _safe_emit(self, event: dict) -> None:
        with self._emit_lock:
            emit = self._emit
        try:
            emit(event)
        except Exception:
            pass

    def _buffer_append(self, chunk: str) -> None:
        with self._buffer_lock:
            self._buffer += chunk
            if len(self._buffer) > SCROLLBACK_BUFFER_LIMIT:
                self._buffer = self._buffer[-SCROLLBACK_BUFFER_LIMIT:]

    def _read_loop(self) -> None:
        while True:
            chunk = self._pty.read()
            if not chunk:
                break
            self._buffer_append(chunk)
            self._safe_emit(
                {"type": "data", "sessionId": self.session_id, "data": chunk}
            )
        self.send(Kill())

    def _command_loop(self) -> None:
        # Reads block, so commands drain on their own thread or input waits on output.
        while True:
            command = self._commands.get()
            if isinstance(command, Write):
                try:
                    self._pty.write(command.data)
                except OSError:
                    break
            elif isinstance(command, Resize):
                try:
                    self._pty.resize(command.cols, command.rows)
                except OSError:
                    pass
            else:
                self._pty.kill()
                break
        try:
            code = self._pty.wait()
        except Exception:
            code = -1
        self._finish(code)

    def _finish(self, code: int | None) -> None:
        if self._finished.is_set():
            return
        self.exit_code = code
        self._finished.set()
        self._pty.close()
        self._safe_emit({"type": "exit", "sessionId": self.session_id, "code": code})
