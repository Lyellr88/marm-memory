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


# --- Automated Guardrails ------------------------------------------------------

from marm_mcp_server.services.analyst.review import (  # noqa: E402
    guardrail_decision,
)

FACT = "We decided that apply claims the row before writing it."


def _ok(**over):
    kw = {
        "content": "apply claims the row before writing it",
        "verdict": "new",
        "evidence": "apply claims the row before writing it",
        "source_text": "... apply claims the row before writing it ...",
        "verification": None,
        "origin": "distill",
    }
    kw.update(over)
    return kw


def test_all_checks_pass(monkeypatch):
    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    d = guardrail_decision(**_ok())
    assert d.apply is True and all(d.checks.values())


@pytest.mark.parametrize(
    "over,check",
    [
        ({"verdict": "near"}, "novel"),
        ({"content": "x"}, "headline_shaped"),
        ({"content": "two lines\nare not a headline at all"}, "headline_shaped"),
        (
            {"evidence": "not in source", "content": "not in source either at all"},
            "evidence_verbatim",
        ),
        ({"content": "the api_key = abc123 is used here for auth"}, "no_secret"),
        (
            {"origin": "analyst", "verification": {"state": "uncertain", "score": 0.8}},
            "verified",
        ),
        (
            {"origin": "analyst", "verification": {"state": "verified", "score": 0.9}},
            "verified",
        ),
    ],
)
def test_each_check_blocks_alone(monkeypatch, over, check):
    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    d = guardrail_decision(**_ok(**over))
    assert d.apply is False and d.checks[check] is False
    assert check in d.reason


@pytest.mark.parametrize("value", ["", "true", "yes", "0", " 1"])
def test_operator_switch_is_exactly_1(monkeypatch, value):
    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", value)
    assert guardrail_decision(**_ok()).checks["operator_enabled"] is False


def _propose(memory, text=FACT):
    from marm_mcp_server.services import distill

    return asyncio.run(
        distill.propose(
            memory, text, session_name="s", use_llm=False, review_mode="guardrails"
        )
    )


def test_guardrails_without_operator_switch_writes_nothing(staged_memory, monkeypatch):
    monkeypatch.delenv("MARM_ANALYST_AUTO_APPLY", raising=False)
    out = _propose(staged_memory)
    assert out["review_mode"] == "guardrails"
    assert out["guardrails"], "nothing was staged, so nothing was decided"
    assert all(not d["applied"] for d in out["guardrails"])
    assert "MARM_ANALYST_AUTO_APPLY" in out["guardrails"][0]["decision"]["reason"]
    with staged_memory.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
        statuses = {r[0] for r in conn.execute("SELECT status FROM distill_staging")}
    assert statuses == {"pending"}


def test_guardrails_applies_a_verbatim_new_fact(staged_memory, monkeypatch):
    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    out = _propose(staged_memory)
    applied = [d for d in out["guardrails"] if d["applied"]]
    assert applied and applied[0]["memory_id"]
    with staged_memory.get_connection() as conn:
        (decision,) = conn.execute(
            "SELECT decision FROM distill_staging WHERE id = ?",
            (applied[0]["proposal_id"],),
        ).fetchone()
    assert json.loads(decision)["apply"] is True


def test_a_blocked_decision_is_recorded_on_the_row(staged_memory, monkeypatch):
    """The audit record exists whether or not anything was written."""
    monkeypatch.delenv("MARM_ANALYST_AUTO_APPLY", raising=False)
    out = _propose(staged_memory)
    pid = out["guardrails"][0]["proposal_id"]
    with staged_memory.get_connection() as conn:
        (decision,) = conn.execute(
            "SELECT decision FROM distill_staging WHERE id = ?", (pid,)
        ).fetchone()
    assert json.loads(decision)["apply"] is False


def test_guardrails_with_nothing_extractable_still_reports_the_mode(staged_memory):
    out = _propose(staged_memory, "ok thanks")
    assert out["review_mode"] == "guardrails"
    assert out["guardrails"] == []


