from __future__ import annotations

import argparse
from pathlib import Path

from marm_mcp_server.services import skill_install

REPO_SKILL = Path(__file__).resolve().parents[2] / "skills" / "marm-init" / "SKILL.md"
SKILL_REL = Path("skills") / "marm-init" / "SKILL.md"


def _args(**globals_) -> argparse.Namespace:
    namespace = argparse.Namespace()
    for agent in skill_install.AGENTS:
        setattr(namespace, f"global_{agent}", globals_.get(agent, False))
    return namespace


def _read(base: Path, agent_dir: str) -> str:
    return (base / agent_dir / SKILL_REL).read_text(encoding="utf-8")


def test_bundled_skill_matches_repo_source():
    bundled = skill_install._bundled_skill_text()
    assert bundled == REPO_SKILL.read_text(encoding="utf-8")


def test_project_scan_installs_into_present_agents(tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".codex").mkdir()
    monkeypatch.chdir(tmp_path)

    code = skill_install.install_skill(_args())

    assert code == 0
    expected = skill_install._bundled_skill_text()
    assert _read(tmp_path, ".claude") == expected
    assert _read(tmp_path, ".codex") == expected
    assert not (tmp_path / ".gemini").exists()
    assert not (tmp_path / skill_install.FALLBACK_DIR).exists()


def test_project_scan_overwrites_existing_skill(tmp_path, monkeypatch):
    stale = tmp_path / ".claude" / SKILL_REL
    stale.parent.mkdir(parents=True)
    stale.write_text("stale content", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    code = skill_install.install_skill(_args())

    assert code == 0
    assert _read(tmp_path, ".claude") == skill_install._bundled_skill_text()


def test_fallback_when_no_agents_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    code = skill_install.install_skill(_args())

    assert code == 0
    fallback = tmp_path / skill_install.FALLBACK_DIR / SKILL_REL
    assert fallback.read_text(encoding="utf-8") == skill_install._bundled_skill_text()


def test_fallback_not_used_when_one_agent_present(tmp_path, monkeypatch):
    (tmp_path / ".kiro").mkdir()
    monkeypatch.chdir(tmp_path)

    skill_install.install_skill(_args())

    assert not (tmp_path / skill_install.FALLBACK_DIR).exists()
    assert _read(tmp_path, ".kiro") == skill_install._bundled_skill_text()


def test_global_flags_install_into_home_and_skip_project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".gemini").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setattr(skill_install.Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(project)

    code = skill_install.install_skill(_args(claude=True, codex=True))

    assert code == 0
    assert _read(home, ".claude") == skill_install._bundled_skill_text()
    assert _read(home, ".codex") == skill_install._bundled_skill_text()
    assert not (project / ".gemini" / SKILL_REL).exists()
    assert not (home / ".gemini").exists()


def test_fail_open_when_a_target_is_unwritable(tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".codex").mkdir()
    monkeypatch.chdir(tmp_path)

    real_write = Path.write_text

    def selective_write(self, data, *args, **kwargs):
        if ".codex" in self.parts:
            raise OSError("permission denied")
        return real_write(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", selective_write)

    code = skill_install.install_skill(_args())

    assert code == 0
    assert _read(tmp_path, ".claude") == skill_install._bundled_skill_text()


def test_exit_one_when_nothing_installs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def always_fail(self, data, *args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "write_text", always_fail)

    code = skill_install.install_skill(_args())

    assert code == 1


def test_init_parser_registers_all_global_flags():
    from marm_mcp_server.cli import _product_parser

    args = _product_parser().parse_args(["init", "--g-claude", "--g-kiro"])

    assert args.command == "init"
    assert args.global_claude is True
    assert args.global_kiro is True
    assert args.global_codex is False
