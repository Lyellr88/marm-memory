import importlib
import inspect

import pytest
from conftest import load_isolated_server, local_client
from fastapi.exceptions import ResponseValidationError
from pydantic import BaseModel


def _assert_input_schema_matches_model(
    schema: dict, request_model: type[BaseModel]
) -> None:
    fields = request_model.model_fields
    properties = schema["properties"]

    assert set(properties) == set(fields)
    assert schema.get("required", []) == [
        name for name, field in fields.items() if field.is_required()
    ]
    for name, field in fields.items():
        assert properties[name]["description"] == field.description


def test_marm_log_entry_response_payloads_are_unchanged(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    logging_endpoint = importlib.import_module("marm_mcp_server.endpoints.logging")
    client = local_client(server.app)
    formatted_entry = "payload parity"
    payloads = [
        {
            "status": "success",
            "message": f"📝 Log entry added: {formatted_entry}",
            "entry_id": "entry-123",
            "memory_id": None,
            "formatted_entry": formatted_entry,
        },
        {
            "status": "session_switched",
            "message": "📂 Session switched to 'schema-check-2026-08-27'",
            "session_name": "schema-check-2026-08-27",
        },
        {
            "status": "error",
            "message": "Session name cannot be empty.",
        },
    ]
    current = {"payload": payloads[0]}

    async def fake_create_log_entry(entry: str, session_name: str | None) -> dict:
        assert entry == "payload-parity"
        assert session_name == "schema-check"
        return current["payload"]

    monkeypatch.setattr(logging_endpoint, "create_log_entry", fake_create_log_entry)

    for payload in payloads:
        current["payload"] = payload
        response = client.post(
            "/marm_log_entry",
            json={"entry": "payload-parity", "session_name": "schema-check"},
        )
        body = response.json()

        assert response.status_code == 200
        assert body == payload


def test_marm_delete_response_payloads_are_unchanged(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    logging_endpoint = importlib.import_module("marm_mcp_server.endpoints.logging")
    client = local_client(server.app)
    cases = [
        (
            {"type": "log", "target": "entry-123", "session_name": "schema-check"},
            {
                "status": "success",
                "message": "🗑️ Deleted 2 items",
                "deleted_count": 2,
                "memories_deleted": 2,
            },
        ),
        (
            {"type": "notebook", "target": "release-rule"},
            {
                "status": "success",
                "message": "🗑️ Deleted notebook entry 'release-rule'",
                "deleted": True,
            },
        ),
        (
            {"type": "notebook", "target": "release-rule"},
            {
                "status": "not_found",
                "message": "Entry 'release-rule' not found",
                "deleted": False,
            },
        ),
        (
            {"type": "log", "target": "entry-123"},
            {
                "status": "error",
                "message": "Database error while deleting.",
            },
        ),
    ]
    current = {"payload": cases[0][1]}

    async def fake_delete(
        type: str,
        target: str,
        session_name: str | None,
        *,
        project: str | None = None,
        platform: str | None = None,
        scoped_notebook: bool = False,
    ) -> dict:
        return current["payload"]

    monkeypatch.setattr(logging_endpoint, "delete_log_or_notebook_entry", fake_delete)

    for request, payload in cases:
        current["payload"] = payload
        response = client.post("/marm_delete", json=request)

        assert response.status_code == 200
        assert response.json() == payload


def test_response_models_reject_undeclared_fields(monkeypatch, tmp_path):
    """Fail loudly instead of silently filtering a new service response field."""
    server = load_isolated_server(monkeypatch, tmp_path)
    logging_endpoint = importlib.import_module("marm_mcp_server.endpoints.logging")
    client = local_client(server.app)

    async def fake_create_log_entry(entry: str, session_name: str | None) -> dict:
        return {
            "status": "error",
            "message": "expected error",
            "undeclared": "must not disappear",
        }

    monkeypatch.setattr(logging_endpoint, "create_log_entry", fake_create_log_entry)

    with pytest.raises(ResponseValidationError):
        client.post("/marm_log_entry", json={"entry": "payload-parity"})


def test_response_models_preserve_mcp_tool_metadata(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    logging_endpoint = importlib.import_module("marm_mcp_server.endpoints.logging")
    tools = {tool.name: tool for tool in server.mcp.tools}

    assert len(server.mcp.tools) == len(server.MCP_TOOL_OPERATIONS) == 14
    assert set(tools) == set(server.MCP_TOOL_OPERATIONS)
    response_description = (
        "\n\n### Responses:\n\n"
        "**200**: Successful Response (Success Response)\n"
        "Content-Type: application/json"
    )
    expected_tools = {
        "marm_log_entry": (
            "Marm Log Entry",
            logging_endpoint.marm_log_entry,
            logging_endpoint.LogEntryRequest,
        ),
        "marm_delete": (
            "Marm Delete",
            logging_endpoint.marm_delete,
            logging_endpoint.DeleteRequest,
        ),
    }
    for name, (title, endpoint, request_model) in expected_tools.items():
        assert tools[name].description == (
            f"{title}\n\n{inspect.getdoc(endpoint)}{response_description}"
        )
        _assert_input_schema_matches_model(tools[name].inputSchema, request_model)

    log_properties = tools["marm_log_entry"].inputSchema["properties"]
    assert log_properties["entry"]["type"] == "string"
    assert {item["type"] for item in log_properties["session_name"]["anyOf"]} == {
        "string",
        "null",
    }

    delete_properties = tools["marm_delete"].inputSchema["properties"]
    assert delete_properties["type"]["enum"] == ["log", "notebook"]
    assert delete_properties["target"]["type"] == "string"
    for name in ("session_name", "project", "platform"):
        assert {item["type"] for item in delete_properties[name]["anyOf"]} == {
            "string",
            "null",
        }

    openapi = server.app.openapi()
    log_response_refs = {
        item["$ref"]
        for item in openapi["paths"]["/marm_log_entry"]["post"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["anyOf"]
    }
    assert log_response_refs == {
        "#/components/schemas/LogEntryCreatedResponse",
        "#/components/schemas/LogSessionSwitchedResponse",
        "#/components/schemas/LoggingErrorResponse",
    }
    delete_response_refs = {
        item["$ref"]
        for item in openapi["paths"]["/marm_delete"]["post"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["anyOf"]
    }
    assert delete_response_refs == {
        "#/components/schemas/LogDeleteResponse",
        "#/components/schemas/NotebookDeleteResponse",
        "#/components/schemas/LoggingErrorResponse",
    }
