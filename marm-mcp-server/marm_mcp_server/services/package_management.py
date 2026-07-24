"""Installer detection and registry checks for the product CLI."""

from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PACKAGE_NAME = "marm-mcp-server"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"


@dataclass(frozen=True)
class Installation:
    version: str
    installer: str
    editable: bool
    source_path: Path | None = None


def inspect_installation() -> Installation:
    """Detect the active distribution without probing or modifying the environment."""
    try:
        distribution = importlib.metadata.distribution(PACKAGE_NAME)
        version = distribution.version
        direct_url = distribution.read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "marm-mcp-server is not installed in this interpreter."
        ) from exc

    editable = False
    source_path: Path | None = None
    if direct_url:
        try:
            payload = json.loads(direct_url)
            editable = bool(payload.get("dir_info", {}).get("editable"))
            source_url = payload.get("url")
            if (
                editable
                and isinstance(source_url, str)
                and source_url.startswith("file:")
            ):
                source = urllib.parse.unquote(urllib.parse.urlparse(source_url).path)
                if (
                    os.name == "nt"
                    and len(source) > 2
                    and source[0] == "/"
                    and source[2] == ":"
                ):
                    source = source[1:]
                source_path = Path(source)
        except (TypeError, ValueError):
            pass
    if os.environ.get("PIPX_HOME") or "pipx" in str(Path(sys.executable)).lower():
        installer = "pipx"
    else:
        installer = "pip"
    return Installation(
        version=version,
        installer=installer,
        editable=editable,
        source_path=source_path,
    )


def check_latest_release(timeout: float = 5.0) -> dict[str, str]:
    """Fetch the latest stable package version without changing the installation."""
    request = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(
            "Could not contact PyPI. Check your network connection and retry `marm-memory upgrade --check`."
        ) from exc
    latest = payload.get("info", {}).get("version")
    if not isinstance(latest, str) or not latest:
        raise RuntimeError("PyPI returned an invalid marm-mcp-server release response.")
    installation = inspect_installation()
    return {
        "installed_version": installation.version,
        "latest_version": latest,
        "state": "current" if installation.version == latest else "update_available",
        "installer": installation.installer,
        "editable": str(installation.editable).lower(),
    }


def manual_upgrade_command(
    installation: Installation, version: str | None = None
) -> str:
    """Return the safest user-visible command for this installation type."""
    target = PACKAGE_NAME if version is None else f"{PACKAGE_NAME}=={version}"
    if installation.editable:
        if installation.source_path:
            return f'"{sys.executable}" -m pip install -e "{installation.source_path}"'
        return "Refresh the editable source environment with its package manager."
    if installation.installer == "pipx":
        return f"pipx upgrade {PACKAGE_NAME}"
    return f'"{sys.executable}" -m pip install --upgrade "{target}"'


def manual_uninstall_command(installation: Installation) -> str:
    """Return a non-destructive command the user can run after this process exits."""
    if installation.editable:
        return "Remove the editable installation from its source environment with its package manager."
    if installation.installer == "pipx":
        return f"pipx uninstall {PACKAGE_NAME}"
    return f'"{sys.executable}" -m pip uninstall {PACKAGE_NAME}'


def run_upgrade(version: str | None = None) -> int:
    """Run pip through the interpreter that owns the active installation."""
    target = PACKAGE_NAME if version is None else f"{PACKAGE_NAME}=={version}"
    return subprocess.call(
        [sys.executable, "-m", "pip", "install", "--upgrade", target]
    )


def run_uninstall() -> int:
    """Remove the distribution through the active interpreter's pip."""
    return subprocess.call(
        [sys.executable, "-m", "pip", "uninstall", "--yes", PACKAGE_NAME]
    )
