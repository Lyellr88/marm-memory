"""Tests for the optional local generation backend.

Nothing here contacts a model. What is asserted is the contract every caller
depends on: a failure is a `None`, and a non-loopback endpoint is refused.
"""

from __future__ import annotations

import pytest

from marm_mcp_server.services import local_llm


@pytest.fixture(autouse=True)
def _no_saved_endpoint(monkeypatch):
    """Isolate these from the durable endpoint override.

    `endpoint()` prefers the saved flag over `MARM_LLM_URL`, which is the whole
    point of the Console picker -- but it also means a value left in the real
    database silently wins over the URL these tests patch in, and the loopback
    assertions then pass or fail on the developer's own configuration.
    """
    monkeypatch.setattr(local_llm, "_saved_endpoint", lambda: None)
    # And not only the saved flag: `endpoint()` falls back to MARM_LLM_URL,
    # read from the environment at call time, so a developer who exports it
    # overrides the URL these tests patch in.
    monkeypatch.delenv("MARM_LLM_URL", raising=False)


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    # `endpoint` too: the cache is keyed by it, so a stale key is as good as
    # a stale value.
    local_llm._probe_cache.update({"at": 0.0, "model": None, "endpoint": None})
    yield
    local_llm._probe_cache.update({"at": 0.0, "model": None, "endpoint": None})


@pytest.fixture
def switch(monkeypatch):
    """Drive `enabled()` from a fake saved flag and a clean environment."""
    from marm_mcp_server.core import runtime_flags

    state = {"saved": None, "readable": True}

    def fake_get(key):
        if not state["readable"]:
            return None
        return state["saved"] if key == runtime_flags.LLM_ENABLED else None

    monkeypatch.setattr(runtime_flags, "get", fake_get)
    monkeypatch.delenv("MARM_LLM_ENABLED", raising=False)
    local_llm._enabled_cache.update({"at": -1.0, "value": False})
    yield state
    local_llm._enabled_cache.update({"at": -1.0, "value": False})


def test_generation_is_off_until_the_operator_enables_it(switch):
    """Finding a running model must not make generation part of a workflow."""
    assert local_llm.enabled() is False


@pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("0", False)])
def test_the_environment_can_enable_it(switch, monkeypatch, value, expected):
    monkeypatch.setenv("MARM_LLM_ENABLED", value)
    assert local_llm.enabled() is expected


@pytest.mark.parametrize(
    "saved,env,expected", [("true", "0", True), ("false", "1", False)]
)
def test_a_saved_choice_outranks_the_environment(
    switch, monkeypatch, saved, env, expected
):
    monkeypatch.setenv("MARM_LLM_ENABLED", env)
    switch["saved"] = saved
    assert local_llm.enabled() is expected


def test_an_unreadable_flag_falls_back_to_the_environment_not_to_on(
    switch, monkeypatch
):
    switch["readable"] = False
    assert local_llm.enabled() is False
    local_llm._enabled_cache.update({"at": -1.0})
    monkeypatch.setenv("MARM_LLM_ENABLED", "1")
    assert local_llm.enabled() is True


def test_switched_off_reads_as_no_model_without_probing(switch, monkeypatch):
    def probe(*_a, **_k):
        raise AssertionError("a disabled backend must not be probed")

    monkeypatch.setattr(local_llm, "endpoint", probe)
    assert local_llm.available() is None


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("http://127.0.0.1:18080", True),
        ("http://localhost:11434", True),
        ("http://[::1]:8080", True),
        ("http://192.168.1.50:8080", False),
        ("https://api.example.com/v1", False),
        ("http://model.internal:8080", False),
    ],
)
def test_only_loopback_endpoints_are_used(monkeypatch, url, allowed):
    """A misconfigured endpoint would ship transcripts off the box silently.

    That is the one failure with no local symptom, so it is refused rather than
    warned about.
    """
    monkeypatch.setenv("MARM_LLM_URL", url)
    monkeypatch.setattr(local_llm, "DEFAULT_URL", url)
    monkeypatch.setattr(local_llm, "ALLOW_REMOTE", False)
    assert (local_llm.endpoint() is not None) is allowed


