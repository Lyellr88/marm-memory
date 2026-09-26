import asyncio
import json
import types
from dataclasses import replace

import pytest

from marm_mcp_server.services.analyst import brief as brief_mod
from marm_mcp_server.services.analyst import ops as ops_mod
from marm_mcp_server.services.analyst.profile import PROFILES, Run
from marm_mcp_server.services.code_context.compose import Context, Symbol

GENERAL, SMALL, LARGE = PROFILES["general"], PROFILES["small"], PROFILES["large"]


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
        by_op={},
        streamed=[],
        finish="stop",
        closed=False,
        calls=[],
    )

    def complete(system, user, **kw):
        fake.calls.append({"system": system, "user": user, **kw})
        if kw.get("finished") is not None:
            kw["finished"]["reason"] = fake.finish
        schema = kw.get("schema")
        if schema is not None and fake.by_op:
            return json.dumps({k: fake.by_op.get(k, []) for k in schema["properties"]})
        return fake.replies.pop(0) if fake.replies else None

    class Upstream:
        def __init__(self, finished):
            self._pieces = iter(fake.streamed)
            self._finished = finished

        def __iter__(self):
            return self

        def __next__(self):
            try:
                return next(self._pieces)
            except StopIteration:
                if self._finished is not None:
                    self._finished["reason"] = fake.finish
                raise

        def close(self):
            fake.closed = True

    def stream(system, user, **kw):
        fake.calls.append({"system": system, "user": user, "stream": True, **kw})
        return Upstream(kw.get("finished"))

    monkeypatch.setattr(brief_mod.local_llm, "available", lambda *a, **k: fake.model)
    monkeypatch.setattr(brief_mod.local_llm, "complete", complete)
    monkeypatch.setattr(brief_mod.local_llm, "stream", stream)
    monkeypatch.setattr(brief_mod.local_llm, "endpoint_source", lambda: "environment")
    return fake


def _run(ctx, profile=GENERAL):
    return asyncio.run(brief_mod.analyse(ctx, "how", profile=profile))


def _stream(ctx, profile=GENERAL):
    return list(brief_mod.stream_analysis(ctx, "how", profile=profile))


# --- the general profile: one free-form answer under hard limits -----------


def test_verified_answer_maps_to_ok(llm):
    llm.replies = ["apply calls claim first [S1] [S2]."]
    b = _run(_ctx())
    assert b.status == "ok" and b.verification.state == "verified"
    fields = b.to_answer_fields()
    assert fields["answer_status"] == "ok"
    assert fields["answer_model"] == "test-model", "stays a string for existing callers"
    assert fields["answer_packet"]["packet_id"] == b.packet.packet_id
    assert [c["handle"] for c in fields["answer_citations"]] == ["S1", "S2"]
    assert fields["answer_profile"]["name"] == "general"


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
    assert b.packet.packet_id in llm.calls[-1]["user"]


def test_no_model_is_unavailable_not_an_error(llm, monkeypatch):
    monkeypatch.setattr(brief_mod.local_llm, "available", lambda *a, **k: None)
    b = _run(_ctx())
    assert b.status == "unavailable" and b.answer is None
    assert b.to_answer_fields()["answer_hint"]


def test_the_cap_is_requested_once_and_reported_as_requested(llm):
    """No wider retry: the reported cap is the one the server was asked for."""
    llm.replies = ["apply [S1] calls claim [S2]."]
    b = _run(_ctx(), replace(GENERAL, output_tokens=300, reasoning_tokens=200))
    (call,) = llm.calls
    assert call["max_tokens"] == 500 and call["widen"] is False
    assert b.model_info["max_tokens"] == 500
    assert (b.model_info["output_tokens"], b.model_info["reasoning_tokens"]) == (
        300,
        200,
    )


def test_an_answer_cut_off_at_the_cap_is_never_verified(llm):
    llm.replies = ["apply calls claim first [S1] [S2]."]
    llm.finish = "length"
    b = _run(_ctx())
    assert b.truncated and b.verification.state == "uncertain"


def test_the_analyst_cannot_retrieve():
    """MARM is the retrieval authority: the analyst has no path to build()."""
    assert not hasattr(brief_mod, "build")
    assert not hasattr(brief_mod, "_expand")


# --- the deadline ------------------------------------------------------------


def test_no_call_starts_after_the_deadline(llm):
    """The reported probe: a 0.01 s budget still made a model call."""
    b = _run(_ctx(), replace(GENERAL, time_s=0.0))
    assert llm.calls == []
    assert b.status == "failed" and b.model_info["stopped"] == "deadline"


def test_no_stream_starts_after_the_deadline(llm):
    events = _stream(_ctx(), replace(GENERAL, time_s=0.0))
    assert llm.calls == []
    assert events[-1][0] == "error"


def test_no_operation_starts_after_the_deadline(llm):
    b = _run(_ctx(), replace(SMALL, time_s=0.0))
    assert llm.calls == []
    assert {r.status for r in b.operations} == {"skipped"}
    assert b.status == "failed"


def test_operations_stop_when_the_deadline_passes_between_them(llm, monkeypatch):
    llm.by_op = {"summary": [{"text": "apply calls claim", "cites": ["S1"]}]}
    real = Run.stop_reason

    def stop_after_first_call(self):
        return "deadline" if llm.calls else real(self)

    monkeypatch.setattr(Run, "stop_reason", stop_after_first_call)
    b = _run(_ctx(), SMALL)
    assert len(llm.calls) == 1
    assert [r.status for r in b.operations][1:] == ["skipped"] * 4
    assert b.verification.state != "verified", "an incomplete run is not verified"


