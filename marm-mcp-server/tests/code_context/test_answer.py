"""Grounding of a generated answer, on the JSON path and the SSE path alike.

An answer is labelled grounded only when its citations resolve to the context
it was written from. Neither path contacts a model or a graph backend here.
"""

import asyncio

import pytest

from marm_mcp_server.services import code_context as cc
from marm_mcp_server.services import local_llm
from marm_mcp_server.services.code_context.compose import Context, Symbol


def _ctx():
    return Context(
        project={"name": "p", "root_path": "/x/proj"},
        task="how does apply claim a row",
        symbols=[
            Symbol("svc.apply", "apply", "Function", "svc.py", 10, 40, seeded=True),
            Symbol("svc.claim_row", "claim_row", "Function", "svc.py", 50, 60),
        ],
    )


@pytest.fixture
def model(monkeypatch):
    """A model that answers with whatever text a test gives it."""
    reply = {"text": ""}
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "stub-model")
    monkeypatch.setattr(local_llm, "complete", lambda *a, **k: reply["text"])

    def stream(*_a, **_k):
        text = reply["text"]
        yield from (text[i : i + 7] for i in range(0, len(text), 7))

    monkeypatch.setattr(local_llm, "stream", stream)
    return reply


@pytest.fixture
def composed(monkeypatch):
    """Stand in for the graph: every composition returns the same context."""
    calls = []

    async def build(_backend, task, **_kw):
        calls.append(task)
        return _ctx()

    monkeypatch.setattr(cc, "build", build)
    monkeypatch.setattr(cc, "LocalBackend", lambda: object())
    return calls


def _json(text, model):
    model["text"] = text
    return asyncio.run(cc.answer_from_context(_ctx(), "how"))


def _sse(text, model):
    model["text"] = text
    return list(cc.stream_answer("how", None, None, 12000))


def _done(events):
    names = [name for name, _ in events]
    assert names[-1] == "done", names
    return events[-1][1]


GROUNDED = "apply takes the row first [apply], via [`claim_row`]."
UNCITED = "apply takes the row first, then writes it."
INVENTED = "apply takes the row first [apply], then calls [persist_all_rows]."


def test_json_grounded_answer_is_ok(model):
    out = _json(GROUNDED, model)
    assert out["answer_status"] == "ok"
    assert [c["name"] for c in out["answer_citations"]] == ["apply", "claim_row"]
    assert out["answer_unresolved"] == []


def test_json_answer_with_no_resolving_citation_is_unverified(model):
    out = _json(UNCITED, model)
    assert out["answer_status"] == "unverified"
    assert out["answer"] == UNCITED, "the text is still returned, only not vouched for"
    assert out["answer_citations"] == []
    assert out["answer_hint"]


def test_json_answer_citing_a_symbol_not_in_context_is_unverified(model):
    out = _json(INVENTED, model)
    assert out["answer_status"] == "unverified"
    assert out["answer_unresolved"] == ["persist_all_rows"]
    assert [c["name"] for c in out["answer_citations"]] == ["apply"]


@pytest.mark.parametrize(
    "noise",
    [
        "see [setup_guide](https://example.com)",
        "footnote [1]",
        "- [ ] todo",
        "[optional]",
    ],
)
def test_brackets_that_are_not_citations_do_not_count_against_it(model, noise):
    out = _json(f"{GROUNDED} {noise}", model)
    assert out["answer_status"] == "ok", out.get("answer_unresolved")


def test_sse_grounded_answer_is_ok(model, composed):
    done = _done(_sse(GROUNDED, model))
    assert done["status"] == "ok"
    assert [c["name"] for c in done["citations"]] == ["apply", "claim_row"]


def test_sse_answer_with_no_resolving_citation_is_unverified(model, composed):
    done = _done(_sse(UNCITED, model))
    assert done["status"] == "unverified"
    assert done["citations"] == []
    assert done["hint"]


def test_sse_answer_citing_a_symbol_not_in_context_is_unverified(model, composed):
    done = _done(_sse(INVENTED, model))
    assert done["status"] == "unverified"
    assert done["unresolved"] == ["persist_all_rows"]


# --- one composition feeds both the panes and the answer --------------------


def test_the_stream_composes_once_and_sends_that_composition_first(model, composed):
    model["text"] = GROUNDED
    events = list(
        cc.stream_answer("how", None, None, 12000, include_graph=True, detail=3)
    )

    assert composed == ["how"], "one request must compose exactly once"
    name, payload = events[0]
    assert name == "context"
    assert payload == cc.serialise(_ctx(), "how", include_graph=True, detail=3)


def test_the_answer_is_written_from_the_composition_it_sent(
    model, composed, monkeypatch
):
    prompts = []

    def stream(system, user, **_k):
        prompts.append(user)
        yield GROUNDED

    monkeypatch.setattr(local_llm, "stream", stream)
    events = list(
        cc.stream_answer("how", None, None, 12000, include_graph=True, detail=3)
    )

    assert prompts and prompts[0].startswith(cc.render(_ctx()))
    assert events[0][1]["markdown"] == cc.render(_ctx())


def test_an_unavailable_graph_is_reported_as_the_context(model, monkeypatch):
    async def build(*_a, **_k):
        raise cc.GraphUnavailable("no indexed project matches 'x'")

    monkeypatch.setattr(cc, "build", build)
    monkeypatch.setattr(cc, "LocalBackend", lambda: object())
    events = list(cc.stream_answer("how", "x", None, 12000))

    assert [name for name, _ in events] == ["context"]
    assert events[0][1]["status"] == "no_project"
    assert events[0][1]["hint"]


def test_no_model_still_delivers_the_context(composed, monkeypatch):
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: None)
    events = list(
        cc.stream_answer("how", None, None, 12000, include_graph=True, detail=3)
    )

    assert [name for name, _ in events] == ["context", "error"]
    assert events[0][1]["status"] == "success"
