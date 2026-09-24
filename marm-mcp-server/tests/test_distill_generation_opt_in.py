"""Generation is opt-in on both transports, checked through the calls themselves.

A reachable model is stubbed and generation is made to fail loudly if it runs,
so a transport that defaulted `use_llm` to true would raise here.
"""

import asyncio
import importlib
import json

import pytest
from conftest import load_isolated_server, local_client
from mcp.shared.memory import create_connected_server_and_client_session

TEXT = "We decided the apply claim is taken before the write, never after."


@pytest.fixture
def generation_must_not_run(monkeypatch):
    local_llm = importlib.import_module("marm_mcp_server.services.local_llm")
    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "stub-model")

    def generate(*_a, **_k):
        raise AssertionError("generation ran without being asked for")

    # Patched after the server loads, where `propose` looks it up at call time.
    return lambda: monkeypatch.setattr(
        importlib.import_module("marm_mcp_server.services.distill"),
        "llm_extract",
        generate,
    )


def test_http_distill_selects_unless_asked(
    monkeypatch, tmp_path, generation_must_not_run
):
    client = local_client(load_isolated_server(monkeypatch, tmp_path).app)
    generation_must_not_run()

    body = client.post(
        "/marm_distill", json={"action": "propose", "text": TEXT, "session_name": "s"}
    ).json()

    assert body["status"] == "success", body
    assert body["mode"] == "selected"


def test_stdio_distill_selects_unless_asked(
    monkeypatch, tmp_path, generation_must_not_run
):
    from test_stdio_transport import _isolated_stdio

    stdio = _isolated_stdio(monkeypatch, tmp_path)
    endpoint = importlib.import_module("marm_mcp_server.endpoints.distill")
    monkeypatch.setattr(endpoint, "memory", stdio.memory)
    generation_must_not_run()

    async def run():
        async with create_connected_server_and_client_session(stdio.mcp) as client:
            return await client.call_tool(
                "marm_distill", {"action": "propose", "text": TEXT, "session_name": "s"}
            )

    payload = json.loads(asyncio.run(run()).content[0].text)

    assert payload["status"] == "success", payload
    assert payload["mode"] == "selected"
