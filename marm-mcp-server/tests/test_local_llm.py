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


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    local_llm._probe_cache["at"] = 0.0
    local_llm._probe_cache["model"] = None
    yield
    local_llm._probe_cache["at"] = 0.0
    local_llm._probe_cache["model"] = None


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
    monkeypatch.setattr(local_llm, "DEFAULT_URL", url)
    monkeypatch.setattr(local_llm, "ALLOW_REMOTE", False)
    assert (local_llm.endpoint() is not None) is allowed


def test_a_remote_endpoint_needs_an_explicit_sentence_to_enable(monkeypatch):
    """The override is a sentence, not a truthy flag, so it cannot be set by
    accident or by a stray `=1` copied from another variable."""
    monkeypatch.setattr(local_llm, "DEFAULT_URL", "https://api.example.com")
    monkeypatch.setattr(local_llm, "ALLOW_REMOTE", True)
    assert local_llm.endpoint() == "https://api.example.com"


def test_an_unreachable_server_is_none_and_not_an_exception(monkeypatch):
    monkeypatch.setattr(local_llm, "DEFAULT_URL", "http://127.0.0.1:9")
    assert local_llm.available() is None
    assert local_llm.complete("s", "u") is None
    assert local_llm.complete_json("s", "u") is None


def test_a_negative_probe_is_cached(monkeypatch):
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
