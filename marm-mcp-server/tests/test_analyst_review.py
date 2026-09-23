import asyncio
import json

import pytest

from marm_mcp_server.services.analyst import review
from marm_mcp_server.services.analyst.brief import Brief
from marm_mcp_server.services.analyst.packet import build_packet
from marm_mcp_server.services.analyst.verify import verify
from marm_mcp_server.services.code_context.compose import Context, Symbol


@pytest.fixture()
def staged_memory(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    assert load_isolated_server(monkeypatch, tmp_path) is not None
    from marm_mcp_server.core.memory import memory as live

    return live


def _brief(answer):
    packet = build_packet(
        Context(
            project={"name": "demo"},
            task="how",
            symbols=[
                Symbol(
                    "pkg.apply",
                    "apply",
                    "Function",
                    "pkg/a.py",
                    1,
                    9,
                    source="def apply():\n    claim()\n",
                ),
                Symbol("pkg.claim", "claim", "Function", "pkg/a.py", 11, 15),
            ],
            graph_edges=[("pkg.apply", "pkg.claim", 1.0)],
        )
    )
    b = Brief(packet=packet, answer=answer)
    b.verification = verify(answer, packet)
    b.status = {"verified": "ok", "uncertain": "unverified", "rejected": "rejected"}[
        b.verification.state
    ]
    return b


def _model(monkeypatch, reply):
    monkeypatch.setattr(review.local_llm, "complete", lambda *a, **k: reply)


def _stage(memory, answer):
    return asyncio.run(
        review.stage_conclusions(
            memory, _brief(answer), "how", session_name="analyst:demo", project="demo"
        )
    )


def test_parse_conclusions_takes_at_most_three_bullets():
    text = "- a [S1]\n- b [S1]\nnoise\n- c [S2]\n- d [S2]"
    assert review.parse_conclusions(text) == ["a [S1]", "b [S1]", "c [S2]"]


def test_only_verified_conclusions_are_staged(staged_memory, monkeypatch):
    _model(
        monkeypatch,
        "- apply calls claim before writing [S1] [S2]\n- it also retries forever",
    )
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert len(out["staged"]) == 1
    assert out["skipped"][0]["reason"].startswith("not verified")
    with staged_memory.get_connection() as conn:
        origin, mode, ver = conn.execute(
            "SELECT origin, mode, verification FROM distill_staging"
        ).fetchone()
    assert (origin, mode) == ("analyst", "analyst")
    assert json.loads(ver)["state"] == "verified"


def test_rejected_brief_stages_nothing(staged_memory, monkeypatch):
    _model(monkeypatch, "- x [S1]")
    out = _stage(staged_memory, "apply calls [persist_all].")
    assert out["staged"] == []
    assert out["skipped"][0]["reason"] == "brief rejected"


def test_abstention_stages_nothing(staged_memory, monkeypatch):
    _model(monkeypatch, "- The context does not show the retry policy")
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert out["staged"] == []


def test_the_same_conclusion_is_not_proposed_twice(staged_memory, monkeypatch):
    _model(monkeypatch, "- apply calls claim before writing [S1] [S2]")
    first = _stage(staged_memory, "apply calls claim [S1] [S2].")
    second = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert len(first["staged"]) == 1
    assert second["staged"] == []
    assert second["skipped"][0]["reason"] == "already proposed"


def test_staged_conclusion_applies_through_distill(staged_memory, monkeypatch):
    from marm_mcp_server.services import distill

    _model(monkeypatch, "- apply calls claim before writing [S1] [S2]")
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    applied = asyncio.run(distill.apply(staged_memory, out["staged"][0]))
    assert applied["status"] == "success"
    with staged_memory.get_connection() as conn:
        (meta,) = conn.execute(
            "SELECT metadata FROM memories WHERE id = ?", (applied["memory_id"],)
        ).fetchone()
    meta = json.loads(meta)
    assert meta["origin"] == "analyst"
    assert meta["verification"]["state"] == "verified"


def test_review_reports_origin_and_verification(staged_memory, monkeypatch):
    from marm_mcp_server.services import distill

    _model(monkeypatch, "- apply calls claim before writing [S1] [S2]")
    _stage(staged_memory, "apply calls claim [S1] [S2].")
    listed = distill.review(staged_memory, session_name="analyst:demo")
    entry = listed["pending"][0]
    assert entry["origin"] == "analyst"
    assert entry["verification"]["state"] == "verified"


# --- analyst_mode on marm_code_context ---------------------------------------


@pytest.fixture
def composed(staged_memory, monkeypatch):
    """A composition and a model; the answer and its conclusions differ."""
    from marm_mcp_server.services import code_context as cc
    from marm_mcp_server.services import local_llm

    async def build(_backend, _task, **_kw):
        return Context(
            project={"name": "graph-id", "root_path": "/x/demo"},
            task="how",
            symbols=[
                Symbol(
                    "pkg.apply",
                    "apply",
                    "Function",
                    "pkg/a.py",
                    1,
                    9,
                    source="def apply():\n    claim()\n",
                ),
                Symbol("pkg.claim", "claim", "Function", "pkg/a.py", 11, 15),
            ],
            graph_edges=[("pkg.apply", "pkg.claim", 1.0)],
        )

    def complete(system, *_a, **_k):
        if system == review.CONCLUSIONS_SYSTEM:
            return "- apply calls claim before writing [S1] [S2]"
        return "apply calls claim [S1] [S2]."

    monkeypatch.setattr(cc, "build", build)
    monkeypatch.setattr(cc, "LocalBackend", lambda: object())
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "stub-model")
    monkeypatch.setattr(local_llm, "endpoint_source", lambda: "environment")
    monkeypatch.setattr(local_llm, "complete", complete)
    return cc


def _pending(memory):
    with memory.get_connection() as conn:
        return conn.execute(
            "SELECT session_name, project FROM distill_staging"
        ).fetchall()


def test_manual_review_stages_verified_conclusions(composed, staged_memory):
    out = asyncio.run(
        composed.build_code_context(
            task="how", answer=True, analyst_mode="manual_review"
        )
    )
    assert out["answer_status"] == "ok"
    assert out["analyst"]["mode"] == "manual_review"
    assert len(out["analyst"]["staged"]) == 1
    assert out["analyst"]["decisions"] == []
    assert _pending(staged_memory) == [("analyst:demo", "demo")]


def test_read_only_stages_nothing(composed, staged_memory):
    out = asyncio.run(composed.build_code_context(task="how", answer=True))
    assert "analyst" not in out
    assert _pending(staged_memory) == []


def test_review_without_an_answer_says_why_and_stages_nothing(composed, staged_memory):
    out = asyncio.run(
        composed.build_code_context(task="how", analyst_mode="manual_review")
    )
    assert out["analyst"]["staged"] == []
    assert "answer" in out["analyst"]["skipped"][0]["reason"]
    assert _pending(staged_memory) == []


def test_no_model_is_not_reported_as_a_rejection(composed, staged_memory, monkeypatch):
    """Nothing was judged, so nothing was rejected: `rejected` means the answer
    contradicted its evidence."""
    from marm_mcp_server.services import local_llm

    monkeypatch.setattr(local_llm, "available", lambda *a, **k: None)
    out = asyncio.run(
        composed.build_code_context(
            task="how", answer=True, analyst_mode="manual_review"
        )
    )
    assert out["analyst"]["staged"] == []
    assert out["analyst"]["skipped"][0]["reason"] == "no answer"
