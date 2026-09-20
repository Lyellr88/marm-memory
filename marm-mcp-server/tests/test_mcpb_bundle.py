"""Contract checks for the local MARM MCPB build source."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
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
    result = subprocess.run(
        command,
        cwd=client_root,
        env=env,
        input="".join(json.dumps(message) + "\n" for message in messages),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[:500]
    responses = {
        response["id"]: response
        for line in result.stdout.splitlines()
        if "id" in (response := json.loads(line))
    }
    assert "serverInfo" in responses[1]["result"]
    tool_names = {tool["name"] for tool in responses[2]["result"]["tools"]}
    assert tool_names == {
        tool["name"] for tool in builder._manifest(builder._version())["tools"]
    }
