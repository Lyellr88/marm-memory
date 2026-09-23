"""The Console's distill proxy must forward everything the page sends.

The payload model is the whole contract: Pydantic drops a field the model does
not declare, so a Console option missing here is silently ignored by the
server, with no error on either side.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marm_mcp_server.console import mcp_client
from marm_mcp_server.console.endpoints.distill import router


@pytest.fixture
def client(monkeypatch):
    forwarded: list[dict] = []

    def post(operation, payload=None, *, query=None, timeout=None):
        forwarded.append(payload or {})
        return {"status": "success", "proposals": [], "mode": "selected"}

    monkeypatch.setattr(mcp_client, "post", post)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client, forwarded


@pytest.mark.parametrize("use_llm", [True, False])
def test_the_generation_choice_reaches_the_server(client, use_llm):
    test_client, forwarded = client
    response = test_client.post(
        "/api/distill",
        json={
            "action": "propose",
            "text": "t",
            "session_name": "s",
            "use_llm": use_llm,
        },
    )
    assert response.status_code == 200
    assert forwarded[0]["use_llm"] is use_llm


def test_generation_stays_off_when_the_page_does_not_ask(client):
    test_client, forwarded = client
    test_client.post(
        "/api/distill", json={"action": "propose", "text": "t", "session_name": "s"}
    )
    assert forwarded[0]["use_llm"] is False


def test_every_server_option_has_a_console_field():
    """The generalisation of the defect: the Console model must not be missing
    any option the server's request model accepts."""
    from marm_mcp_server.console.models import DistillPayload
    from marm_mcp_server.endpoints.distill import DistillRequest

    missing = set(DistillRequest.model_fields) - set(DistillPayload.model_fields)
    assert not missing, f"Console drops these distill options: {sorted(missing)}"


def test_every_code_context_option_has_a_console_field():
    """The same defect as `use_llm`, on the other proxy: a server option the
    Console model does not declare is dropped before it is forwarded."""
    from marm_mcp_server.console.models import CodeContextPayload
    from marm_mcp_server.endpoints.code_context import CodeContextRequest

    missing = set(CodeContextRequest.model_fields) - set(
        CodeContextPayload.model_fields
    )
    assert not missing, f"Console drops these code-context options: {sorted(missing)}"
