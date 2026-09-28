"""The calibration script shows the answers it asks an operator to judge."""

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "calibrate-analyst.py"


def _script():
    spec = importlib.util.spec_from_file_location("calibrate_analyst", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(monkeypatch, tmp_path, results):
    script = _script()
    questions = tmp_path / "q.txt"
    questions.write_text("\n".join(results), encoding="utf-8")
    monkeypatch.setattr(script, "ask", lambda _url, _p, q, _t: results[q])
    monkeypatch.setattr(
        sys, "argv", ["calibrate", "--project", "p", "--questions", str(questions)]
    )
    # Captured in the script's own namespace: once another test imports
    # server_stdio, the builtin print writes to stderr for the whole process.
    printed: list[str] = []
    monkeypatch.setattr(
        script,
        "print",
        lambda *a, **_k: printed.append(" ".join(map(str, a))),
        raising=False,
    )
    script.main()
    return [json.loads(line) for line in printed[:-1]]


def test_an_answer_to_judge_is_printed_without_an_output_file(monkeypatch, tmp_path):
    rows = _run(
        monkeypatch,
        tmp_path,
        {
            "why": {"answer": "It claims first [S1].", "answer_status": "unverified"},
            "how": {
                "answer": "It writes [S1].",
                "answer_verification": {"state": "verified"},
            },
        },
    )
    assert rows[0]["answer"] == "It claims first [S1]."
    assert "answer" not in rows[1], "a verified answer needs no judging"
