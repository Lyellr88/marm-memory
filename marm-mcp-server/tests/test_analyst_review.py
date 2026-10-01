import asyncio
import json
import sys

import pytest

from marm_mcp_server.services.analyst import review
from marm_mcp_server.services.analyst.brief import Brief
from marm_mcp_server.services.analyst.ops import Item, OpResult
from marm_mcp_server.services.analyst.packet import build_packet
from marm_mcp_server.services.analyst.profile import PROFILES
from marm_mcp_server.services.analyst.verify import verify
from marm_mcp_server.services.code_context.compose import Context, Symbol


@pytest.fixture()
def staged_memory(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    assert load_isolated_server(monkeypatch, tmp_path) is not None
    from marm_mcp_server.core.memory import memory as live

    return live


@pytest.fixture(autouse=True)
def env_only_switch(monkeypatch):
    """Unit tests decide the operator switch from the environment alone; the
    tests of the saved override ask for `saved_switch`."""
    import types

    from marm_mcp_server.core import runtime_flags

    monkeypatch.setattr(
        review,
        "runtime_flags",
        types.SimpleNamespace(
            ANALYST_AUTO_APPLY=runtime_flags.ANALYST_AUTO_APPLY,
            get_bool=lambda _key, env_default: env_default,
        ),
    )


@pytest.fixture
def saved_switch(monkeypatch, staged_memory):
    from marm_mcp_server.core import runtime_flags

    monkeypatch.setattr(review, "runtime_flags", runtime_flags)
    return runtime_flags


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """Review never asks the model anything; a call is a failure."""

    def refuse(*_a, **_k):
        raise AssertionError("review called the model")

    from marm_mcp_server.services import local_llm

    monkeypatch.setattr(local_llm, "complete", refuse)


def _packet(source="def apply():\n    claim()\n", memories=()):
    return build_packet(
        Context(
            project={"name": "demo"},
            task="how",
            symbols=[
                Symbol(
                    "pkg.apply", "apply", "Function", "pkg/a.py", 1, 9, source=source
                ),
                Symbol("pkg.claim", "claim", "Function", "pkg/a.py", 11, 15),
            ],
            memories=list(memories),
            graph_edges=[("pkg.apply", "pkg.claim", 1.0)],
        )
    )


def _brief(answer, packet=None):
    packet = packet or _packet()
    b = Brief(packet=packet, profile=PROFILES["general"], answer=answer)
    b.verification = verify(answer, packet)
    b.status = {"verified": "ok", "uncertain": "unverified", "rejected": "rejected"}[
        b.verification.state
    ]
    return b


def _stage(memory, answer, packet=None):
    return asyncio.run(
        review.stage_conclusions(
            memory,
            _brief(answer, packet),
            "how",
            session_name="analyst:demo",
            project="demo",
        )
    )


def _rows(memory):
    with memory.get_connection() as conn:
        return conn.execute(
            "SELECT content, evidence, origin, verification FROM distill_staging"
        ).fetchall()


# --- what is staged ----------------------------------------------------------


def test_a_verified_call_claim_is_staged_as_marms_own_call_edge(staged_memory):
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert len(out["staged"]) == 1
    ((content, evidence, origin, ver),) = _rows(staged_memory)
    assert content == "`pkg.apply` calls `pkg.claim`"
    assert evidence == "call edge pkg.apply -> pkg.claim"
    assert origin == "analyst"
    assert json.loads(ver)["claim_kind"] == "call_edge"


def test_the_reported_unsupported_claim_is_never_staged(staged_memory, monkeypatch):
    """The maintainer's case: a real `apply` that deletes nothing."""
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    packet = _packet(source="def apply(): return 1")
    out = _stage(staged_memory, "apply deletes every memory [S1].", packet)
    assert out["staged"] == []
    assert "not verified" in out["skipped"][0]["reason"]
    assert _rows(staged_memory) == []


def test_an_uncertain_answer_stages_nothing_and_asks_the_model_nothing(staged_memory):
    out = _stage(staged_memory, "apply calls claim first.")
    assert out["staged"] == []
    assert out["skipped"][0]["reason"].startswith("the answer is uncertain")


def test_rejected_brief_stages_nothing(staged_memory):
    out = _stage(staged_memory, "apply calls [persist_all] [S1].")
    assert out["staged"] == []
    assert "rejected" in out["skipped"][0]["reason"]


def test_abstention_stages_nothing(staged_memory):
    out = _stage(staged_memory, "The packet does not show how apply writes.")
    assert out["staged"] == []


def test_the_same_conclusion_is_not_proposed_twice(staged_memory):
    _stage(staged_memory, "apply calls claim [S1] [S2].")
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert out["staged"] == []
    assert out["skipped"][0]["reason"] == "already proposed"


def test_staged_conclusion_applies_through_distill(staged_memory):
    from marm_mcp_server.services import distill

    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    applied = asyncio.run(distill.apply(staged_memory, out["staged"][0]))
    assert applied["status"] == "success"
    with staged_memory.get_connection() as conn:
        (meta,) = conn.execute(
            "SELECT metadata FROM memories WHERE id = ?", (applied["memory_id"],)
        ).fetchone()
    assert json.loads(meta)["origin"] == "analyst"


def test_review_reports_origin_and_verification(staged_memory):
    from marm_mcp_server.services import distill

    _stage(staged_memory, "apply calls claim [S1] [S2].")
    (entry,) = distill.review(staged_memory, session_name="analyst:demo")["pending"]
    assert entry["origin"] == "analyst"
    assert entry["verification"]["state"] == "verified"


# --- claim kinds ---------------------------------------------------------------


def _structured(items, packet=None):
    packet = packet or _packet()
    b = Brief(packet=packet, profile=PROFILES["small"], answer="x")
    b.operations = [OpResult(op="all", status="ok", items=items)]
    return b


def _item(op, text, **kw):
    kw.setdefault("state", "verified")
    kw.setdefault("support", "citation")
    return Item(id=kw.pop("id", "X1"), op=op, text=text, **kw)


def test_a_verified_call_relation_becomes_a_call_edge():
    (c,) = review.conclusions(
        _structured(
            [
                _item(
                    "relations",
                    "apply calls claim",
                    kind="calls",
                    source="S1",
                    target="S2",
                )
            ]
        )
    )
    assert (c.claim_kind, c.content) == ("call_edge", "`pkg.apply` calls `pkg.claim`")


def test_a_paraphrased_fact_is_staged_as_a_paraphrase():
    (c,) = review.conclusions(
        _structured(
            [
                _item(
                    "facts",
                    "apply hands the row to claim first",
                    cites=("S1",),
                    quote="claim()",
                    support="quote",
                )
            ]
        )
    )
    assert c.claim_kind == "paraphrase"


def test_a_fact_restating_its_quote_is_a_quoted_span():
    (c,) = review.conclusions(
        _structured(
            [
                _item(
                    "facts",
                    "def apply():",
                    cites=("S1",),
                    quote="def apply():",
                    support="quote",
                )
            ]
        )
    )
    assert c.claim_kind in ("verbatim_statement", "quoted_span")


def test_a_verbatim_memory_statement_is_mechanical():
    packet = _packet(
        memories=[{"id": "m1", "content": "apply claims the row before writing."}]
    )
    (c,) = review.conclusions(
        _structured(
            [_item("summary", "apply claims the row before writing", cites=("M1",))],
            packet,
        )
    )
    assert c.claim_kind == "verbatim_statement"


def test_an_identifier_in_its_cited_range_is_marms_own_statement():
    (c,) = review.conclusions(
        _structured([_item("summary", "`apply` is at pkg/a.py:3", cites=("S1",))])
    )
    assert c.claim_kind == "identifier_in_range"
    assert c.content == "`pkg.apply` is defined in pkg/a.py:1-9"


def test_an_unverified_or_non_substantive_item_is_never_a_conclusion():
    items = [
        _item("facts", "apply writes the row", cites=("S1",), state="uncertain"),
        _item("gaps", "the writer is not shown", state="missing"),
        _item("next_steps", "read claim", cites=("S2",), state="proposal"),
    ]
    assert review.conclusions(_structured(items)) == []


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

    def complete(system, *_a, finished=None, **_k):
        if finished is not None:
            finished["reason"] = "stop"
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
        # The selection path: the content is the span, so evidence is empty.
        "evidence": "",
        "source_text": "We met. apply claims the row before writing it. Then lunch.",
        "verification": None,
        "origin": "distill",
    }
    kw.update(over)
    return kw