def test_manual_mode_decides_nothing(staged_memory, monkeypatch):
    from marm_mcp_server.services import distill

    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    out = asyncio.run(
        distill.propose(staged_memory, FACT, session_name="s", use_llm=False)
    )
    assert out["review_mode"] == "manual"
    assert "guardrails" not in out
    with staged_memory.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0


def test_code_context_guardrails_records_decisions(
    composed, staged_memory, monkeypatch
):
    monkeypatch.delenv("MARM_ANALYST_AUTO_APPLY", raising=False)
    out = asyncio.run(
        composed.build_code_context(task="how", answer=True, analyst_mode="guardrails")
    )
    assert out["analyst"]["mode"] == "guardrails"
    decisions = out["analyst"]["decisions"]
    assert len(decisions) == 1 and decisions[0]["applied"] is False
    assert decisions[0]["decision"]["checks"]["operator_enabled"] is False


def _distill_http(monkeypatch, tmp_path, args):
    from conftest import load_isolated_server, local_client

    client = local_client(load_isolated_server(monkeypatch, tmp_path).app)
    return client.post("/marm_distill", json=args)


def _distill_stdio(monkeypatch, tmp_path, args):
    from mcp.shared.memory import create_connected_server_and_client_session
    from test_stdio_transport import _isolated_stdio

    stdio = _isolated_stdio(monkeypatch, tmp_path)

    async def run():
        async with create_connected_server_and_client_session(stdio.mcp) as c:
            return await c.call_tool("marm_distill", args)

    return json.loads(asyncio.run(run()).content[0].text)


# One transport per test: the HTTP app starts a background worker bound to its
# own event loop, and sharing a test with a STDIO session leaks it into the next.
_GUARDED = {
    "action": "propose",
    "text": FACT,
    "session_name": "s",
    "review_mode": "guardrails",
}
_UNKNOWN = {**_GUARDED, "review_mode": "auto"}


def test_review_mode_reaches_the_service_over_http(monkeypatch, tmp_path):
    monkeypatch.delenv("MARM_ANALYST_AUTO_APPLY", raising=False)
    assert (
        _distill_http(monkeypatch, tmp_path, _GUARDED).json()["review_mode"]
        == "guardrails"
    )


def test_review_mode_reaches_the_service_over_stdio(monkeypatch, tmp_path):
    monkeypatch.delenv("MARM_ANALYST_AUTO_APPLY", raising=False)
    assert (
        _distill_stdio(monkeypatch, tmp_path, _GUARDED)["review_mode"] == "guardrails"
    )


def test_an_unknown_review_mode_is_refused_over_http(monkeypatch, tmp_path):
    assert _distill_http(monkeypatch, tmp_path, _UNKNOWN).status_code == 422


def test_an_unknown_review_mode_is_refused_over_stdio(monkeypatch, tmp_path):
    assert _distill_stdio(monkeypatch, tmp_path, _UNKNOWN)["status"] == "error"


# --- the same modes on the answer STREAM (what the Console uses) ---------------


@pytest.fixture
def streamed(monkeypatch, tmp_path):
    return _streamed(monkeypatch, tmp_path)


def _streamed(monkeypatch, tmp_path, **server_kw):
    """The real HTTP stream route, with the graph and the model stubbed."""
    from conftest import load_isolated_server, local_client

    server = load_isolated_server(monkeypatch, tmp_path, **server_kw)
    import importlib

    cc = importlib.import_module("marm_mcp_server.services.code_context")
    local_llm = importlib.import_module("marm_mcp_server.services.local_llm")
    rv = importlib.import_module("marm_mcp_server.services.analyst.review")

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
        if system == rv.CONCLUSIONS_SYSTEM:
            return "- apply calls claim before writing [S1] [S2]"
        return "apply calls claim [S1] [S2]."

    def stream(*_a, finished=None, **_k):
        if finished is not None:
            finished["reason"] = "stop"
        yield "apply calls claim [S1] [S2]."

    monkeypatch.setattr(cc, "build", build)
    monkeypatch.setattr(cc, "LocalBackend", lambda: object())
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "stub-model")
    monkeypatch.setattr(local_llm, "endpoint_source", lambda: "environment")
    monkeypatch.setattr(local_llm, "complete", complete)
    monkeypatch.setattr(local_llm, "stream", stream)
    client = local_client(server.app)
    from marm_mcp_server.core.memory import memory as live

    return client, live


