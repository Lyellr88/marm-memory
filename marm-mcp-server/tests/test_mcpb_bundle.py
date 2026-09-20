"""Contract checks for the local MARM MCPB build source."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build-mcpb.py"


def _builder():
    spec = importlib.util.spec_from_file_location("build_mcpb", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcpb_manifest_tracks_the_shipped_stdio_tool_contract():
    builder = _builder()
    manifest = builder._manifest(builder._version())
    registry = json.loads(
        (REPO_ROOT / "marm-mcp-server" / "server.json").read_text(encoding="utf-8")
    )

    assert manifest["version"] == registry["version"]
    assert manifest["tools"] == registry["tools"]
    assert manifest["server"]["type"] == "uv"
    assert manifest["server"]["entry_point"] == "marm_mcpb_entry.py"
    assert "--locked" in manifest["server"]["mcp_config"]["args"]


def test_mcpb_stage_and_archive_have_the_locked_runtime_contract(tmp_path, monkeypatch):
    builder = _builder()
    monkeypatch.setattr(builder, "OUTPUT_ROOT", tmp_path)
    stage = builder._stage(builder._version(), require_model=False)
    builder._validate_stage(stage)

    artifact = tmp_path / "marm-memory.mcpb"
    with zipfile.ZipFile(artifact, "w") as archive:
        for path in stage.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(stage))
    builder._validate_archive(artifact)

    staged_project = (stage / "pyproject.toml").read_text(encoding="utf-8")
    locked_project = (REPO_ROOT / "packaging" / "mcpb" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert staged_project == locked_project
    assert (stage / "uv.lock").read_bytes() == (
        REPO_ROOT / "packaging" / "mcpb" / "uv.lock"
    ).read_bytes()


@pytest.mark.slow_stdio
@pytest.mark.skipif(
    shutil.which("uv") is None,
    reason="the MCPB runtime smoke requires the external UV executable",
)
def test_mcpb_entry_starts_and_lists_the_shipped_tools(tmp_path, monkeypatch):
    builder = _builder()
    monkeypatch.setattr(builder, "OUTPUT_ROOT", tmp_path / "bundle")
    stage = builder._stage(builder._version(), require_model=False)
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    mcp_config = manifest["server"]["mcp_config"]
    command = [
        part.replace("${__dirname}", str(stage))
        for part in [mcp_config["command"], *mcp_config["args"]]
    ]
    client_root = tmp_path / "client-project"
    client_root.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "MARM_DB_PATH": str(tmp_path / "memory.db"),
            "MARM_ANALYTICS_DB_PATH": str(tmp_path / "analytics.db"),
            "MARM_SKIP_DOC_LOAD": "1",
        }
    )
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcpb-test", "version": "0.1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    # stdin stays OPEN until the replies are in. `subprocess.run(input=...)`
    # closes it the moment the three messages are written, which is the
    # shutdown signal for an MCP stdio server -- and `tools/list` cannot answer
    # until the graph child has spawned and reported its own tools, about two
    # seconds. The reply and the teardown then raced, and the teardown won
    # roughly one run in five: `initialize` answered, `tools/list` missing,
    # exit status 0. A real client holds stdin open, so the race belonged to
    # the harness rather than to anything this test means to assert.
    proc = subprocess.Popen(
        command,
        cwd=client_root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdin is not None and proc.stdout is not None
    # Drained on a thread: the server logs startup and the graph handshake to
    # stderr, and a full pipe there would block it forever while this side
    # waits on stdout.
    errors: list[str] = []
    drain = threading.Thread(
        target=lambda: errors.extend(proc.stderr or []), daemon=True
    )
    drain.start()
    watchdog = threading.Timer(180, proc.kill)
    watchdog.start()
    responses: dict[int, dict] = {}
    try:
        proc.stdin.write("".join(json.dumps(message) + "\n" for message in messages))
        proc.stdin.flush()
        for line in proc.stdout:  # ends on EOF, or when the watchdog kills it
            try:
                response = json.loads(line)
            except ValueError:
                continue  # a stray log line on stdout is not a protocol error
            if "id" in response:
                responses[response["id"]] = response
            if 2 in responses:
                break
    finally:
        watchdog.cancel()
        proc.stdin.close()
        proc.wait(timeout=60)
        drain.join(timeout=10)
    stderr = "".join(errors)
    assert proc.returncode == 0, stderr[:500]
    assert "serverInfo" in responses[1]["result"]
    tool_names = {tool["name"] for tool in responses[2]["result"]["tools"]}
    assert tool_names == {
        tool["name"] for tool in builder._manifest(builder._version())["tools"]
    }
