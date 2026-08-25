from __future__ import annotations

import argparse
import os
from importlib import resources
from pathlib import Path

AGENTS: dict[str, str] = {
    "claude": ".claude",
    "codex": ".codex",
    "gemini": ".gemini",
    "qwen": ".qwen",
    "kiro": ".kiro",
}

SKILL_SUBPATH = Path("skills") / "marm-init" / "SKILL.md"
FALLBACK_DIR = ".agents"
_BUNDLED_SKILL = "resources/skills/marm-init/SKILL.md"


def _bundled_skill_text() -> str:
    """Return the packaged marm-init skill shipped inside the wheel."""
    return (
        resources.files("marm_mcp_server")
        .joinpath(_BUNDLED_SKILL)
        .read_text(encoding="utf-8")
    )


def _write_skill(agent_dir: Path, text: str) -> dict[str, str]:
    """Write (overwrite) the skill under one agent directory, failing open.

    Writes to a temp file and atomically replaces the target, so a failed write
    never truncates an existing skill and a symlinked target is replaced rather
    than followed. Symlinked targets are refused outright.
    """
    target = agent_dir / SKILL_SUBPATH
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            return {
                "target": str(target),
                "state": "error",
                "detail": "refusing to overwrite a symlinked skill file",
            }
        existed = target.exists()
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        return {"target": str(target), "state": "error", "detail": str(exc)}
    return {"target": str(target), "state": "refreshed" if existed else "installed"}


def _selected_globals(args: argparse.Namespace) -> list[str]:
    return [name for name in AGENTS if getattr(args, f"global_{name}", False)]


def install_skill(args: argparse.Namespace) -> int:
    """Install the skill globally (per --g-* flags) or into the current project."""
    text = _bundled_skill_text()
    selected = _selected_globals(args)

    if selected:
        home = Path.home()
        results = [_write_skill(home / AGENTS[name], text) for name in selected]
        mode = "global"
    else:
        cwd = Path.cwd()
        found = [name for name in AGENTS if (cwd / AGENTS[name]).is_dir()]
        if found:
            results = [_write_skill(cwd / AGENTS[name], text) for name in found]
        else:
            results = [_write_skill(cwd / FALLBACK_DIR, text)]
        mode = "project"

    return _report(results, mode)


def _report(results: list[dict[str, str]], mode: str) -> int:
    written = 0
    for result in results:
        if result["state"] == "error":
            print(f"[skip] {result['target']}: {result['detail']}")
            continue
        written += 1
        print(f"[{result['state']}] {result['target']}")

    if not written:
        print("No skill files were installed.")
        return 1

    print(
        f"\nInstalled the MARM skill into {written} location(s) ({mode} mode).\n"
        "Open your agent and invoke the MARM skill to finish setup."
    )
    return 0