def test_a_remote_endpoint_needs_an_explicit_sentence_to_enable(monkeypatch):
    """The override is a sentence, not a truthy flag, so it cannot be set by
    accident or by a stray `=1` copied from another variable."""
    monkeypatch.setenv("MARM_LLM_URL", "https://api.example.com")
    monkeypatch.setattr(local_llm, "DEFAULT_URL", "https://api.example.com")
    monkeypatch.setattr(local_llm, "ALLOW_REMOTE", True)
    assert local_llm.endpoint() == "https://api.example.com"


@pytest.fixture
def generation_on(monkeypatch):
    """Probe behaviour is only reachable once the operator has switched it on;
    without this, `available()` answers None before it probes anything, and a
    test of the probe passes without exercising it."""
    monkeypatch.setattr(local_llm, "enabled", lambda: True)


def test_an_unreachable_server_is_none_and_not_an_exception(monkeypatch, generation_on):
    monkeypatch.setenv("MARM_LLM_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(local_llm, "DEFAULT_URL", "http://127.0.0.1:9")
    assert local_llm.available() is None
    assert local_llm.complete("s", "u") is None
    assert local_llm.complete_json("s", "u") is None


def test_a_negative_probe_is_cached(monkeypatch, generation_on):
    """Otherwise every distil on a machine with no model pays a full timeout
    before falling back, turning a working feature into a slow one."""
    calls = []

    def fake_request(path, payload, timeout):
        calls.append(path)
        return None

    monkeypatch.setattr(local_llm, "_request", fake_request)
    assert local_llm.available() is None
    assert local_llm.available() is None
    assert len(calls) == 1, "the negative result was re-probed"


def test_a_cached_model_is_not_reused_after_the_endpoint_moves(
    monkeypatch, generation_on
):
    """The cached id belongs to the server that answered, not to the clock.

    Auto-selection rotates on a 30s TTL while the probe cache defaults to 60s,
    so an endpoint can move from A to B with A's model id still cached. The
    next completion then asks B for one of A's models, which either errors or
    quietly serves something else -- the silent case being the worse one.
    """
    served = {
        "http://127.0.0.1:1111": "model-on-a",
        "http://127.0.0.1:2222": "model-on-b",
    }
    current = {"base": "http://127.0.0.1:1111"}
    monkeypatch.setattr(local_llm, "endpoint", lambda: current["base"])
    monkeypatch.setattr(
        local_llm,
        "_request",
        lambda *a, **k: {"data": [{"id": served[current["base"]]}]},
    )

    assert local_llm.available() == "model-on-a"
    current["base"] = "http://127.0.0.1:2222"
    assert local_llm.available() == "model-on-b", (
        "the endpoint moved, so the model cached from the previous server "
        "must be a miss rather than a hit within the TTL"
    )


def test_status_reports_what_the_console_shows(monkeypatch):
    monkeypatch.setattr(local_llm, "DEFAULT_URL", "http://127.0.0.1:18080")
    monkeypatch.setattr(local_llm, "_request", lambda *a, **k: None)
    status = local_llm.status()
    assert status["configured"] is True
    assert status["available"] is False
    assert status["loopback_enforced"] is True


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('[{"a": 1}]', [{"a": 1}]),
        ('```json\n[{"a": 1}]\n```', [{"a": 1}]),
        ('Here you go:\n[{"a": 1}]\nHope that helps.', [{"a": 1}]),
        ('{"facts": []}', {"facts": []}),
        ("not json at all", None),
        ("", None),
    ],
)
def test_json_is_recovered_from_however_the_model_wrapped_it(raw, expected):
    """Models fence and preface JSON however they were tuned to. A reply that
    cannot be parsed is the same `None` as no model at all."""
    assert local_llm._first_json_value(raw) == expected


# --- talking to a server that is not llama.cpp ------------------------------


