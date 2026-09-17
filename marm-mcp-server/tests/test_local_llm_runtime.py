"""Identifying the runtime, and refusing to imply a switch it will not make."""

import pytest

from marm_mcp_server.services import local_llm


@pytest.fixture(autouse=True)
def _clean():
    local_llm.invalidate_settings_cache()
    yield
    local_llm.invalidate_settings_cache()


def _serve(monkeypatch, responses: dict):
    """Answer the diagnostic GETs like a given server would.

    A missing key is a 404, which is how the real discrimination works: every
    one of these servers answers `/v1/models` and they are told apart by which
    of the *other* paths they also serve.
    """
    monkeypatch.setattr(local_llm, "endpoint", lambda: "http://127.0.0.1:18080")
    monkeypatch.setattr(
        local_llm, "_get", lambda path, timeout=4.0: responses.get(path)
    )


def test_llama_cpp_is_identified_and_reported_as_unswitchable(monkeypatch):
    """The whole point of this module.

    Measured against the live server on 2026-09-17: a request naming
    `definitely-not-a-real-model` was answered by `qwen3.6-27b-mtp` with HTTP
    200 and no error. llama.cpp ignores the model parameter, so anything that
    offers a choice here is offering one that silently will not happen.
    """
    _serve(
        monkeypatch,
        {
            "/props": {
                "model_path": "/models/Qwen3.6-27B-IQ4_NL.gguf",
                "model_alias": "qwen3.6-27b-mtp",
                "default_generation_settings": {"n_ctx": 65536},
            }
        },
    )
    info = local_llm.runtime_info(force=True)
    assert info["runtime"] == "llama.cpp"
    assert info["can_switch"] is False
    assert info["model_path"] == "/models/Qwen3.6-27B-IQ4_NL.gguf"
    assert info["context_length"] == 65536
    assert "one model per process" in info["reason"]


def test_ollama_is_identified_and_can_switch(monkeypatch):
    _serve(
        monkeypatch,
        {
            "/api/tags": {"models": [{"name": "llama3.2:8b"}, {"name": "qwen3:14b"}]},
            "/api/version": {"version": "0.5.1"},
        },
    )
    info = local_llm.runtime_info(force=True)
    assert info["runtime"] == "Ollama"
    assert info["can_switch"] is True
    assert [s["id"] for s in info["served"]] == ["llama3.2:8b", "qwen3:14b"]


def test_lm_studio_is_identified_and_can_switch(monkeypatch):
    _serve(
        monkeypatch,
        {
            "/api/v0/models": {
                "data": [{"id": "gemma", "state": "loaded", "path": "/m"}]
            }
        },
    )
    info = local_llm.runtime_info(force=True)
    assert info["runtime"] == "LM Studio"
    assert info["can_switch"] is True


def test_a_plain_server_with_one_model_is_not_assumed_switchable(monkeypatch):
    """Absent evidence is not evidence. One listed model means one choice."""
    _serve(monkeypatch, {"/v1/models": {"data": [{"id": "only-one"}]}})
    info = local_llm.runtime_info(force=True)
    assert info["runtime"] == "OpenAI-compatible"
    assert info["can_switch"] is False
    assert "single model" in info["reason"]


def test_a_plain_server_listing_several_models_is_taken_at_its_word(monkeypatch):
    _serve(monkeypatch, {"/v1/models": {"data": [{"id": "a"}, {"id": "b"}]}})
    info = local_llm.runtime_info(force=True)
    assert info["can_switch"] is True
    assert info["reason"] is None


def test_a_preference_is_ignored_on_a_runtime_that_cannot_honour_it(monkeypatch):
    """A saved choice must not read back as though it were in force.

    Otherwise the Console shows the model someone picked months ago while a
    different one answers every question.
    """
    _serve(monkeypatch, {"/props": {"model_path": "/m.gguf"}})

    class _Flags:
        LLM_MODEL = "llm.model"

        @staticmethod
        def get(_key):
            return "some-other-model"

    monkeypatch.setattr(
        "marm_mcp_server.core.runtime_flags.get", staticmethod(_Flags.get)
    )
    assert local_llm.preferred_model() is None


def test_switching_off_reads_as_no_model_available(monkeypatch):
    """The switch reuses the state every caller already handles."""
    monkeypatch.setattr(local_llm, "enabled", lambda: False)
    assert local_llm.available(force=True) is None


def test_status_still_reports_the_model_while_switched_off(monkeypatch):
    """The pane you turn generation back on from has to say what it would use.

    "Off" must not also mean "unknown", or the reader is asked to re-enable
    something the page refuses to describe.
    """
    _serve(
        monkeypatch,
        {"/props": {"model_path": "/m.gguf", "model_alias": "qwen3.6-27b-mtp"}},
    )
    monkeypatch.setattr(local_llm, "enabled", lambda: False)
    status = local_llm.status()
    assert status["enabled"] is False
    assert status["available"] is False
    assert status["model_in_use"] is None
    assert status["model"] == "qwen3.6-27b-mtp"
    assert status["runtime"] == "llama.cpp"


# --- which on-disk models can actually be clicked ---------------------------


def test_a_disk_model_the_runtime_knows_is_selectable():
    """Ollama names a manifest exactly as it serves it, so this is a match."""
    from marm_mcp_server.endpoints.system import _served_id_for

    model = {"name": "llama3.2:8b", "path": "/home/u/.ollama/models/blobs/sha256-ab"}
    served = [{"id": "llama3.2:8b", "path": None}]
    assert _served_id_for(model, served) == "llama3.2:8b"


def test_an_lm_studio_file_matches_the_repo_its_runtime_serves():
    """The two sides name the same model differently.

    LM Studio serves `publisher/repo` while discovery reports the file
    underneath it, so an exact-match-only test would make every LM Studio row
    inert even though selecting it works.
    """
    from marm_mcp_server.endpoints.system import _served_id_for

    model = {
        "name": "unsloth/gpt-oss-20b-GGUF/gpt-oss-20b-Q4.gguf",
        "path": "/home/u/.lmstudio/models/unsloth/gpt-oss-20b-GGUF/gpt-oss-20b-Q4.gguf",
    }
    served = [{"id": "unsloth/gpt-oss-20b-GGUF", "path": None}]
    assert _served_id_for(model, served) == "unsloth/gpt-oss-20b-GGUF"


def test_a_disk_model_the_runtime_has_never_seen_is_not_selectable():
    """A file cannot be loaded by naming it if the runtime does not know it.

    This is the row that must stay inert and say why, rather than looking
    clickable and doing nothing.
    """
    from marm_mcp_server.endpoints.system import _served_id_for

    model = {"name": "org/repo/other.gguf", "path": "/models/other.gguf"}
    served = [{"id": "something-else", "path": None}]
    assert _served_id_for(model, served) is None


def test_a_path_reported_by_the_runtime_wins_over_a_name_guess():
    """Where a runtime reports a path, it is the reliable identity."""
    from marm_mcp_server.endpoints.system import _served_id_for

    model = {"name": "whatever-the-file-is-called.gguf", "path": "/models/m.gguf"}
    served = [{"id": "an-alias-sharing-no-words", "path": "/models/m.gguf"}]
    assert _served_id_for(model, served) == "an-alias-sharing-no-words"
