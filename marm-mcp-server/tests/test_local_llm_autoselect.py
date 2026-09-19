"""`endpoint()` must follow whichever local server is actually serving.

A fixed default is wrong on a workstation where the LLM server changes: the
deployment's documented endpoint (llama.cpp on 18080) was down for 22 hours
while LM Studio served on 1234, and MARM only kept generating because an
operator had pinned a runtime flag by hand. Auto-selection removes the hand
step -- and the preference order is deliberate, not alphabetical.
"""

import pytest

from marm_mcp_server.services import local_llm


def _server(port, runtime, models=1):
    return {
        "url": f"http://127.0.0.1:{port}",
        "port": port,
        "runtime": runtime,
        "model_count": models,
        "models": [f"model-{port}"] if models else [],
    }


@pytest.fixture(autouse=True)
def _no_saved_endpoint_or_cache(monkeypatch):
    monkeypatch.setattr(local_llm, "_saved_endpoint", lambda: None)
    local_llm._auto_cache.update({"at": 0.0, "value": None})
    yield
    local_llm._auto_cache.update({"at": 0.0, "value": None})


def _discovers(monkeypatch, servers):
    monkeypatch.setattr(
        local_llm, "discover_servers", lambda force=False: {"servers": servers}
    )


def test_the_only_server_running_is_the_one_used(monkeypatch):
    _discovers(monkeypatch, [_server(11434, "Ollama")])
    assert local_llm.endpoint() == "http://127.0.0.1:11434"


def test_lm_studio_is_used_when_it_is_the_only_one(monkeypatch):
    """Explicitly wanted: LM Studio is the fallback, not an exclusion."""
    _discovers(monkeypatch, [_server(1234, "LM Studio")])
    assert local_llm.endpoint() == "http://127.0.0.1:1234"


def test_a_purpose_run_server_wins_over_lm_studio(monkeypatch):
    """LM Studio is ranked last when something else is also serving.

    It is a desktop app that is frequently up with nothing loaded, and it is
    the runtime measured to reject `response_format=json_object` (FINDINGS 22),
    so when a dedicated server is also answering that one is the better pick.
    """
    _discovers(monkeypatch, [_server(1234, "LM Studio"), _server(11434, "Ollama")])
    assert local_llm.endpoint() == "http://127.0.0.1:11434"


def test_the_deployment_default_wins_when_it_is_up(monkeypatch):
    """`MARM_LLM_URL` (or 18080) stops being a blind default and becomes a
    preference: honoured when it answers, ignored when it does not."""
    _discovers(
        monkeypatch,
        [
            _server(11434, "Ollama"),
            _server(18080, "llama.cpp"),
            _server(1234, "LM Studio"),
        ],
    )
    assert local_llm.endpoint() == "http://127.0.0.1:18080"


def test_a_server_with_no_model_loaded_loses_to_one_with_a_model(monkeypatch):
    _discovers(
        monkeypatch,
        [_server(11434, "Ollama", models=0), _server(1234, "LM Studio", models=1)],
    )
    assert local_llm.endpoint() == "http://127.0.0.1:1234"


def test_nothing_serving_falls_back_to_the_default_rather_than_none(monkeypatch):
    """A dead default is still the right thing to report and probe: callers
    surface "the configured endpoint is down", which is more useful than a
    silent None, and every generation path already falls back."""
    _discovers(monkeypatch, [])
    assert local_llm.endpoint() == local_llm.DEFAULT_URL.rstrip("/")


def test_a_saved_endpoint_still_wins_over_discovery(monkeypatch):
    """The Console's explicit pick is an operator decision; auto-selection is
    only what happens when nobody has made one."""
    monkeypatch.setattr(local_llm, "_saved_endpoint", lambda: "http://127.0.0.1:5001")
    _discovers(monkeypatch, [_server(11434, "Ollama")])
    assert local_llm.endpoint() == "http://127.0.0.1:5001"


def test_discovery_is_not_run_on_every_call(monkeypatch):
    calls = {"n": 0}

    def counting(force=False):
        calls["n"] += 1
        return {"servers": [_server(11434, "Ollama")]}

    monkeypatch.setattr(local_llm, "discover_servers", counting)
    for _ in range(5):
        local_llm.endpoint()
    assert calls["n"] == 1, "auto-selection must be cached, not a scan per call"


def test_a_non_loopback_discovery_is_refused(monkeypatch):
    _discovers(
        monkeypatch,
        [
            {
                "url": "http://10.0.0.5:1234",
                "port": 1234,
                "runtime": "LM Studio",
                "model_count": 1,
            }
        ],
    )
    monkeypatch.setattr(local_llm, "ALLOW_REMOTE", False)
    assert local_llm.endpoint() == local_llm.DEFAULT_URL.rstrip("/")


def test_endpoint_source_names_the_rule_that_chose(monkeypatch):
    """A URL does not say how it was picked, and "discovery" means it can
    change by itself when a server starts or stops."""
    _discovers(monkeypatch, [_server(11434, "Ollama")])
    assert local_llm.endpoint_source() == "discovery"

    monkeypatch.setenv("MARM_LLM_URL", "http://127.0.0.1:8080")
    assert local_llm.endpoint_source() == "environment"

    monkeypatch.setattr(local_llm, "_saved_endpoint", lambda: "http://127.0.0.1:5001")
    assert local_llm.endpoint_source() == "flag"


def test_endpoint_source_is_default_when_nothing_answers(monkeypatch):
    _discovers(monkeypatch, [])
    assert local_llm.endpoint_source() == "default"


def test_discovery_does_not_recurse_through_auto_selection(monkeypatch):
    """`discover_servers()` includes the CONFIGURED endpoint in its list, and
    for a while it asked `endpoint()` for it -- which asks auto-selection, which
    asks `discover_servers()`. Measured at 1,170 ms per call against ~5 ms of
    real probing, with the RecursionError swallowed and invisible.
    """
    calls = {"n": 0}
    real = local_llm.discover_servers

    def counting(force=False):
        calls["n"] += 1
        if calls["n"] > 3:
            raise AssertionError("discover_servers re-entered itself")
        return real(force=force)

    monkeypatch.setattr(local_llm, "discover_servers", counting)
    monkeypatch.setattr(local_llm, "_port_open", lambda port: False)
    local_llm._servers_cache.update({"at": 0.0, "value": None})
    local_llm.discover_servers(force=True)
    assert calls["n"] == 1
