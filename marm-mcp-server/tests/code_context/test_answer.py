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

    # A terminal event too: a stream that ends after `context` alone leaves a
    # reader's answer pane waiting for an answer that will never come.
    assert [name for name, _ in events] == ["context", "error"]
    assert events[0][1]["status"] == "no_project"
    assert events[1][1]["message"] == events[0][1]["message"]
    assert events[1][1]["hint"] == events[0][1]["hint"]


def test_graph_failure_details_are_not_returned_over_json_or_sse(monkeypatch):
    async def build(*_a, **_k):
        raise cc.GraphUnavailable("engine failure at /private/secret.db")

    monkeypatch.setattr(cc, "build", build)
    monkeypatch.setattr(cc, "LocalBackend", lambda: object())

    json_payload = asyncio.run(
        cc.build_code_context(task="how", project="p", cwd=None, budget=12000)
    )
    stream_events = list(cc.stream_answer("how", "p", None, 12000))

    assert json_payload["message"] == "Code Context is unavailable."
    assert "secret.db" not in str(json_payload)
    assert stream_events[0][1]["message"] == "Code Context is unavailable."
    assert "secret.db" not in str(stream_events)


def test_no_model_still_delivers_the_context(composed, monkeypatch):
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: None)
    events = list(
        cc.stream_answer("how", None, None, 12000, include_graph=True, detail=3)
    )

    assert [name for name, _ in events] == ["context", "error"]
    assert events[0][1]["status"] == "success"


# --- a bracket can cite more than one symbol ---------------------------------
#
# Seen from a real model: "... old enough to be considered a crashed process
# [apply, _claim_is_stale]." Each name inside is its own citation.


def test_each_name_in_a_multi_name_bracket_is_a_citation(model):
    out = _json("apply claims first, then checks the row [apply, `claim_row`].", model)
    assert out["answer_status"] == "ok"
    assert [c["name"] for c in out["answer_citations"]] == ["apply", "claim_row"]


def test_an_invented_name_cannot_hide_in_a_multi_name_bracket(model):
    out = _json("apply claims first, then persists [apply; persist_all_rows].", model)
    assert out["answer_status"] == "unverified"
    assert out["answer_unresolved"] == ["persist_all_rows"]


# --- the stream gets the same one wider retry as `complete` ------------------


@pytest.fixture
def budgeted(monkeypatch):
    """A model whose replies, per attempt, are (text, finish_reason)."""
    attempts: list[int] = []
    replies: list[tuple[str, str]] = []

    def stream(*_a, max_tokens, finished=None, **_k):
        attempts.append(max_tokens)
        text, reason = replies[len(attempts) - 1]
        if finished is not None:
            finished["reason"] = reason
        yield from (text[i : i + 5] for i in range(0, len(text), 5))

    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "stub-model")
    monkeypatch.setattr(local_llm, "stream", stream)
    return attempts, replies


def _after_last_restart(events):
    names = [n for n, _ in events]
    start = len(names) - 1 - names[::-1].index("restart") if "restart" in names else 0
    return "".join(p["text"] for n, p in events[start:] if n == "delta")


def test_a_stream_cut_off_by_its_budget_is_retried_once_wider(composed, budgeted):
    attempts, replies = budgeted
    replies[:] = [("The `apply`", "length"), (GROUNDED, "stop")]
    events = list(cc.stream_answer("how", None, None, 12000))

    names = [n for n, _ in events]
    assert names.count("restart") == 1
    assert attempts == [
        cc._ANSWER_TOKENS,
        min(cc._ANSWER_TOKENS * 4, local_llm.MAX_RETRY_TOKENS),
    ]
    assert _after_last_restart(events) == GROUNDED
    done = _done(events)
    assert done["status"] == "ok" and done["truncated"] is False
    assert done["length"] == len(GROUNDED), "the verdict is on the retried text only"


def test_a_stream_that_finishes_normally_is_not_retried(composed, budgeted):
    attempts, replies = budgeted
    replies[:] = [(GROUNDED, "stop")]
    events = list(cc.stream_answer("how", None, None, 12000))

    assert "restart" not in [n for n, _ in events]
    assert len(attempts) == 1
    assert _done(events)["truncated"] is False


def test_a_second_cut_off_is_reported_not_retried_again(composed, budgeted):
    attempts, replies = budgeted
    replies[:] = [
        ("The `apply`", "length"),
        ("The `apply` claims [apply] then", "length"),
    ]
    events = list(cc.stream_answer("how", None, None, 12000))

    assert len(attempts) == 2
    assert _done(events)["truncated"] is True
