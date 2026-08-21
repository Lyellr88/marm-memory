import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = ROOT / "scripts" / "tui-launcher.py"


@pytest.fixture
def launcher_module():
    spec = importlib.util.spec_from_file_location("tui_launcher", LAUNCHER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_rejects_paths_outside_its_script_catalog(launcher_module):
    assert launcher_module.launch_script_in_terminal("../outside.py") is False


def test_launcher_runs_selected_script_in_windows_terminal(
    monkeypatch, launcher_module
):
    calls = []
    monkeypatch.setattr(launcher_module.sys, "platform", "win32")
    monkeypatch.setattr(
        launcher_module.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert launcher_module.launch_script_in_terminal("find-tools.py") is True

    command, kwargs = calls[0]
    assert command[:3] == ["powershell", "-NoExit", "-Command"]
    assert str(LAUNCHER_PATH.parent / "find-tools.py") in command[3]
    assert kwargs["cwd"] == ROOT


def test_launcher_runs_selected_script_in_xterm_after_gnome_fallback(
    monkeypatch, launcher_module
):
    calls = []
    monkeypatch.setattr(launcher_module.sys, "platform", "linux")
    monkeypatch.setattr(launcher_module.sys, "executable", "/tmp/python; unsafe")

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "gnome-terminal":
            raise FileNotFoundError

    monkeypatch.setattr(launcher_module.subprocess, "Popen", fake_popen)

    assert launcher_module.launch_script_in_terminal("find-tools.py") is True

    command, _kwargs = calls[-1]
    assert command[:4] == ["xterm", "-e", "bash", "-lc"]
    assert "'/tmp/python; unsafe'" in command[-1]
    assert str(LAUNCHER_PATH.parent / "find-tools.py") in command[-1]


def test_launcher_passes_macos_command_as_an_osascript_argument(
    monkeypatch, launcher_module
):
    calls = []
    monkeypatch.setattr(launcher_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        launcher_module.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert launcher_module.launch_script_in_terminal("find-tools.py") is True

    command, _kwargs = calls[0]
    assert command[0] == "osascript"
    assert "on run argv" in command[2]
    assert str(LAUNCHER_PATH.parent / "find-tools.py") in command[3]
