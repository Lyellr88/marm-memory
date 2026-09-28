"""A model that spends its budget before answering gets one wider retry.

Measured 2026-09-18: `gemma-4-26b-a4b-qat` returned `finish_reason="length"`
with `content=""` for a 2,048-token distill budget, so every proposal fell back
to sentence selection and only a debug line said why. Auto-selection means the
model can change underneath the call, so the coping belongs here.
"""

import pytest

from marm_mcp_server.services import local_llm


@pytest.fixture(autouse=True)
def _a_model_is_available(monkeypatch):
    monkeypatch.setattr(local_llm, "available", lambda: "test-model")
    monkeypatch.setattr(local_llm, "endpoint", lambda: "http://127.0.0.1:1234")


def _reply(content, finish):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}]}


def test_an_empty_length_capped_reply_is_retried_once_with_more_room(monkeypatch):
    seen = []

    def fake(path, payload, timeout):
        seen.append(payload["max_tokens"])
        return _reply("", "length") if len(seen) == 1 else _reply("the answer", "stop")

    monkeypatch.setattr(local_llm, "_request", fake)
    assert local_llm.complete("s", "u", max_tokens=2048) == "the answer"
    assert seen == [2048, 8192], "one retry, quadrupled and capped"


def test_the_retry_does_not_recurse(monkeypatch):
    """A model that cannot answer in 4x its budget is not going to."""
    calls = {"n": 0}

    def always_length(path, payload, timeout):
        calls["n"] += 1
        return _reply("", "length")

    monkeypatch.setattr(local_llm, "_request", always_length)
    assert local_llm.complete("s", "u", max_tokens=512) is None
    assert calls["n"] == 2, "exactly one retry, never a cascade"


def test_a_normal_reply_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def ok(path, payload, timeout):
        calls["n"] += 1
        return _reply("done", "stop")

    monkeypatch.setattr(local_llm, "_request", ok)
    assert local_llm.complete("s", "u", max_tokens=256) == "done"
    assert calls["n"] == 1


def test_the_retry_is_capped_not_merely_multiplied(monkeypatch):
    seen = []

    def fake(path, payload, timeout):
        seen.append(payload["max_tokens"])
        return _reply("", "length")

    monkeypatch.setattr(local_llm, "_request", fake)
    monkeypatch.setattr(local_llm, "MAX_RETRY_TOKENS", 3000)
    local_llm.complete("s", "u", max_tokens=2048)
    assert seen == [2048, 3000], "the cap wins over 4x"


def test_no_retry_when_the_budget_is_already_at_the_cap(monkeypatch):
    calls = {"n": 0}

    def fake(path, payload, timeout):
        calls["n"] += 1
        return _reply("", "length")

    monkeypatch.setattr(local_llm, "_request", fake)
    monkeypatch.setattr(local_llm, "MAX_RETRY_TOKENS", 1024)
    assert local_llm.complete("s", "u", max_tokens=4096) is None
    assert calls["n"] == 1, "a retry that cannot widen is just a slow duplicate"
