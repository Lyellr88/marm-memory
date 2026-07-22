import subprocess
import sys

from marm_mcp_server.services import knowledge_setup


def test_setup_requires_confirmation_and_uses_current_interpreter(monkeypatch):
    monkeypatch.setattr(
        knowledge_setup,
        "setup_plan",
        lambda: [
            [sys.executable, "-m", "pip", "install", "marm-mcp-server[concepts]"],
            [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
        ],
    )
    calls = []

    def runner(command, check):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    preview = knowledge_setup.install_knowledge_runtime(confirmed=False, runner=runner)
    installed = knowledge_setup.install_knowledge_runtime(confirmed=True, runner=runner)

    assert preview["status"] == "confirmation_required"
    assert calls == [
        (preview["commands"][0], False),
        (preview["commands"][1], False),
    ]
    assert all(command[0] == sys.executable for command, _ in calls)
    assert installed["status"] == "installed"
    assert installed["restart_required"] is True


def test_setup_failure_stops_at_failed_command(monkeypatch):
    commands = [
        [sys.executable, "-m", "pip", "install", "marm-mcp-server[concepts]"],
        [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
    ]
    monkeypatch.setattr(knowledge_setup, "setup_plan", lambda: commands)
    calls = []

    def runner(command, check):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1)

    result = knowledge_setup.install_knowledge_runtime(confirmed=True, runner=runner)

    assert result["status"] == "error"
    assert "Run this command manually" in result["message"]
    assert calls == [commands[0]]