def _analyst(kind, content, evidence, answer_state="verified", state="verified"):
    return _ok(
        origin="analyst",
        content=content,
        evidence=evidence,
        source_text=None,
        verification={
            "state": state,
            "claim_kind": kind,
            "answer": {"state": answer_state},
        },
    )


EDGE = (
    "call_edge",
    "`pkg.apply` calls `pkg.claim`",
    "call edge pkg.apply -> pkg.claim",
)


def test_all_checks_pass(monkeypatch):
    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    d = guardrail_decision(**_ok())
    assert d.apply is True and all(d.checks.values())
    assert d.to_public()["status"] == "applied"


def test_a_call_edge_the_analyst_verified_can_be_applied(monkeypatch):
    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    d = guardrail_decision(**_analyst(*EDGE))
    assert d.apply is True, d.reason


def test_the_reported_paraphrase_returns_review_required(monkeypatch):
    """Cited, verified, and still not provable: prose is for a reviewer."""
    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    d = guardrail_decision(
        **_analyst("paraphrase", "apply deletes every memory", "def apply(): return 1")
    )
    assert d.apply is False
    assert d.checks["mechanically_provable"] is False
    assert d.to_public()["status"] == "review_required"
    assert "cannot prove a paraphrase claim" in d.reason


@pytest.mark.parametrize(
    "kind,content,evidence",
    [
        # Content that does not match the kind's template, whatever it claims.
        ("call_edge", "apply deletes every memory", "call edge pkg.apply -> pkg.claim"),
        ("identifier_in_range", "`pkg.apply` deletes rows", "pkg/a.py:1-9"),
        ("verbatim_statement", "apply deletes every memory", "def apply(): return 1"),
        ("quoted_span", "claim()", "write_row()"),
        ("made_up_kind", "`pkg.apply` calls `pkg.claim`", "call edge pkg.apply -> x"),
    ],
)
def test_a_claim_kind_is_rechecked_against_what_was_stored(
    monkeypatch, kind, content, evidence
):
    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    d = guardrail_decision(**_analyst(kind, content, evidence))
    assert d.apply is False and d.checks["mechanically_provable"] is False


