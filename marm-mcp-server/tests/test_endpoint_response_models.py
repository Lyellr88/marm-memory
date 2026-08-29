import importlib
import inspect

from conftest import load_isolated_server, local_client
from fastapi.testclient import TestClient
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


def test_console_project_index_and_queued_job_payloads_are_unchanged(
    monkeypatch, tmp_path
):
    server = load_isolated_server(monkeypatch, tmp_path)
    graph_endpoint = importlib.import_module("marm_mcp_server.endpoints.graph")
    client = local_client(server.app)
    job_id = "job-payload-parity"
    created_at = "2026-08-28T10:00:00+00:00"

    class DormantThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(graph_endpoint.threading, "Thread", DormantThread)
    monkeypatch.setattr(graph_endpoint.uuid, "uuid4", lambda: job_id)
    monkeypatch.setattr(graph_endpoint, "_now_iso", lambda: created_at)

    expected_job = {
        "job_id": job_id,
        "status": "queued",
        "project": None,
        "phase": "queued",
        "error": None,
        "created_at": created_at,
        "started_at": None,
        "finished_at": None,
    }
    try:
        created = client.post(
            "/internal/projects/index",
            json={"repo_path": str(tmp_path), "mode": "fast"},
        )
        queued = client.get(f"/internal/projects/jobs/{job_id}")

        assert created.status_code == 202
        assert created.json() == {"job_id": job_id}
        assert queued.status_code == 200
        assert queued.json() == expected_job
    finally:
        graph_endpoint._project_jobs.clear()
        if graph_endpoint._project_job_lock.locked():
            graph_endpoint._project_job_lock.release()


def test_console_project_job_state_payloads_are_unchanged(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    graph_endpoint = importlib.import_module("marm_mcp_server.endpoints.graph")
    client = local_client(server.app)
    payloads = [
        {
            "job_id": "job-running-starting",
            "status": "running",
            "project": None,
            "phase": "starting",
            "error": None,
            "created_at": "2026-08-28T10:00:00+00:00",
            "started_at": "2026-08-28T10:00:01+00:00",
            "finished_at": None,
        },
        {
            "job_id": "job-running-indexing",
            "status": "running",
            "project": None,
            "phase": "indexing",
            "error": None,
            "created_at": "2026-08-28T10:00:00+00:00",
            "started_at": "2026-08-28T10:00:01+00:00",
            "finished_at": None,
        },
        {
            "job_id": "job-success",
            "status": "success",
            "project": "marm-memory",
            "phase": "complete",
            "error": None,
            "created_at": "2026-08-28T10:00:00+00:00",
            "started_at": "2026-08-28T10:00:01+00:00",
            "finished_at": "2026-08-28T10:00:02+00:00",
        },
        {
            "job_id": "job-success-before-finally",
            "status": "success",
            "project": None,
            "phase": "complete",
            "error": None,
            "created_at": "2026-08-28T10:00:00+00:00",
            "started_at": "2026-08-28T10:00:01+00:00",
            "finished_at": None,
        },
        {
            "job_id": "job-unavailable",
            "status": "error",
            "project": None,
            "phase": "unavailable",
            "error": "Graph backend unavailable.",
            "created_at": "2026-08-28T10:00:00+00:00",
            "started_at": "2026-08-28T10:00:01+00:00",
            "finished_at": "2026-08-28T10:00:02+00:00",
        },
        {
            "job_id": "job-busy-before-finally",
            "status": "error",
            "project": None,
            "phase": "busy",
            "error": "Graph index already in progress.",
            "created_at": "2026-08-28T10:00:00+00:00",
            "started_at": "2026-08-28T10:00:01+00:00",
            "finished_at": None,
        },
        {
            "job_id": "job-failed",
            "status": "error",
            "project": None,
            "phase": "failed",
            "error": "Repository indexing failed.",
            "created_at": "2026-08-28T10:00:00+00:00",
            "started_at": "2026-08-28T10:00:01+00:00",
            "finished_at": "2026-08-28T10:00:02+00:00",
        },
    ]

    try:
        for payload in payloads:
            stored = dict(payload)
            if payload["finished_at"] is not None:
                stored["_finished_timestamp"] = graph_endpoint.datetime.now(
                    graph_endpoint.timezone.utc
                ).timestamp()
            graph_endpoint._project_jobs.clear()
            graph_endpoint._project_jobs[payload["job_id"]] = stored

            response = client.get(f"/internal/projects/jobs/{payload['job_id']}")

            assert response.status_code == 200
            assert response.json() == payload
    finally:
        graph_endpoint._project_jobs.clear()


def test_console_project_job_rejects_undeclared_fields(monkeypatch, tmp_path):
    """Expose job schema drift as a client-facing 500 instead of filtering it."""
    server = load_isolated_server(monkeypatch, tmp_path)
    graph_endpoint = importlib.import_module("marm_mcp_server.endpoints.graph")
    client = TestClient(
        server.app,
        client=("127.0.0.1", 50000),
        raise_server_exceptions=False,
    )
    job_id = "job-with-undeclared-field"
    graph_endpoint._project_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "project": None,
        "phase": "queued",
        "error": None,
        "created_at": "2026-08-28T10:00:00+00:00",
        "started_at": None,
        "finished_at": None,
        "worker_detail": "must not disappear",
    }

    try:
        response = client.get(f"/internal/projects/jobs/{job_id}")
    finally:
        graph_endpoint._project_jobs.clear()

    assert response.status_code == 500


def test_response_models_reject_undeclared_fields(monkeypatch, tmp_path):
    """Fail loudly instead of silently filtering a new service response field."""
    server = load_isolated_server(monkeypatch, tmp_path)
    logging_endpoint = importlib.import_module("marm_mcp_server.endpoints.logging")
    client = TestClient(
        server.app,
        client=("127.0.0.1", 50000),
        raise_server_exceptions=False,
    )

    async def fake_create_log_entry(entry: str, session_name: str | None) -> dict:
        return {
            "status": "error",
            "message": "expected error",
            "undeclared": "must not disappear",
        }

    monkeypatch.setattr(logging_endpoint, "create_log_entry", fake_create_log_entry)

    response = client.post("/marm_log_entry", json={"entry": "payload-parity"})

    assert response.status_code == 500


def test_response_models_preserve_mcp_tool_metadata(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    logging_endpoint = importlib.import_module("marm_mcp_server.endpoints.logging")
    tools = {tool.name: tool for tool in server.mcp.tools}

    assert len(server.mcp.tools) == len(server.MCP_TOOL_OPERATIONS) == 14
    assert set(tools) == set(server.MCP_TOOL_OPERATIONS)
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
        assert title in tools[name].description
        assert inspect.getdoc(endpoint) in tools[name].description
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

    index_response_schema = openapi["paths"]["/internal/projects/index"]["post"][
        "responses"
    ]["202"]["content"]["application/json"]["schema"]
    assert index_response_schema == {
        "$ref": "#/components/schemas/ConsoleProjectIndexResponse"
    }
    job_response_refs = {
        item["$ref"]
        for item in openapi["paths"]["/internal/projects/jobs/{job_id}"]["get"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]["anyOf"]
    }
    assert job_response_refs == {
        "#/components/schemas/ConsoleProjectJobQueuedResponse",
        "#/components/schemas/ConsoleProjectJobRunningResponse",
        "#/components/schemas/ConsoleProjectJobSuccessResponse",
        "#/components/schemas/ConsoleProjectJobErrorResponse",
    }
