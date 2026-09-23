import asyncio
import types

import pytest

from marm_mcp_server.services.analyst import brief as brief_mod
from marm_mcp_server.services.analyst.budget import Budget, Run
from marm_mcp_server.services.code_context.compose import Context, Symbol


def _ctx(task="how does apply work"):
    return Context(
        project={"name": "demo"},
        task=task,
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
            Symbol(
                "pkg.claim",
                "claim",
                "Function",
                "pkg/a.py",
                11,
                15,
                source="def claim(): pass\n",
            ),
        ],
        graph_edges=[("pkg.apply", "pkg.claim", 1.0)],
    )


@pytest.fixture
def llm(monkeypatch):
    fake = types.SimpleNamespace(
        model="test-model",
        replies=[],
        streamed=[],
        closed=False,
        prompts=[],
        upstreams=[],
    )

    def complete(system, user, **kw):
        fake.prompts.append(user)
        return fake.replies.pop(0) if fake.replies else None

    class Upstream:
        """The model's stream. The fake keeps a reference to it, so only an
        explicit close() can end it; garbage collection cannot do it for us."""

        def __init__(self, user, finished):
            fake.prompts.append(user)
            self._pieces = iter(fake.streamed)
            self._finished = finished
            fake.upstreams.append(self)

        def __iter__(self):
            return self

        def __next__(self):
            try:
                return next(self._pieces)
            except StopIteration:
                if self._finished is not None:
                    self._finished["reason"] = "stop"
                raise

        def close(self):
            fake.closed = True

    def stream(system, user, **kw):
        return Upstream(user, kw.get("finished"))

    monkeypatch.setattr(brief_mod.local_llm, "available", lambda *a, **k: fake.model)
    monkeypatch.setattr(brief_mod.local_llm, "complete", complete)
    monkeypatch.setattr(brief_mod.local_llm, "stream", stream)
    monkeypatch.setattr(brief_mod.local_llm, "endpoint_source", lambda: "environment")
    return fake


def _run(ctx, **kw):
    return asyncio.run(brief_mod.analyse(ctx, "how", budget=Budget(), **kw))


def test_verified_answer_maps_to_ok(llm):
    llm.replies = ["apply calls claim first [S1] [S2]."]
    b = _run(_ctx())
    assert b.status == "ok" and b.verification.state == "verified"
    fields = b.to_answer_fields()
    assert fields["answer_status"] == "ok"
    assert fields["answer_model"] == "test-model", "stays a string for existing callers"
    assert fields["answer_model_info"]["id"] == "test-model"
    assert fields["answer_packet"]["packet_id"] == b.packet.packet_id
    assert [c["handle"] for c in fields["answer_citations"]] == ["S1", "S2"]


def test_uncited_answer_is_unverified(llm):
    llm.replies = ["apply calls claim first."]
    assert _run(_ctx()).to_answer_fields()["answer_status"] == "unverified"


def test_invented_reference_is_rejected(llm):
    llm.replies = ["apply calls [persist_all] [S1]."]
    fields = _run(_ctx()).to_answer_fields()
    assert fields["answer_status"] == "rejected"
    assert fields["answer_unresolved"] == ["persist_all"]


def test_the_prompt_is_the_packet_the_caller_sees(llm):
    llm.replies = ["apply [S1]."]
    b = _run(_ctx())
    assert b.packet.packet_id in llm.prompts[-1]


def test_no_model_is_unavailable_not_an_error(llm, monkeypatch):
    monkeypatch.setattr(brief_mod.local_llm, "available", lambda *a, **k: None)
    b = _run(_ctx())
    assert b.status == "unavailable" and b.answer is None
    assert b.to_answer_fields()["answer_hint"]