def _done_of(body):
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(ln.split(": ", 1) for ln in block.splitlines() if ": " in ln)
        events.append((lines["event"], json.loads(lines["data"])))
    assert events[-1][0] == "done", [e for e, _ in events]
    return events[-1][1]


def _stream(client, mode):
    return client.post(
        "/internal/code-context/answer",
        json={"task": "how", "project": "p", "answer": True, "analyst_mode": mode},
    ).text


def test_the_stream_stages_in_manual_review(streamed):
    client, memory = streamed
    done = _done_of(_stream(client, "manual_review"))
    assert done["status"] == "ok"
    assert done["analyst"]["mode"] == "manual_review"
    assert len(done["analyst"]["staged"]) == 1
    assert _pending(memory) == [("analyst:demo", "demo")]


def test_the_stream_stays_read_only_by_default(streamed):
    client, memory = streamed
    done = _done_of(_stream(client, "read_only"))
    assert "analyst" not in done
    assert _pending(memory) == []


def test_the_stream_reports_guardrail_decisions(streamed, monkeypatch):
    monkeypatch.delenv("MARM_ANALYST_AUTO_APPLY", raising=False)
    client, memory = streamed
    done = _done_of(_stream(client, "guardrails"))
    (decision,) = done["analyst"]["decisions"]
    assert decision["applied"] is False
    assert decision["decision"]["checks"]["operator_enabled"] is False
    with memory.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0


def test_the_stream_can_apply_when_the_operator_allows_it(monkeypatch, tmp_path):
    """The one path that writes, through the write queue as the server runs it.

    The first queued write starts the queue on whatever loop is running. From
    the stream's worker thread, anything but the server's own loop leaves the
    write waiting on a queue bound to a loop that has closed, and the answer
    stalls until the queue times out (about a minute) and falls back. `with
    client` keeps one server loop across requests, as a real server has.
    """
    import time

    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    client, memory = _streamed(monkeypatch, tmp_path, write_queue_enabled=True)
    with client:
        started = time.monotonic()
        done = _done_of(_stream(client, "guardrails"))
        elapsed = time.monotonic() - started
        later = client.post(
            "/marm_log_entry",
            json={"entry": "2026-01-02-a later write still lands", "session_name": "s"},
        )
    assert elapsed < 20, f"the answer stalled {elapsed:.0f}s writing through the queue"
    (decision,) = done["analyst"]["decisions"]
    assert decision["applied"] is True, decision["decision"]
    assert later.status_code == 200, later.text
    assert later.json().get("status") != "error", later.text
    with memory.get_connection() as conn:
        (meta,) = conn.execute(
            "SELECT metadata FROM memories WHERE id = ?", (decision["memory_id"],)
        ).fetchone()
    assert json.loads(meta)["origin"] == "analyst"


def test_conclusions_get_the_same_output_budget_as_the_answer(
    staged_memory, monkeypatch
):
    """A reasoning model can spend a small budget thinking and answer with
    nothing, so the conclusions call gets the answer's budget."""
    from marm_mcp_server.services.analyst import Budget

    seen = {}

    def complete(*_a, max_tokens=None, **_k):
        seen["max_tokens"] = max_tokens
        return "- apply calls claim before writing [S1] [S2]"

    monkeypatch.setattr(review.local_llm, "complete", complete)
    _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert seen["max_tokens"] == Budget.from_env().output_tokens


def test_a_model_that_returns_nothing_is_not_reported_as_nothing_durable(
    staged_memory, monkeypatch
):
    _model(monkeypatch, None)
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert out["staged"] == []
    assert out["skipped"] == [
        {"content": "", "reason": "the model wrote no conclusions within its budget"}
    ]


def test_a_reply_with_no_bullets_says_nothing_was_durable(staged_memory, monkeypatch):
    _model(monkeypatch, "Nothing here is worth remembering.")
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert out["skipped"] == [{"content": "", "reason": "nothing durable to propose"}]


