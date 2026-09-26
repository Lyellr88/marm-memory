import time

import pytest

from marm_mcp_server.core import runtime_flags
from marm_mcp_server.services import local_llm
from marm_mcp_server.services.analyst import ops, profile
from marm_mcp_server.services.analyst.profile import (
    MAX_OUTPUT_TOKENS,
    MAX_REASONING_TOKENS,
    PROFILES,
    resolve,
    selected_name,
)

_ENV = (
    "MARM_ANALYST_PROFILE",
    "MARM_ANALYST_TIME_BUDGET",
    "MARM_ANALYST_REASONING_TOKENS",
    "MARM_CODE_CONTEXT_ANSWER_TOKENS",
)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)
    saved = {}
    monkeypatch.setattr(runtime_flags, "get", lambda key: saved.get(key))
    return saved


def test_the_default_is_the_general_profile():
    assert selected_name() == ("general", "default")
    assert resolve().name == "general"


def test_the_environment_selects_a_profile(monkeypatch):
    monkeypatch.setenv("MARM_ANALYST_PROFILE", "small")
    assert selected_name() == ("small", "environment")


def test_a_saved_setting_wins_over_the_environment(monkeypatch, clean):
    monkeypatch.setenv("MARM_ANALYST_PROFILE", "small")
    clean[runtime_flags.ANALYST_PROFILE] = "large"
    assert selected_name() == ("large", "runtime")


def test_an_unknown_name_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("MARM_ANALYST_PROFILE", "huge")
    assert selected_name() == ("general", "default")


def test_the_profile_is_never_inferred_from_the_model(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("selection consulted the model")

    monkeypatch.setattr(local_llm, "available", boom)
    monkeypatch.setattr(local_llm, "status", boom)
    assert resolve().name == "general"


def test_the_caller_can_lower_the_evidence_cap_but_not_raise_it():
    assert resolve("small", context_chars=2000).context_chars == 2000
    assert resolve("small", context_chars=50000).context_chars == 6000


def test_settings_are_clamped_to_the_ceilings(monkeypatch):
    monkeypatch.setenv("MARM_ANALYST_REASONING_TOKENS", "999999")
    monkeypatch.setenv("MARM_CODE_CONTEXT_ANSWER_TOKENS", "999999")
    monkeypatch.setenv("MARM_ANALYST_TIME_BUDGET", "0")
    p = resolve("general")
    assert p.reasoning_tokens == MAX_REASONING_TOKENS
    assert p.output_tokens == MAX_OUTPUT_TOKENS
    assert p.time_s == profile.MIN_TIME_S


def test_the_answer_token_setting_only_sizes_the_free_form_answer(monkeypatch):
    """The structured profiles are sized to their schemas, not to prose."""
    monkeypatch.setenv("MARM_CODE_CONTEXT_ANSWER_TOKENS", "200")
    assert resolve("general").output_tokens == 200
    assert resolve("small").output_tokens == PROFILES["small"].output_tokens


def test_max_tokens_is_output_plus_reasoning():
    p = PROFILES["large"]
    assert p.max_tokens == p.output_tokens + p.reasoning_tokens
    assert p.to_public()["max_tokens"] == p.max_tokens


@pytest.mark.parametrize("name", ["small", "large"])
def test_a_profile_cap_covers_the_largest_reply_its_schemas_admit(name):
    """A cap below the schema's worst case cuts off valid output."""
    p = PROFILES[name]
    groups = [ops.OPERATIONS] if p.batch else [(op,) for op in ops.OPERATIONS]
    need = max(ops.worst_case_tokens(g) for g in groups)
    assert p.output_tokens >= need, (p.output_tokens, need)


def test_run_reports_cancel_and_deadline():
    from dataclasses import replace

    run = PROFILES["small"].start()
    assert run.stop_reason() is None
    run.cancel.set()
    assert run.stop_reason() == "cancelled"
    run2 = replace(PROFILES["small"], time_s=0.01).start()
    time.sleep(0.02)
    assert run2.expired() and run2.stop_reason() == "deadline"
