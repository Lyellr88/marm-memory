#!/usr/bin/env python3
"""Build a local MARM MCPB bundle from the release source tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import threading
import zipfile
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "marm-mcp-server"
BUNDLE_SOURCE = ROOT / "packaging" / "mcpb"
OUTPUT_ROOT = ROOT / "dist" / "mcpb"
MCPB_CLI_VERSION = "2.1.2"
REQUIRED_STAGE_FILES = (
    "manifest.json",
    "pyproject.toml",
    "uv.lock",
    "marm_mcpb_entry.py",
    "marm_mcp_server/server_stdio.py",
    "marm_graph/config/settings.py",
    "icon.png",
)


def _copy(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Required MCPB source is missing: {source}")
    if source.is_dir():
        shutil.copytree(
            source, destination, ignore=shutil.ignore_patterns("__pycache__")
        )
    else:
        shutil.copy2(source, destination)


def _project(path: Path) -> dict:
    with path.open("rb") as handle:
        project = tomllib.load(handle)["project"]
    if not isinstance(project, dict):
        raise ValueError(f"{path} project metadata must be an object")
    return project


def _version() -> str:
    project = _project(PACKAGE_ROOT / "pyproject.toml")
    version = project["version"]
    if not isinstance(version, str):
        raise ValueError("marm-mcp-server project.version must be a string")
    return version


def _assert_locked_dependencies_match() -> None:
    marm_dependencies = _project(PACKAGE_ROOT / "pyproject.toml").get("dependencies")
    bundle_dependencies = _project(BUNDLE_SOURCE / "pyproject.toml").get("dependencies")
    if marm_dependencies != bundle_dependencies:
        raise ValueError(
            "packaging/mcpb/pyproject.toml must exactly match MARM runtime dependencies"
        )
    subprocess.run(["uv", "lock", "--check"], cwd=BUNDLE_SOURCE, check=True)


def _manifest(version: str) -> dict:
    template = (BUNDLE_SOURCE / "manifest.template.json").read_text(encoding="utf-8")
    manifest = json.loads(template.replace("__MARM_VERSION__", version))
    registry = json.loads((PACKAGE_ROOT / "server.json").read_text(encoding="utf-8"))
    tools = registry.get("tools")
    if not isinstance(tools, list):
        raise ValueError("marm-mcp-server/server.json must declare a tools list")
    manifest["tools"] = tools
    return manifest


def _stage(version: str, *, require_model: bool = True) -> Path:
    stage = OUTPUT_ROOT / f"marm-memory-{version}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    manifest = _manifest(version)
    (stage / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    _copy(BUNDLE_SOURCE / "marm_mcpb_entry.py", stage / "marm_mcpb_entry.py")
    _copy(BUNDLE_SOURCE / "pyproject.toml", stage / "pyproject.toml")
    _copy(BUNDLE_SOURCE / "uv.lock", stage / "uv.lock")
    _copy(PACKAGE_ROOT / "README.md", stage / "README.md")
    _copy(ROOT / "LICENSE", stage / "LICENSE")
    _copy(ROOT / "THIRD_PARTY_NOTICES.md", stage / "THIRD_PARTY_NOTICES.md")
    _copy(ROOT / "assets" / "marm-logo.png", stage / "icon.png")
    _copy(PACKAGE_ROOT / "marm_mcp_server", stage / "marm_mcp_server")
    _copy(PACKAGE_ROOT / "marm_graph", stage / "marm_graph")

    model = stage / "marm_mcp_server" / "models" / "en_core_web_sm"
    if require_model and not model.is_dir():
        raise FileNotFoundError(
            "The bundled concept model is missing. Run "
            "python marm-mcp-server/scripts/bundle-concept-model.py first."
        )

    return stage


def _validate_stage(stage: Path) -> None:
    missing = [path for path in REQUIRED_STAGE_FILES if not (stage / path).is_file()]
    if missing:
        raise FileNotFoundError(f"MCPB staging directory is incomplete: {missing}")
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("server", {}).get("type") != "uv":
        raise ValueError("MCPB manifest must use the UV runtime")
    args = manifest.get("server", {}).get("mcp_config", {}).get("args")
    if not isinstance(args, list) or "--locked" not in args:
        raise ValueError("MCPB manifest must run UV with the staged lockfile")


def _validate_archive(artifact: Path) -> None:
    with zipfile.ZipFile(artifact) as archive:
        paths = set(archive.namelist())
        unsafe = [
            path for path in paths if path.startswith("/") or ".." in Path(path).parts
        ]
        if unsafe:
            raise ValueError(f"MCPB archive contains unsafe paths: {unsafe}")
        missing = [path for path in REQUIRED_STAGE_FILES if path not in paths]
        if missing:
            raise FileNotFoundError(f"MCPB archive is incomplete: {missing}")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("server", {}).get("entry_point") != "marm_mcpb_entry.py":
            raise ValueError("MCPB archive points at an unexpected entry point")


def _mcpb_command(stage: Path, artifact: Path) -> list[str]:
    executable = "npx.cmd" if os.name == "nt" else "npx"
    npx = shutil.which(executable)
    if npx is None:
        raise FileNotFoundError(
            f"{executable} is required to run @anthropic-ai/mcpb@{MCPB_CLI_VERSION}"
        )
    return [
        npx,
        "--yes",
        f"@anthropic-ai/mcpb@{MCPB_CLI_VERSION}",
        "pack",
        str(stage),
        str(artifact),
    ]


def _uv_stdio_smoke(stage: Path) -> None:
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    expected_tools = {tool["name"] for tool in manifest["tools"]}
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcpb-build-smoke", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    payload = "".join(json.dumps(message) + "\n" for message in messages).encode()
    with tempfile.TemporaryDirectory(prefix="marm-mcpb-smoke-") as temp_dir:
        temp_path = Path(temp_dir)
        env = os.environ.copy()
        env.update(
            {
                "MARM_DB_PATH": str(temp_path / "memory.db"),
                "MARM_ANALYTICS_DB_PATH": str(temp_path / "analytics.db"),
                "MARM_SKIP_DOC_LOAD": "1",
            }
        )
        process = subprocess.Popen(
            [
                "uv",
                "run",
                "--locked",
                "--directory",
                str(stage),
                "marm_mcpb_entry.py",
            ],
            cwd=stage,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        watchdog = threading.Timer(120, process.kill)
        responses: dict[int, dict] = {}
        try:
            watchdog.start()
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("MCPB UV stdio smoke did not create standard streams")
            process.stdin.write(payload)
            process.stdin.flush()
            while 2 not in responses:
                line = process.stdout.readline()
                if not line:
                    break
                response = json.loads(line)
                if isinstance(response.get("id"), int):
                    responses[response["id"]] = response
        finally:
            watchdog.cancel()
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=15)
        stderr = b"" if process.stderr is None else process.stderr.read()
        if process.returncode != 0:
            raise RuntimeError(
                "MCPB UV stdio smoke failed: "
                f"{stderr.decode('utf-8', errors='replace')[:500]}"
            )
    if "serverInfo" not in responses.get(1, {}).get("result", {}):
        raise RuntimeError("MCPB UV stdio smoke received no initialize response")
    actual_tools = {
        tool["name"] for tool in responses.get(2, {}).get("result", {}).get("tools", [])
    }
    if actual_tools != expected_tools:
        raise RuntimeError("MCPB UV stdio smoke tools/list did not match the manifest")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-stdio", action="store_true")
    args = parser.parse_args()
    version = _version()
    _assert_locked_dependencies_match()
    stage = _stage(version)
    _validate_stage(stage)
    artifact = OUTPUT_ROOT / f"marm-memory-{version}.mcpb"
    command = _mcpb_command(stage, artifact)
    print(f"Building {artifact.relative_to(ROOT)}")
    subprocess.run(command, cwd=ROOT, check=True)
    _validate_archive(artifact)
    if args.smoke_stdio:
        _uv_stdio_smoke(stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