@pytest.mark.parametrize("answer_state", ["uncertain", "rejected"])
def test_an_unverified_answer_blocks_even_a_provable_claim(monkeypatch, answer_state):
    monkeypatch.setenv("MARM_ANALYST_AUTO_APPLY", "1")
    d = guardrail_decision(**_analyst(*EDGE, answer_state=answer_state))
    assert d.apply is False and d.checks["verified"] is False


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
    assert "automatic apply is off" in out["guardrails"][0]["decision"]["reason"]
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

    def complete(system, *_a, finished=None, **_k):
        if finished is not None:
            finished["reason"] = "stop"
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


def test_a_secret_in_the_cited_evidence_blocks_automatic_apply(monkeypatch):
    """The evidence is persisted with the memory, so it is checked as well."""
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    d = review.guardrail_decision(
        content="apply loads its client configuration first",
        verdict="new",
        evidence='client = Client(api_key="sk-live-1234")',
        source_text=None,
        verification={
            "state": "verified",
            "claim_kind": "call_edge",
            "answer": {"state": "verified"},
        },
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
    _resolving(monkeypatch, "duplicate", "`pkg.apply` calls `pkg.claim`")
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert out["staged"] == []
    assert out["skipped"][0]["reason"] == "already recorded"


def test_a_near_conclusion_is_staged_with_its_neighbour(staged_memory, monkeypatch):
    _resolving(monkeypatch, "near", "apply claims rows")
    out = _stage(staged_memory, "apply calls claim [S1] [S2].")
    assert len(out["staged"]) == 1
    with staged_memory.get_connection() as conn:
        row = conn.execute(
            "SELECT verdict, cosine, neighbour_id, neighbour_content "
            "FROM distill_staging"
        ).fetchone()
    assert row == ("near", 0.97, "n-1", "apply claims rows")


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


# --- a verbatim statement is a whole statement --------------------------------


def _sweep_packet():
    return _packet(
        source="def apply():\n    # never deletes every memory row\n    claim()\n",
        memories=[{"id": "m1", "content": "apply claims the row. It writes once."}],
    )


def test_a_fragment_of_a_negated_comment_is_not_a_verbatim_statement():
    """The review's case: the claim sits inside the comment, minus `never`."""
    c = review._classify("deletes every memory row", ["S1"], _sweep_packet(), "A1")
    assert c.claim_kind == "paraphrase"


def test_a_whole_sentence_is_a_verbatim_statement_and_is_its_evidence():
    c = review._classify("apply claims the row", ["M1"], _sweep_packet(), "A1")
    assert c.claim_kind == "verbatim_statement"
    assert c.evidence == "apply claims the row"


def test_a_quote_is_a_span_only_when_it_is_a_whole_source_line():
    whole = review._classify("claim()", ["S1"], _sweep_packet(), "F1", quote="claim()")
    part = review._classify("laim(", ["S1"], _sweep_packet(), "F1", quote="laim(")
    assert whole.claim_kind in ("quoted_span", "verbatim_statement")
    assert part.claim_kind == "paraphrase"


def test_the_recheck_needs_equality_not_containment(monkeypatch):
    """The stored shape the old re-check could never catch: the claim inside
    its own negated evidence."""
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    d = guardrail_decision(
        **_analyst(
            "verbatim_statement",
            "deletes every memory row",
            "never deletes every memory row",
        )
    )
    assert d.apply is False and d.checks["mechanically_provable"] is False


# --- statements are never cut out of a wrapped sentence ------------------------


def _wrapped(source):
    return _packet(source=source)


def test_a_line_of_a_wrapped_comment_is_not_a_verbatim_statement():
    p = _wrapped(
        "def apply():\n    # Callers must never\n    # write the row directly.\n"
    )
    c = review._classify("write the row directly", ["S1"], p, "A1")
    assert c.claim_kind == "paraphrase"


def test_a_docstring_line_does_not_pass_as_a_line_of_code():
    p = _wrapped(
        'def apply():\n    """\n    Callers must never\n    write the row directly\n    """\n'
    )
    c = review._classify(
        "write the row directly", ["S1"], p, "F1", quote="write the row directly"
    )
    assert c.claim_kind == "paraphrase"


# --- distilled proposals: only a whole verbatim sentence may be applied --------


def test_generated_distill_content_is_left_for_review(monkeypatch):
    """The model wrote the content; only its evidence span is verbatim."""
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    d = guardrail_decision(
        **_ok(
            content="apply always writes rows twice",
            evidence="apply claims the row before writing it.",
        )
    )
    assert d.apply is False
    assert d.checks["content_is_span"] is False


def test_a_fragment_of_a_source_sentence_is_not_verbatim(monkeypatch):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    d = guardrail_decision(
        **_ok(
            content="write the row directly",
            source_text="Callers must never write the row directly.",
        )
    )
    assert d.apply is False and d.checks["evidence_verbatim"] is False


def test_a_fragment_of_a_wrapped_source_sentence_is_not_verbatim(monkeypatch):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    d = guardrail_decision(
        **_ok(
            content="write the row directly",
            source_text="Callers must never\nwrite the row directly.",
        )
    )
    assert d.apply is False and d.checks["evidence_verbatim"] is False


def test_a_whole_sentence_that_wraps_is_still_verbatim(monkeypatch):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    d = guardrail_decision(
        **_ok(
            content="Callers must never write the row directly",
            source_text="Callers must never write\nthe row directly.",
        )
    )
    assert d.checks["evidence_verbatim"] is True, d.checks


@pytest.mark.parametrize(
    "source_text",
    [
        "- apply claims the row before writing it\n- then it retries",
        "## apply\napply claims the row before writing it",
        "Notes\n\napply claims the row before writing it",
    ],
)
def test_list_items_and_headings_stay_separate_units(monkeypatch, source_text):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    d = guardrail_decision(**_ok(source_text=source_text))
    assert d.checks["evidence_verbatim"] is True, d.checks


# --- the operator switch is a runtime flag ---------------------------------------


def test_a_saved_off_beats_an_environment_on(saved_switch, monkeypatch):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    saved_switch.set_bool(saved_switch.ANALYST_AUTO_APPLY, False)
    assert review.auto_apply_allowed() is False
    assert guardrail_decision(**_ok()).checks["operator_enabled"] is False


def test_a_saved_on_needs_no_environment(saved_switch, monkeypatch):
    monkeypatch.delenv(review.AUTO_APPLY_ENV, raising=False)
    saved_switch.set_bool(saved_switch.ANALYST_AUTO_APPLY, True)
    assert review.auto_apply_allowed() is True


def test_an_unreadable_switch_never_authorizes_a_write(saved_switch, monkeypatch):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    monkeypatch.setattr(saved_switch, "_read", lambda _key: (False, None))
    assert review.auto_apply_allowed() is False


def test_the_switch_is_saved_and_reported_over_http(monkeypatch, tmp_path):
    from conftest import load_isolated_server, local_client

    server = load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setattr(
        review, "runtime_flags", sys.modules["marm_mcp_server.core.runtime_flags"]
    )
    monkeypatch.delenv(review.AUTO_APPLY_ENV, raising=False)
    client = local_client(server.app)
    system = sys.modules["marm_mcp_server.endpoints.system"]
    monkeypatch.setattr(system.local_llm, "status", lambda: {})

    saved = client.put("/internal/runtime/settings/llm", json={"auto_apply": True})
    assert saved.status_code == 200, saved.text
    assert review.auto_apply_allowed() is True
    status = system._llm_status()["analyst_auto_apply"]
    assert status == {"enabled": True, "source": "override"}

    client.put("/internal/runtime/settings/llm", json={"auto_apply": None})
    assert review.auto_apply_allowed() is True, "null leaves the switch alone"

    # An empty string returns the switch to MARM_ANALYST_AUTO_APPLY.
    cleared = client.put("/internal/runtime/settings/llm", json={"auto_apply": ""})
    assert cleared.status_code == 200, cleared.text
    assert system._llm_status()["analyst_auto_apply"] == {
        "enabled": False,
        "source": "environment",
    }


# --- credentials without a label ------------------------------------------------


# Built from parts so the file itself carries no scannable secret.
_JWT = (
    "eyJhbGciOiJIUzI1NiJ9"
    + "."
    + "eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    + "."
    + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
)


@pytest.mark.parametrize(
    "secret",
    [
        "sk-" + "proj-" + "4f9aZbQ2x7LmN1cV" + "8tR3wY6uP0sK5dE2",
        "ghp_" + "16C7e42F292c6912" + "E7710c838347Ae178B4a",
        "AKIA" + "IOSFODNN7" + "EXAMPLE",
        "Bearer " + _JWT,
        _JWT,
        "postgres://" + "admin:" + "hunter2secret" + "@db.internal:5432/app",
        "xox" + "b-2748-39201-" + "Fk2d9QmZpL0aXv7T",
    ],
)
def test_a_raw_credential_blocks_automatic_apply(monkeypatch, secret):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    content = f"the deploy step uses {secret} to connect"
    d = guardrail_decision(**_ok(content=content, source_text=f"We met. {content}."))
    assert d.checks["no_secret"] is False, secret


@pytest.mark.parametrize(
    "text",
    [
        "the token bucket refills every second",
        "apply reads the password policy before it writes",
        "see https://example.com/docs/setup for the steps",
        "the sk-learn pipeline runs nightly",
    ],
)
def test_ordinary_prose_is_not_a_credential(monkeypatch, text):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    d = guardrail_decision(**_ok(content=text, source_text=f"We met. {text}. Then."))
    assert d.checks["no_secret"] is True, text


# --- decided at apply time, recorded as it happened ------------------------------


def _staged_only(memory):
    from marm_mcp_server.services import distill

    out = asyncio.run(
        distill.propose(
            memory, FACT, session_name="s", use_llm=False, review_mode="manual"
        )
    )
    return next(p["id"] for p in out["proposals"] if p.get("staged"))


def test_a_distilled_proposal_is_re_resolved_before_it_is_applied(
    staged_memory, monkeypatch
):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    pid = _staged_only(staged_memory)
    # Staged as new; another process stores the same fact before apply runs.
    _resolving(monkeypatch, "duplicate", "apply claims the row before writing it.")

    (entry,) = asyncio.run(review.auto_apply(staged_memory, [pid], source_text=FACT))
    assert entry["applied"] is False
    assert entry["decision"]["checks"]["novel"] is False


def test_a_failed_apply_is_recorded_as_failed(staged_memory, monkeypatch):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    pid = _staged_only(staged_memory)

    # The real apply, failing only the memory write: its error envelope is the
    # contract this has to read, not one invented here.
    async def failing_write(*_a, **_k):
        raise TimeoutError("write queue timed out")

    monkeypatch.setattr(staged_memory, "store_memory_queued", failing_write)
    (entry,) = asyncio.run(review.auto_apply(staged_memory, [pid], source_text=FACT))

    assert entry["applied"] is False
    assert entry["decision"]["status"] == "apply_failed"
    assert entry["error"] == "write failed: write queue timed out"
    with staged_memory.get_connection() as conn:
        decision, status = conn.execute(
            "SELECT decision, status FROM distill_staging WHERE id = ?", (pid,)
        ).fetchone()
    assert json.loads(decision)["error"] == "write failed: write queue timed out"
    assert status == "pending", "a failed write leaves the proposal reviewable"


def test_an_applied_proposal_is_not_left_awaiting_review(staged_memory, monkeypatch):
    monkeypatch.setenv(review.AUTO_APPLY_ENV, "1")
    out = _propose(staged_memory)
    (applied,) = [p for p in out["proposals"] if p.get("applied")]
    assert applied["applied_memory_id"]
    assert out["applied"] == 1
    assert out["staged"] == 0, "staged counts only what awaits review"
