"""Optional concept extraction dependency setup for the product CLI."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from typing import Callable


def setup_plan() -> list[list[str]]:
    commands: list[list[str]] = []
    if importlib.util.find_spec("spacy") is None:
        commands.append(
            [sys.executable, "-m", "pip", "install", "marm-mcp-server[concepts]"]
        )
    if importlib.util.find_spec("en_core_web_sm") is None:
        commands.append([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
    return commands


def install_knowledge_runtime(
    *,
    confirmed: bool,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    commands = setup_plan()
    if not commands:
        return {"status": "ready", "commands": [], "restart_required": False}
    if not confirmed:
        return {
            "status": "confirmation_required",
            "commands": commands,
            "environment": sys.executable,
            "restart_required": False,
        }
    for command in commands:
        completed = runner(command, check=False)
        if completed.returncode != 0:
            return {
                "status": "error",
                "failed_command": command,
                "environment": sys.executable,
                "message": (
                    "The active Python environment could not be modified. "
                    f"Run this command manually: {' '.join(command)}"
                ),
                "restart_required": False,
            }
    return {
        "status": "installed",
        "commands": commands,
        "environment": sys.executable,
        "restart_required": True,
    }
