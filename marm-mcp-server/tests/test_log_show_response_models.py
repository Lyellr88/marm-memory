import importlib
import inspect
import sqlite3
from copy import deepcopy

import pytest
from conftest import load_isolated_server, local_client
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_mcp import FastApiMCP

_LOG_ROWS = [
    (
        "entry-new",
        "release-notes",
        "2026-08-28",
        "schema",
        'Keep Unicode 日志, "quotes", and\nnewlines.',
        '2026-08-28-schema-Keep Unicode 日志, "quotes", and\nnewlines.',
    ),
    ("entry-other", "other-session", "2026-08-29", "general", "other", "other"),
    ("entry-old", "release-notes", "2026-08-27", "", "", ""),
]


@pytest.fixture
def log_show_server(monkeypatch, tmp_path):
    return load_isolated_server(monkeypatch, tmp_path)


def _untyped_log_show_app():
    logging_endpoint = importlib.import_module("marm_mcp_server.endpoints.logging")
    app = FastAPI()
    # Exercise the same service with the route's pre-conversion serialization.
    app.add_api_route(
        "/marm_log_show",
        logging_endpoint.marm_log_show,
        methods=["GET"],
        operation_id="marm_log_show",
        response_model=dict,
    )
    return app


def _insert_log_rows(server, rows):
    with server.memory.get_connection() as conn:
        conn.executemany(
            "INSERT INTO log_entries "
            "(id, session_name, entry_date, topic, summary, full_entry) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()


@pytest.mark.parametrize("populated", [False, True], ids=["empty", "populated"])
@pytest.mark.parametrize(
    "session_name", [None, "", "release-notes", "other-session", "missing-session"]
)
def test_log_show_real_payloads_are_unchanged(log_show_server, populated, session_name):
    rows = _LOG_ROWS if populated else []
    _insert_log_rows(log_show_server, rows)
    params = {} if session_name is None else {"session_name": session_name}
    if session_name:
        entries = [
            {
                "id": row[0],
                "entry_date": row[2],
                "topic": row[3],
                "summary": row[4],
                "full_entry": row[5],
            }
            for row in sorted(rows, key=lambda row: row[2], reverse=True)
            if row[1] == session_name
        ]
        expected = {
            "status": "success",
            "session_name": session_name,
            "entries": entries,
            "total_entries": len(entries),
        }
    else:
        sessions = [
            {
                "session_name": name,
                "entry_count": sum(row[1] == name for row in rows),
            }
            for name in sorted({row[1] for row in rows})
        ]
        expected = {
            "status": "success",
            "sessions": sessions,
            "total_sessions": len(sessions),
        }

    before = local_client(_untyped_log_show_app()).get("/marm_log_show", params=params)
    after = local_client(log_show_server.app).get("/marm_log_show", params=params)

    assert before.status_code == after.status_code == 200
    assert after.json() == before.json() == expected


def test_log_show_large_entry_is_not_truncated(log_show_server):
    content = "日志\n" * 160_000
    _insert_log_rows(
        log_show_server,
        [("large-entry", "large-session", "2026-08-28", "general", content, content)],
    )
    params = {"session_name": "large-session"}

    before = local_client(_untyped_log_show_app()).get("/marm_log_show", params=params)
    after = local_client(log_show_server.app).get("/marm_log_show", params=params)

    assert before.status_code == after.status_code == 200
    assert len(after.content) > 1024 * 1024
    assert after.json() == before.json()
    assert after.json()["entries"][0]["full_entry"] == content


@pytest.mark.parametrize("session_name", [None, "release-notes"])
@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (sqlite3.OperationalError, "Database error while showing logs."),
        (RuntimeError, "Log show failed."),
    ],
)
def test_log_show_service_errors_are_unchanged(
    log_show_server, monkeypatch, session_name, error_type, message
):
    def fail_connection():
        raise error_type("private/database/path.sqlite")

    monkeypatch.setattr(log_show_server.memory, "get_connection", fail_connection)
    params = {} if session_name is None else {"session_name": session_name}

    before = local_client(_untyped_log_show_app()).get("/marm_log_show", params=params)
    after = local_client(log_show_server.app).get("/marm_log_show", params=params)

    assert before.status_code == after.status_code == 200
    assert after.json() == before.json() == {"status": "error", "message": message}


