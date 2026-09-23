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
    # `_get_at`, not `_get`: detection is parameterised by base URL so the
    # server scan can reuse it against every candidate port.
    monkeypatch.setattr(
        local_llm, "_get_at", lambda base, path, timeout=4.0: responses.get(path)
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


# --- finding the other servers on this machine ------------------------------


def test_the_scan_never_probes_marms_own_ports(monkeypatch):
    """MARM serves on 8001/8002, and asking yourself over HTTP from the loop
    that would answer deadlocks until the timeout -- the defect that made
    `/internal/runtime/settings` cost a full second. A scan that included them
    would reintroduce it once per sweep."""
    monkeypatch.setenv("SERVER_PORT", "8001")
    monkeypatch.setenv("MARM_CONSOLE_PORT", "8002")
    monkeypatch.setattr(
        local_llm,
        "KNOWN_PORTS",
        ((8001, "self"), (8002, "console"), (1234, "LM Studio")),
    )
    monkeypatch.setattr(local_llm, "_chosen_endpoint", lambda: None)
    monkeypatch.setattr(local_llm, "DEFAULT_URL", "http://127.0.0.1:1234")

    probed = []
    monkeypatch.setattr(
        local_llm, "_port_open", lambda port: (probed.append(port), False)[1]
    )

    result = local_llm.discover_servers(force=True)
    assert 8001 not in probed and 8002 not in probed
    assert probed == [1234]
    assert result["servers"] == []


def test_something_listening_that_is_not_an_llm_is_not_offered(monkeypatch):
    """Syncthing and a dozen other things live on these ports.

    Offering one as a candidate hands the reader an endpoint that cannot
    generate, and they find out only when an answer never arrives.
    """
    monkeypatch.setattr(local_llm, "KNOWN_PORTS", ((8384, "not an llm"),))
    monkeypatch.setattr(local_llm, "_chosen_endpoint", lambda: None)
    monkeypatch.setattr(local_llm, "DEFAULT_URL", "http://127.0.0.1:1234")
    monkeypatch.setattr(local_llm, "_port_open", lambda _port: True)
    monkeypatch.setattr(
        local_llm, "_identify", lambda base, timeout=4.0: {"runtime": None}
    )

    assert local_llm.discover_servers(force=True)["servers"] == []


def test_the_configured_endpoint_is_reported_even_when_dead(monkeypatch):
    """ "The one you configured is not answering" is the most useful thing
    this can say, so the configured port is always scanned.

    Patches `_chosen_endpoint` and not `endpoint`: `discover_servers` reads
    the former deliberately, to avoid the recursion through auto-selection.
    Patching `endpoint` left the call reading the real saved flag, so the
    test asserted against whichever server the developer last picked in the
    Console and passed only on a machine that had never picked one.
    """
    monkeypatch.setattr(local_llm, "KNOWN_PORTS", ())
    monkeypatch.setattr(local_llm, "_chosen_endpoint", lambda: "http://127.0.0.1:18080")
    monkeypatch.setattr(local_llm, "_port_open", lambda _port: False)

    result = local_llm.discover_servers(force=True)
    assert 18080 in result["scanned_ports"]
    assert result["configured_reachable"] is False


def test_a_found_server_reports_what_it_serves(monkeypatch):
    monkeypatch.setattr(local_llm, "KNOWN_PORTS", ((1234, "LM Studio"),))
    monkeypatch.setattr(local_llm, "_chosen_endpoint", lambda: None)
    monkeypatch.setattr(local_llm, "DEFAULT_URL", "http://127.0.0.1:1234")
    monkeypatch.setattr(local_llm, "_port_open", lambda _port: True)
    monkeypatch.setattr(
        local_llm,
        "_identify",
        lambda base, timeout=4.0: {
            "runtime": "LM Studio",
            "can_switch": True,
            "served": [{"id": "gpt-oss-20b"}, {"id": "qwen3-14b"}],
        },
    )
    (server,) = local_llm.discover_servers(force=True)["servers"]
    assert server["url"] == "http://127.0.0.1:1234"
    assert server["runtime"] == "LM Studio"
    assert server["can_switch"] is True
    assert server["models"] == ["gpt-oss-20b", "qwen3-14b"]


# --- saving an endpoint from the Console -------------------------------------


def _save_endpoint(monkeypatch, url, *, allow_remote):
    """Drive the Console's save path and return its `rejected` reason, if any."""
    import asyncio

    from marm_mcp_server.endpoints import system
    from marm_mcp_server.endpoints.system import RuntimeLlmRequest

    monkeypatch.setattr(local_llm, "ALLOW_REMOTE", allow_remote)
    saved: dict[str, str] = {}
    monkeypatch.setattr(
        system.runtime_flags, "set_", lambda key, value: saved.update({key: value})
    )
    monkeypatch.setattr(system.runtime_flags, "clear", lambda key: None)
    monkeypatch.setattr(system.runtime_flags, "set_bool", lambda key, value: None)
    monkeypatch.setattr(local_llm, "invalidate_settings_cache", lambda: None)
    monkeypatch.setattr(system, "_llm_status", lambda: {})

    result = asyncio.run(system.update_runtime_llm(RuntimeLlmRequest(endpoint=url)))
    # `rejected` rides inside the `llm` status payload, not at the top level.
    return result["llm"].get("rejected"), saved


def test_a_non_loopback_endpoint_is_refused_without_the_override(monkeypatch):
    """The default. Nothing but this machine, and the Console says why."""
    rejected, saved = _save_endpoint(
        monkeypatch, "http://10.0.0.5:1234", allow_remote=False
    )
    assert rejected and "loopback" in rejected
    assert not saved, "a refused endpoint must not reach the flag store"


def test_the_override_the_server_honours_is_honoured_here_too(monkeypatch):
    """`endpoint()` accepts a non-loopback URL once `MARM_LLM_ALLOW_REMOTE` is
    stated in full, and this path refused to SAVE that same URL -- so the
    Console could not configure an endpoint the server would then have used.
    The comment here claimed parity with `endpoint()`; it did not hold."""
    rejected, saved = _save_endpoint(
        monkeypatch, "http://10.0.0.5:1234", allow_remote=True
    )
    assert rejected is None, (
        f"the override was stated, but the save was refused: {rejected}"
    )
    assert saved, "the endpoint the server would use must actually be stored"


def test_a_malformed_endpoint_is_refused_with_a_reason_not_a_crash(monkeypatch):
    rejected, saved = _save_endpoint(monkeypatch, "http://[::1", allow_remote=True)
    assert rejected and "not a valid" in rejected
    assert not saved