def test_follow_up_is_bounded_and_merges(llm, monkeypatch):
    calls = []

    async def fake_build(backend, task, **kw):
        calls.append(task)
        return Context(
            project={"name": "demo"},
            task=task,
            symbols=[
                Symbol(
                    "pkg.db.write",
                    "write",
                    "Function",
                    "pkg/db.py",
                    1,
                    5,
                    source="def write(): pass\n",
                )
            ],
        )

    monkeypatch.setattr(brief_mod, "build", fake_build)
    llm.replies = ["NEED: where is write", "NEED: again", "write is here [S3]."]
    b = asyncio.run(
        brief_mod.analyse(_ctx(), "how", budget=Budget(follow_ups=1), backend=object())
    )
    assert calls == ["where is write"], "one follow-up, not two"
    assert b.follow_ups_used == 1
    assert b.packet.symbol("S1").qualified_name == "pkg.apply", (
        "handles keep their meaning"
    )
    assert b.packet.symbol("S3").qualified_name == "pkg.db.write"


def test_no_follow_up_unless_the_budget_allows_one(llm, monkeypatch):
    async def fake_build(*_a, **_k):
        raise AssertionError("retrieved without a follow-up budget")

    monkeypatch.setattr(brief_mod, "build", fake_build)
    llm.replies = ["apply [S1] calls claim [S2]."]
    b = asyncio.run(brief_mod.analyse(_ctx(), "how", budget=Budget(follow_ups=0)))
    assert b.follow_ups_used == 0


def _stream(ctx, **kw):
    return list(brief_mod.stream_analysis(ctx, "how", budget=Budget(), **kw))


def test_stream_sends_the_packet_then_the_verdict(llm):
    llm.streamed = ["apply calls ", "claim [S1] [S2]."]
    events = _stream(_ctx())
    names = [n for n, _ in events]
    assert names[:2] == ["packet", "start"]
    done = events[-1][1]
    assert names[-1] == "done"
    # #218's keys, which the Console reads, all survive.
    assert {"citations", "unresolved", "status", "length", "truncated"} <= set(done)
    assert done["status"] == "ok"
    assert done["verification"]["state"] == "verified"
    assert done["packet_id"] == events[0][1]["packet_id"]


def test_a_follow_up_re_sends_the_context_it_was_written_from(llm, monkeypatch):
    async def fake_build(backend, task, **kw):
        return Context(
            project={"name": "demo"},
            task=task,
            symbols=[Symbol("pkg.db.write", "write", "Function", "pkg/db.py", 1, 5)],
        )

    monkeypatch.setattr(brief_mod, "build", fake_build)
    llm.replies = ["NEED: write"]
    llm.streamed = ["write [S3]."]
    rendered = []
    events = list(
        brief_mod.stream_analysis(
            _ctx(),
            "how",
            budget=Budget(follow_ups=1),
            backend=object(),
            render_context=lambda c: rendered.append(c) or {"symbols": len(c.symbols)},
        )
    )
    assert events[0] == ("context", {"symbols": 3})
    assert len(rendered[0].symbols) == 3


def test_closing_the_stream_stops_generation(llm):
    llm.streamed = ["a " for _ in range(1000)]
    gen = brief_mod.stream_analysis(_ctx(), "how", budget=Budget())
    for name, _ in gen:
        if name == "delta":
            break
    gen.close()
    assert llm.closed is True


def test_a_deadline_stops_the_stream_and_says_so(llm, monkeypatch):
    llm.streamed = ["apply [S1] " for _ in range(50)]
    calls = {"n": 0}

    def stop_reason(self):
        calls["n"] += 1
        return "deadline" if calls["n"] > 3 else None

    monkeypatch.setattr(Run, "stop_reason", stop_reason)
    events = _stream(_ctx())
    done = events[-1][1]
    assert events[-1][0] == "done"
    assert done["truncated"] is True
    assert done["model_info"]["stopped"] == "deadline"
    assert len([n for n, _ in events if n == "delta"]) < 50


def test_no_model_on_the_stream_is_an_error_event(llm, monkeypatch):
    monkeypatch.setattr(brief_mod.local_llm, "available", lambda *a, **k: None)
    events = _stream(_ctx())
    assert [n for n, _ in events] == ["error"]
    assert events[0][1]["hint"]