@pytest.mark.parametrize("shape", ["sessions", "entries", "error"])
def test_log_show_rejects_response_drift(log_show_server, monkeypatch, shape):
    logging_endpoint = importlib.import_module("marm_mcp_server.endpoints.logging")
    payloads = {
        "sessions": {
            "status": "success",
            "sessions": [{"session_name": "release-notes", "entry_count": 1}],
            "total_sessions": 1,
        },
        "entries": {
            "status": "success",
            "session_name": "release-notes",
            "entries": [
                {
                    "id": "entry-new",
                    "entry_date": "2026-08-28",
                    "topic": "schema",
                    "summary": "parity",
                    "full_entry": "parity",
                }
            ],
            "total_entries": 1,
        },
        "error": {"status": "error", "message": "Log show failed."},
    }
    payload = payloads[shape]
    invalid_payloads = [
        {**payload, "undeclared": "must not disappear"},
        {**payload, "status": "unknown"},
    ]
    for field in payload:
        missing = deepcopy(payload)
        del missing[field]
        invalid_payloads.append(missing)

    if shape != "error":
        nested_extra = deepcopy(payload)
        nested_extra[shape][0]["undeclared"] = "must not disappear"
        invalid_payloads.append(nested_extra)
        for field in payload[shape][0]:
            missing = deepcopy(payload)
            del missing[shape][0][field]
            invalid_payloads.append(missing)
        invalid_type = deepcopy(payload)
        field = "entry_count" if shape == "sessions" else "full_entry"
        invalid_type[shape][0][field] = {"unexpected": "object"}
        invalid_payloads.append(invalid_type)
        invalid_payloads.append({**payloads["sessions"], **payloads["entries"]})

    current = {"payload": payload}

    async def fake_list_log_entries(session_name):
        return current["payload"]

    monkeypatch.setattr(logging_endpoint, "list_log_entries", fake_list_log_entries)
    client = TestClient(
        log_show_server.app,
        client=("127.0.0.1", 50000),
        raise_server_exceptions=False,
    )
    assert client.get("/marm_log_show").json() == payload
    for invalid in invalid_payloads:
        current["payload"] = invalid
        response = client.get("/marm_log_show")
        assert response.status_code == 500, invalid


def test_log_show_preserves_mcp_metadata(log_show_server):
    logging_endpoint = importlib.import_module("marm_mcp_server.endpoints.logging")
    baseline = FastApiMCP(
        _untyped_log_show_app(), include_operations=["marm_log_show"]
    ).tools[0]
    tools = {tool.name: tool for tool in log_show_server.mcp.tools}
    actual = tools["marm_log_show"]

    assert len(tools) == len(log_show_server.mcp.tools) == 16
    assert set(tools) == set(log_show_server.MCP_TOOL_OPERATIONS)
    # Comparing two generated descriptions avoids pinning the adapter's renderer.
    assert actual.description == baseline.description
    assert "Marm Log Show" in actual.description
    assert inspect.getdoc(logging_endpoint.marm_log_show) in actual.description
    assert actual.inputSchema == baseline.inputSchema
    assert set(actual.inputSchema["properties"]) == {"session_name"}
    assert actual.inputSchema.get("required", []) == []
    session_schema = actual.inputSchema["properties"]["session_name"]
    assert {item["type"] for item in session_schema["anyOf"]} == {"string", "null"}


def test_log_show_openapi_describes_both_shapes(log_show_server):
    openapi = log_show_server.app.openapi()
    schema = openapi["paths"]["/marm_log_show"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert {item["$ref"] for item in schema["anyOf"]} == {
        "#/components/schemas/LogSessionsResponse",
        "#/components/schemas/LogEntriesResponse",
        "#/components/schemas/LoggingErrorResponse",
    }
    expected_fields = {
        "LogSessionsResponse": {"status", "sessions", "total_sessions"},
        "LogEntriesResponse": {"status", "session_name", "entries", "total_entries"},
        "LogSessionSummary": {"session_name", "entry_count"},
        "LogEntryDetails": {"id", "entry_date", "topic", "summary", "full_entry"},
        "LoggingErrorResponse": {"status", "message"},
    }
    schemas = openapi["components"]["schemas"]
    for name, fields in expected_fields.items():
        assert set(schemas[name]["properties"]) == fields
        assert set(schemas[name]["required"]) == fields
        assert schemas[name]["additionalProperties"] is False
    for name in ("LogSessionsResponse", "LogEntriesResponse"):
        assert schemas[name]["properties"]["status"]["const"] == "success"
    assert schemas["LogSessionsResponse"]["properties"]["sessions"]["items"] == {
        "$ref": "#/components/schemas/LogSessionSummary"
    }
    assert schemas["LogEntriesResponse"]["properties"]["entries"]["items"] == {
        "$ref": "#/components/schemas/LogEntryDetails"
    }
