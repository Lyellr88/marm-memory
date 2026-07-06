"""Subprocess client for the codebase-memory-mcp static binary.

Speaks newline-delimited JSON-RPC 2.0 over the child's stdio, per the verified
protocol in docs/current/graph-index/graph/protocol-proof.md:

  - framing      : write compact JSON + "\n"; read one line, strip "\r\n", parse
  - handshake    : initialize -> capture serverInfo.version -> notifications/initialized
  - envelope     : result.content[] items carry the real payload (JSON-or-string) in
                   .text; scan for the first JSON-parseable item, don't assume index 0
                   (an update notice can be prepended, see mcp.c:5298-5302); errors are
                   signalled by result.isError == true, NOT a JSON-RPC error
  - serialization: one stdin pipe -> a single lock guards each write+read round-trip
  - isolation    : stderr is drained on a background thread; child crash/EOF is
                   detected and the process transparently respawned on the next call

The client is synchronous and thread-safe. Async callers invoke it through
asyncio.to_thread (matching marm-mcp-server's idiom), so the event loop never
blocks on subprocess IO.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

_EOF = object()  # sentinel pushed by the reader thread on child EOF


class CbmError(Exception):
    """Transport/protocol failure (spawn, timeout, EOF, malformed response)."""


class CbmTimeoutError(CbmError):
    """The child didn't respond within the call timeout.

    Unlike EOF/crash, the child may still be alive and working (e.g. a long
    index run) — this must NOT trigger a kill+retry, which would destroy
    in-flight work and force a blind restart.
    """


class CbmToolError(Exception):
    """A tool call returned result.isError == true.

    `payload` is the parsed content (a dict when the child returned JSON, else
    the raw string). `hint` surfaces the child's own remediation hint if present.
    """

    def __init__(self, message: str, payload: Any = None):
        super().__init__(message)
        self.payload = payload
        self.hint = payload.get("hint") if isinstance(payload, dict) else None


class CbmClient:
    """Manages one long-lived codebase-memory-mcp child process."""

    def __init__(
        self,
        command: list[str],
        cwd: Optional[str] = None,
        startup_timeout: float = 60.0,
        call_timeout: float = 300.0,
        protocol_version: str = "2025-06-18",
        client_name: str = "marm-graph",
        client_version: str = "0.1.0",
    ):
        self._command = command
        self._cwd = cwd
        self._startup_timeout = startup_timeout
        self._call_timeout = call_timeout
        self._protocol_version = protocol_version
        self._client_name = client_name
        self._client_version = client_version

        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._out_q: "queue.Queue" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self._stderr_reader: Optional[threading.Thread] = None
        self._next_id = 0

        # Populated at handshake; the true schema-contract version (binary's, not pip's).
        self.server_version: Optional[str] = None
        self.server_name: Optional[str] = None

    # ── process lifecycle ───────────────────────────────────────────

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _spawn(self) -> None:
        logger.info("cbm.spawn", command=self._command, cwd=self._cwd)
        try:
            self._proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self._cwd,
                bufsize=0,
            )
        except (OSError, ValueError) as e:
            raise CbmError(f"failed to spawn codebase-memory-mcp: {e}") from e

        # Bind the reader thread to THIS queue instance. If the child is later
        # killed and respawned, the dying old reader must not push its EOF
        # sentinel into the new queue (which would poison the fresh handshake).
        self._out_q = queue.Queue()
        self._reader = threading.Thread(
            target=self._read_stdout, args=(self._proc.stdout, self._out_q), daemon=True
        )
        self._reader.start()
        self._stderr_reader = threading.Thread(
            target=self._drain_stderr, args=(self._proc.stderr,), daemon=True
        )
        self._stderr_reader.start()

        self._handshake()

    def _read_stdout(self, pipe, q: "queue.Queue") -> None:
        """Feed each response line into `q`; push _EOF when the pipe closes.

        `q` is passed in (not read from self) so a respawn's new queue is never
        touched by a previous child's dying reader thread.
        """
        try:
            for raw in iter(pipe.readline, b""):
                q.put(raw)
        except (ValueError, OSError):
            pass
        finally:
            q.put(_EOF)

    def _drain_stderr(self, pipe) -> None:
        """Continuously drain stderr so a full pipe buffer can't deadlock the child.

        The binary logs operational lines here (e.g. mem.init); route to debug.
        """
        try:
            for raw in iter(pipe.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line == "The system cannot find the path specified.":
                    continue
                if line:
                    logger.debug("cbm.stderr", line=line)
        except (ValueError, OSError):
            pass

    def _handshake(self) -> None:
        init_result = self._send_recv(
            "initialize",
            {
                "protocolVersion": self._protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": self._client_name,
                    "version": self._client_version,
                },
            },
            timeout=self._startup_timeout,
        )
        info = (init_result or {}).get("serverInfo", {})
        self.server_version = info.get("version")
        self.server_name = info.get("name")
        logger.info(
            "cbm.handshake",
            server_name=self.server_name,
            server_version=self.server_version,
            protocol=init_result.get("protocolVersion") if init_result else None,
        )
        # notifications/initialized — no id, no response expected.
        self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def start(self) -> None:
        """Spawn + handshake if not already running. Idempotent."""
        with self._lock:
            if not self._alive():
                self._spawn()

    def close(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    # ── framing ─────────────────────────────────────────────────────

    def _write(self, obj: dict) -> None:
        line = json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise CbmError(f"write to child failed: {e}") from e

    def _read_response(self, expect_id: int, timeout: float) -> dict:
        """Read lines until the response with `expect_id` arrives.

        Blank keepalive lines are skipped; unmatched ids (shouldn't occur under
        serialized calls) are skipped defensively. _EOF or timeout -> CbmError.
        """
        import time as _time

        deadline = _time.monotonic() + timeout
        while True:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                raise CbmTimeoutError(f"timeout waiting for response id={expect_id}")
            try:
                raw = self._out_q.get(timeout=remaining)
            except queue.Empty as err:
                raise CbmTimeoutError(
                    f"timeout waiting for response id={expect_id}"
                ) from err
            if raw is _EOF:
                raise CbmError("child process closed stdout (EOF)")
            text = raw.decode("utf-8", "replace").strip("\r\n").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("cbm.unparseable_line", line=text[:200])
                continue
            if msg.get("id") != expect_id:
                logger.warning("cbm.id_mismatch", got=msg.get("id"), expected=expect_id)
                continue
            if "error" in msg:
                err = msg["error"]
                raise CbmError(f"JSON-RPC error: {err}")
            return msg.get("result", {})

    def _send_recv(self, method: str, params: dict, timeout: float) -> dict:
        """One serialized request/response round-trip. Assumes lock held OR called
        during handshake (single-threaded spawn path)."""
        self._next_id += 1
        req_id = self._next_id
        self._write(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        return self._read_response(req_id, timeout)

    # ── public API ──────────────────────────────────────────────────

    def call_tool(
        self, name: str, arguments: dict, timeout: Optional[float] = None
    ) -> Any:
        """Invoke an upstream tool. Returns the parsed payload (dict or str).

        Raises CbmToolError when the child sets result.isError == true, and
        CbmError on transport failure. Transparently respawns a dead child once.
        """
        timeout = timeout if timeout is not None else self._call_timeout
        with self._lock:
            result = self._call_tool_locked(name, arguments, timeout)
        return result

    def _call_tool_locked(self, name: str, arguments: dict, timeout: float) -> Any:
        if not self._alive():
            self._spawn()
        try:
            result = self._send_recv(
                "tools/call", {"name": name, "arguments": arguments}, timeout
            )
        except CbmTimeoutError:
            # Don't kill: the child may still be working. Surface as-is.
            raise
        except CbmError:
            # Child likely died mid-call: respawn once and retry.
            logger.warning("cbm.call_failed_retry", tool=name)
            self._force_respawn()
            result = self._send_recv(
                "tools/call", {"name": name, "arguments": arguments}, timeout
            )
        return self._unwrap(name, result)

    def _force_respawn(self) -> None:
        proc = self._proc
        self._proc = None
        if proc and proc.poll() is None:
            proc.kill()
        self._spawn()

    @staticmethod
    def _unwrap(tool: str, result: dict) -> Any:
        """Decode the MCP tools/call envelope -> payload, honouring isError.

        result.content[N].text is the payload as a JSON string OR plain string.
        Upstream's one-shot update-check notice (mcp.c:5298-5302) is prepended
        as a *non-JSON* text item ahead of the real payload, so content[0] is
        not reliably the payload — scan for the first item that parses as
        JSON, falling back to the last item's raw text.
        """
        content = result.get("content") if isinstance(result, dict) else None
        texts = (
            [c.get("text", "") for c in content if isinstance(c, dict)]
            if isinstance(content, list)
            else []
        )

        payload: Any = texts[-1] if texts else ""
        for candidate in texts:
            try:
                payload = json.loads(candidate)
                break
            except (json.JSONDecodeError, TypeError):
                continue

        if result.get("isError"):
            message = (
                payload.get("error") if isinstance(payload, dict) else str(payload)
            )
            raise CbmToolError(f"{tool}: {message}", payload=payload)
        return payload

    def list_tools(self, timeout: Optional[float] = None) -> list[dict]:
        """Return the child's tools/list (for schema-drift verification)."""
        timeout = timeout if timeout is not None else self._call_timeout
        with self._lock:
            if not self._alive():
                self._spawn()
            result = self._send_recv("tools/list", {}, timeout)
        return result.get("tools", [])