def test_each_call_gets_only_the_time_that_remains(llm):
    llm.by_op = {"summary": []}
    _run(_ctx(), SMALL)
    assert all(c["timeout"] <= SMALL.time_s for c in llm.calls)


# --- the structured profiles ------------------------------------------------

_GOOD = {
    "summary": [{"text": "apply calls claim", "cites": ["S1", "S2"]}],
    "facts": [{"text": "apply calls claim", "cites": ["S1"], "quote": "claim()"}],
    "relations": [
        {"kind": "calls", "from": "S1", "to": "S2", "text": "apply calls claim"}
    ],
    "missing": [{"text": "what claim returns is not shown"}],
    "next_steps": [{"action": "read", "cites": ["S2"], "text": "read claim"}],
}


def test_small_runs_one_schema_bound_call_per_operation(llm):
    llm.by_op = _GOOD
    b = _run(_ctx(), SMALL)
    assert len(llm.calls) == len(ops_mod.OPERATIONS)
    assert all(c["schema"] and c["widen"] is False for c in llm.calls)
    assert b.status == "ok", b.verification
    ids = [i["id"] for i in b.to_answer_fields()["answer_items"]]
    assert ids == ["A1", "F1", "R1", "G1", "N1"]


def test_large_batches_every_operation_into_one_call(llm):
    llm.by_op = _GOOD
    b = _run(_ctx(), LARGE)
    (call,) = llm.calls
    assert set(call["schema"]["properties"]) == {op.key for op in ops_mod.OPERATIONS}
    assert b.status == "ok"
    assert b.model_info["calls"] == 1


def test_batched_results_are_still_verified_one_by_one(llm):
    llm.by_op = dict(
        _GOOD,
        relations=[
            {"kind": "calls", "from": "S2", "to": "S1", "text": "claim calls apply"}
        ],
    )
    b = _run(_ctx(), LARGE)
    states = {i.id: i.state for i in b.items}
    assert states["R1"] == "uncertain" and states["F1"] == "verified"
    assert b.verification.state == "uncertain"


def test_malformed_output_cannot_be_verified(llm):
    llm.replies = ["this is not json"] * 5
    b = _run(_ctx(), SMALL)
    assert {r.status for r in b.operations} == {"malformed"}
    assert b.status == "failed"
    assert b.verification.state != "verified"


def test_an_entry_that_breaks_the_contract_is_dropped_and_counted(llm):
    llm.by_op = dict(_GOOD, facts=[{"text": "no quote", "cites": ["S1"]}])
    b = _run(_ctx(), SMALL)
    facts = next(r for r in b.operations if r.op == "facts")
    assert facts.malformed == 1 and facts.items == []
    assert b.verification.state == "uncertain"


def test_an_invented_handle_in_any_item_rejects_the_answer(llm):
    llm.by_op = dict(_GOOD, summary=[{"text": "apply", "cites": ["S9"]}])
    b = _run(_ctx(), SMALL)
    assert b.status == "rejected"


def test_only_gaps_is_an_abstention_not_a_verified_answer(llm):
    llm.by_op = {"missing": [{"text": "nothing about deletes"}]}
    b = _run(_ctx(), SMALL)
    assert b.verification.abstained and b.verification.state == "uncertain"


def test_a_reply_cut_off_at_the_cap_fails_that_operation(llm):
    llm.by_op = _GOOD
    llm.finish = "length"
    b = _run(_ctx(), SMALL)
    assert {r.status for r in b.operations} == {"failed"}
    assert b.verification.state != "verified"


# --- one verdict on both paths ---------------------------------------------


@pytest.mark.parametrize("profile", [GENERAL, SMALL, LARGE], ids=lambda p: p.name)
def test_json_and_stream_give_the_same_verification(llm, profile):
    llm.by_op = _GOOD
    llm.replies = ["apply calls claim first [S1] [S2]."]
    llm.streamed = ["apply calls claim ", "first [S1] [S2]."]
    fields = _run(_ctx(), profile).to_answer_fields()
    done = _stream(_ctx(), profile)[-1][1]
    assert done["verification"] == fields["answer_verification"]
    assert done.get("items") == fields.get("answer_items")
    assert done["profile"] == fields["answer_profile"]


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
    assert done["packet_id"] == events[0][1]["packet_id"]


def test_a_structured_stream_reports_each_operation_as_it_finishes(llm):
    llm.by_op = _GOOD
    events = _stream(_ctx(), SMALL)
    ops = [p["op"] for n, p in events if n == "operation"]
    assert ops == [op.name for op in ops_mod.OPERATIONS]
    assert events[-1][0] == "done"


def test_closing_the_stream_stops_generation(llm):
    llm.streamed = ["a " for _ in range(1000)]
    gen = brief_mod.stream_analysis(_ctx(), "how", profile=GENERAL)
    for name, _ in gen:
        if name == "delta":
            break
    gen.close()
    assert llm.closed is True


def test_a_deadline_stops_the_stream_and_says_so(llm, monkeypatch):
    llm.streamed = ["apply [S1] " for _ in range(50)]
    calls = {"n": 0}
    real = Run.stop_reason

    def stop_reason(self):
        calls["n"] += 1
        return "deadline" if calls["n"] > 3 else real(self)

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


def test_disagreements_ride_on_the_answer(llm):
    ctx = _ctx()
    ctx.memories = [{"id": "m1", "content": "apply does not call claim."}]
    llm.replies = ["apply [S1]."]
    fields = _run(ctx).to_answer_fields()
    (d,) = fields["answer_disagreements"]
    assert d["severity"] == "contradicted"