def test_a_staged_conclusion_does_not_keep_packet_handles(staged_memory, monkeypatch):
    """`[S1]` names a symbol only inside one packet. A memory keeping it would
    cite nothing for ever after; the evidence is kept separately."""
    _model(monkeypatch, "- `apply` calls claim before writing [S1, S2].")
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert len(out["staged"]) == 1
    with staged_memory.get_connection() as conn:
        content, evidence = conn.execute(
            "SELECT content, evidence FROM distill_staging"
        ).fetchone()
    assert content == "`apply` calls claim before writing."
    assert evidence, "the cited source is still attached"


def test_a_handle_stripped_duplicate_is_still_one_proposal(staged_memory, monkeypatch):
    """Two spellings of one fact that differ only in their citations."""
    _model(
        monkeypatch,
        "- apply calls claim before writing [S1]\n- apply calls claim before writing [S1, S2]",
    )
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert len(out["staged"]) == 1
    assert out["skipped"][0]["reason"] == "already proposed"


def test_a_secret_in_the_cited_evidence_blocks_automatic_apply(monkeypatch):
    """The evidence is persisted with the memory, so it is checked as well."""
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    d = review.guardrail_decision(
        content="apply loads its client configuration first",
        verdict="new",
        evidence='client = Client(api_key="sk-live-1234")',
        source_text=None,
        verification={"state": "verified", "score": 1.0},
        origin="analyst",
    )
    assert d.apply is False
    assert d.checks["no_secret"] is False


def _resolving(monkeypatch, verdict, neighbour=None):
    from marm_mcp_server.core.distill import Resolution

    async def fake(_memory, candidates, **_kw):
        return [
            Resolution(verdict, 0.97, neighbour and "n-1", neighbour)
            for _ in candidates
        ]

    monkeypatch.setattr(review, "resolve", fake)


def test_a_conclusion_already_stored_is_not_staged(staged_memory, monkeypatch):
    """Manual review applies the staged row as it stands, so staging resolves."""
    _model(monkeypatch, "- apply calls claim before writing [S1] [S2]")
    _resolving(monkeypatch, "duplicate", "apply calls claim before writing")
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert out["staged"] == []
    assert out["skipped"][0]["reason"] == "already recorded"


def test_a_near_conclusion_is_staged_with_its_neighbour(staged_memory, monkeypatch):
    _model(monkeypatch, "- apply calls claim before writing [S1] [S2]")
    _resolving(monkeypatch, "near", "apply claims rows")
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert len(out["staged"]) == 1
    with staged_memory.get_connection() as conn:
        row = conn.execute(
            "SELECT verdict, cosine, neighbour_id, neighbour_content "
            "FROM distill_staging"
        ).fetchone()
    assert row == ("near", 0.97, "n-1", "apply claims rows")


def test_the_conclusions_call_is_bounded_by_the_time_budget(staged_memory, monkeypatch):
    seen = {}

    def complete(*_a, **kw):
        seen.update(kw)
        return ""

    monkeypatch.setenv("MARM_ANALYST_TIME_BUDGET", "30")
    monkeypatch.setattr(review.local_llm, "complete", complete)
    _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert seen.get("timeout") is not None and 0 < seen["timeout"] <= 30


def test_a_review_failure_keeps_the_verified_answer(composed, monkeypatch):
    """Staging runs after the answer is verified; its failure must not lose it."""

    import importlib

    async def boom(*_a, **_k):
        raise RuntimeError("staging database locked")

    # The isolated server re-imports the package; patch the module it calls.
    live = importlib.import_module("marm_mcp_server.services.analyst.review")
    monkeypatch.setattr(live, "stage_conclusions", boom)
    out = asyncio.run(
        composed.build_code_context(
            task="how", answer=True, analyst_mode="manual_review"
        )
    )
    assert out["answer_status"] == "ok"
    assert out["answer"]
    skipped = out["analyst"]["skipped"]
    assert skipped and skipped[0]["reason"] == "review failed"
    assert "locked" not in json.dumps(out["analyst"])