def test_json_object_is_retried_without_it_when_the_server_refuses(monkeypatch):
    """LM Studio returns HTTP 400 for `response_format: {"type":"json_object"}`.

    Measured against 0.3.x: *"'response_format.type' must be 'json_schema' or
    'text'"*. Every generated distillation silently fell back to sentence
    selection the moment MARM pointed at LM Studio instead of llama.cpp, and
    nothing said why. `json_object` is an optimisation -- callers parse
    defensively anyway -- so refusing it must not cost the feature.
    """
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "gpt-oss-20b")
    sent = []

    def fake_request(path, payload, timeout):
        # A snapshot: the retry pops `response_format` off the same dict, so
        # storing the reference would show both calls without it.
        sent.append(dict(payload))
        if "response_format" in payload:
            return None  # the 400
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(local_llm, "_request", fake_request)

    assert local_llm.complete("sys", "user", json_object=True) == "ok"
    assert len(sent) == 2, "the refusal must be retried without response_format"
    assert "response_format" in sent[0] and "response_format" not in sent[1]


def test_a_reasoning_model_that_never_reached_content_is_a_failure(monkeypatch):
    """Empty content is not an empty answer.

    gpt-oss and the R1 family emit chain of thought into a separate
    `reasoning` field and can spend the whole budget there, returning
    finish_reason="length" with content still "". Returning "" hands the
    caller a confident blank; None is the state every caller falls back from.
    """
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "gpt-oss-20b")
    monkeypatch.setattr(
        local_llm,
        "_request",
        lambda *a, **k: {
            "choices": [
                {
                    "message": {"content": "", "reasoning": "thinking at length..."},
                    "finish_reason": "length",
                }
            ]
        },
    )
    assert local_llm.complete("sys", "user") is None


def test_a_normal_empty_reply_is_also_a_failure_not_an_answer(monkeypatch):
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "m")
    monkeypatch.setattr(
        local_llm,
        "_request",
        lambda *a, **k: {
            "choices": [{"message": {"content": "  "}, "finish_reason": "stop"}]
        },
    )
    assert local_llm.complete("sys", "user") is None


class _FakeSSE:
    """Stands in for the HTTP response `stream()` iterates, line by line."""

    def __init__(self, chunks):
        import json

        self._lines = [f"data: {json.dumps(c)}\n".encode() for c in chunks]
        self._lines.append(b"data: [DONE]\n")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)


def _serve(monkeypatch, chunks):
    monkeypatch.setattr(local_llm, "endpoint", lambda: "http://127.0.0.1:1234")
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "m")
    monkeypatch.setattr(
        local_llm.urllib.request, "urlopen", lambda *a, **k: _FakeSSE(chunks)
    )


def test_stream_yields_content_and_reports_how_it_finished(monkeypatch):
    _serve(
        monkeypatch,
        [
            {"choices": [{"delta": {"reasoning_content": "thinking..."}}]},
            {"choices": [{"delta": {"content": "The `apply`"}}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
        ],
    )
    finished: dict = {}
    pieces = list(local_llm.stream("s", "u", finished=finished))
    assert pieces == ["The `apply`"], "reasoning is not answer text"
    assert finished["reason"] == "length"


def test_stream_reports_a_normal_stop(monkeypatch):
    _serve(
        monkeypatch,
        [
            {"choices": [{"delta": {"content": "done"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ],
    )
    finished: dict = {}
    assert list(local_llm.stream("s", "u", finished=finished)) == ["done"]
    assert finished["reason"] == "stop"


MALFORMED = ["http://[::1", "http://[::1:8080", "http://"]


@pytest.mark.parametrize("url", MALFORMED)
@pytest.mark.parametrize("allow_remote", [False, True])
def test_a_malformed_endpoint_is_none_not_an_exception(
    monkeypatch, generation_on, url, allow_remote
):
    """Every caller relies on a `None` to fall back to its non-generated path;
    an exception here fails Distill and Code Context outright. Unusable even
    with the remote override, because there is no host to talk to."""
    monkeypatch.setenv("MARM_LLM_URL", url)
    monkeypatch.setattr(local_llm, "DEFAULT_URL", url)
    monkeypatch.setattr(local_llm, "ALLOW_REMOTE", allow_remote)
    monkeypatch.setattr(local_llm, "_auto_endpoint", lambda: None)
    assert local_llm._is_loopback(url) is False
    assert local_llm.endpoint() is None
    assert local_llm.available() is None
    assert local_llm.status()["available"] is False
