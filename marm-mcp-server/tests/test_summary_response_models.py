import importlib
import inspect
from datetime import datetime, timezone

import pytest
from conftest import load_isolated_server, local_client
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_mcp import FastApiMCP

_LOG_ROWS = [
    (
        "entry-b",
        "release-notes",
        "2026-10-05",
        "decision",
        'Keep café, "quotes", and\nnewlines.',
    ),
    ("entry-a", "release-notes", "2026-10-05", "context", "x" * 205),
    ("entry-start", "release-notes", "2026-10-04", "session_start", "Release work"),
    ("entry-old", "release-notes", "2026-10-03", "", ""),
    ("entry-other", "other-session", "2026-10-06", "general", "Other session"),
]
_SUMMARY_BODY = (
    '**2026-10-05** [decision]: Keep café, "quotes", and\nnewlines.\n'
    "**2026-10-05** [context]: " + "x" * 197 + "...\n"
    "\n## Session: Release work\n"
    "**2026-10-03** []: "
)
_TRUNCATION_FIELDS = {
    "_mcp_truncated": True,
    "_truncation_reason": "Summary limited to 1MB for MCP compliance",
}


@pytest.fixture
def summary_server(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    summary_service = importlib.import_module("marm_mcp_server.services.summary")

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = cls(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
            return fixed.replace(tzinfo=None) if tz is None else fixed.astimezone(tz)

    # The generated header must not change between the two HTTP requests.
    monkeypatch.setattr(summary_service, "datetime", FixedDateTime)
    monkeypatch.delenv("MARM_SUMMARY_CACHE_DISPOSABLE", raising=False)
    return server


def _untyped_summary_app():
    reasoning_endpoint = importlib.import_module("marm_mcp_server.endpoints.reasoning")
    app = FastAPI()
    app.add_api_route(
        "/marm_summary",
        reasoning_endpoint.marm_summary,
        methods=["GET"],
        operation_id="marm_summary",
        response_model=dict,
    )
    return app


def _insert_log_rows(server, rows):
    with server.memory.get_connection() as conn:
        conn.executemany(
            "INSERT INTO log_entries "
            "(id, session_name, entry_date, topic, summary, full_entry) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(*row, row[-1]) for row in rows],
        )


def _reset_summary_cache(server, session_name, cache):
    with server.memory.get_connection() as conn:
        conn.execute(
            "DELETE FROM session_summary_cache WHERE session_name = ?", (session_name,)
        )
        if cache is not None:
            conn.execute(
                "INSERT INTO session_summary_cache "
                "(session_name, summary_text, entry_count, dirty) VALUES (?, ?, ?, ?)",
                (session_name, *cache),
            )


def _assert_summary_parity(server, session_name, cache=None):
    responses = []
    for app in (_untyped_summary_app(), server.app):
        # The baseline request must not prime the cache for the converted route.
        _reset_summary_cache(server, session_name, cache)
        response = local_client(app).get(
            "/marm_summary", params={"session_name": session_name}
        )
        assert response.status_code == 200
        responses.append(response)
    assert responses[1].json() == responses[0].json()
    return responses[1]


def _success_payload(session_name, summary_body, entry_count):
    return {
        "status": "success",
        "session_name": session_name,
        "summary": (
            f"# MARM Session Summary: {session_name}\n"
            "Generated: 2026-10-06 12:00 UTC\n\n" + summary_body
        ),
        "entry_count": entry_count,
        "total_entries": entry_count,
    }


@pytest.mark.parametrize("cache_state", ["missing", "clean", "dirty", "wrong-count"])
@pytest.mark.parametrize("disposable", [False, True])
def test_summary_real_payloads_are_unchanged(
    summary_server, monkeypatch, cache_state, disposable
):
    _insert_log_rows(summary_server, _LOG_ROWS)
    monkeypatch.setenv("MARM_SUMMARY_CACHE_DISPOSABLE", "1" if disposable else "0")
    cache = None
    if cache_state != "missing":
        cache = (
            'Cached café with "quotes"\nand newlines.',
            3 if cache_state == "wrong-count" else 4,
            cache_state == "dirty",
        )
    expected_body = cache[0] if cache_state == "clean" else _SUMMARY_BODY

    response = _assert_summary_parity(summary_server, "release-notes", cache)

    assert response.json() == _success_payload("release-notes", expected_body, 4)
    with summary_server.memory.get_connection() as conn:
        cached = conn.execute(
            "SELECT summary_text, entry_count, dirty FROM session_summary_cache "
            "WHERE session_name = ?",
            ("release-notes",),
        ).fetchone()
    assert cached == (None if disposable else (expected_body, 4, 0))


@pytest.mark.parametrize("session_name", ["missing-session", ""])
def test_summary_empty_payload_is_unchanged(summary_server, session_name):
    _insert_log_rows(summary_server, _LOG_ROWS)

    response = _assert_summary_parity(summary_server, session_name)

    assert response.json() == {
        "status": "empty",
        "message": f"No entries found in session '{session_name}'",
    }


@pytest.mark.parametrize("failure", ["missing-table", "unexpected"])
def test_summary_service_errors_are_unchanged(summary_server, monkeypatch, failure):
    _insert_log_rows(summary_server, _LOG_ROWS)
    if failure == "missing-table":
        with summary_server.memory.get_connection() as conn:
            conn.execute("DROP TABLE session_summary_cache")
    else:

        def fail_connection():
            raise RuntimeError("private/database/path.sqlite")

        monkeypatch.setattr(summary_server.memory, "get_connection", fail_connection)

    params = {"session_name": "release-notes"}
    before = local_client(_untyped_summary_app()).get("/marm_summary", params=params)
    after = local_client(summary_server.app).get("/marm_summary", params=params)

    assert before.status_code == after.status_code == 200
    assert (
        after.json()
        == before.json()
        == {
            "status": "error",
            "message": "Error generating summary.",
        }
    )


@pytest.mark.parametrize("limit_delta", [-1, 0, 1])
def test_summary_size_boundary_is_unchanged(summary_server, monkeypatch, limit_delta):
    limiter = importlib.import_module(
        "marm_mcp_server.core.response_limiter"
    ).MCPResponseLimiter
    _insert_log_rows(summary_server, _LOG_ROWS)
    untruncated = _success_payload("release-notes", _SUMMARY_BODY, 4)
    limit = limiter.estimate_response_size(untruncated) + limit_delta
    monkeypatch.setattr(limiter, "CONTENT_LIMIT", limit)

    response = _assert_summary_parity(summary_server, "release-notes")

    body = response.json()
    assert limiter.estimate_response_size(body) <= limit
    assert len(response.content) <= limit
    if limit_delta >= 0:
        assert body == untruncated
    else:
        assert body == {**untruncated, "summary": body["summary"], **_TRUNCATION_FIELDS}
        assert untruncated["summary"].startswith(body["summary"])
        assert len(body["summary"]) < len(untruncated["summary"])


@pytest.mark.parametrize("cached", [False, True])
def test_summary_default_limit_preserves_truncated_payload(summary_server, cached):
    limiter = importlib.import_module(
        "marm_mcp_server.core.response_limiter"
    ).MCPResponseLimiter
    oversized = "é" * 550_000
    _insert_log_rows(
        summary_server,
        [
            ("keep", "large-session", "2026-10-05", "decision", "Retain this line"),
            ("large", "large-session", "2026-10-04", "session_start", oversized),
        ],
    )
    retained = "**2026-10-05** [decision]: Retain this line\n"
    full_body = retained + "\n## Session: " + oversized
    untruncated = _success_payload("large-session", full_body, 2)
    assert limiter.estimate_response_size(untruncated) > limiter.MAX_RESPONSE_SIZE

    response = _assert_summary_parity(
        summary_server, "large-session", (full_body, 2, False) if cached else None
    )

    assert response.json() == {
        **_success_payload("large-session", retained, 2),
        **_TRUNCATION_FIELDS,
    }
    assert limiter.estimate_response_size(response.json()) <= limiter.CONTENT_LIMIT
    assert len(response.content) <= limiter.CONTENT_LIMIT < limiter.MAX_RESPONSE_SIZE


def test_summary_prefix_truncation_is_unchanged(summary_server, monkeypatch):
    limiter = importlib.import_module(
        "marm_mcp_server.core.response_limiter"
    ).MCPResponseLimiter
    session_name = "é" * 100
    _insert_log_rows(
        summary_server, [("long-name", session_name, "2026-10-05", "general", "Entry")]
    )
    metadata = {
        **_success_payload(session_name, "", 1),
        "summary": "",
        **_TRUNCATION_FIELDS,
    }
    limit = limiter.estimate_response_size(metadata) + 31
    monkeypatch.setattr(limiter, "CONTENT_LIMIT", limit)

    response = _assert_summary_parity(summary_server, session_name)

    body = response.json()
    assert body == {**metadata, "summary": "# MARM Session Summary: " + "é" * 3}
    assert limiter.estimate_response_size(body) <= limit
    assert len(response.content) <= limit
    assert (
        limiter.estimate_response_size({**body, "summary": body["summary"] + "é"})
        > limit
    )


@pytest.mark.parametrize("shape", ["success", "truncated", "empty", "error"])
def test_summary_rejects_response_drift(summary_server, monkeypatch, shape):
    reasoning_endpoint = importlib.import_module("marm_mcp_server.endpoints.reasoning")
    success = _success_payload("release-notes", _SUMMARY_BODY, 4)
    payloads = {
        "success": success,
        "truncated": {**success, **_TRUNCATION_FIELDS},
        "empty": {
            "status": "empty",
            "message": "No entries found in session 'missing'",
        },
        "error": {"status": "error", "message": "Error generating summary."},
    }
    payload = payloads[shape]
    invalid_payloads = [
        {**payload, "undeclared": "must not disappear"},
        {**payload, "status": "unknown"},
        {**success, **payloads["empty"]},
    ]
    for field in payload:
        missing = payload.copy()
        del missing[field]
        invalid_payloads.extend([missing, {**payload, field: {}}])
    if shape == "truncated":
        invalid_payloads.append({**payload, "_mcp_truncated": False})
        invalid_payloads.append(
            {**success, "mcp_truncated": True, "truncation_reason": "Renamed"}
        )

    current = {"payload": payload}

    async def fake_generate_session_summary(session_name):
        return current["payload"]

    monkeypatch.setattr(
        reasoning_endpoint, "generate_session_summary", fake_generate_session_summary
    )
    client = TestClient(
        summary_server.app,
        client=("127.0.0.1", 50000),
        raise_server_exceptions=False,
    )
    params = {"session_name": "release-notes"}
    assert client.get("/marm_summary", params=params).json() == payload
    for invalid in invalid_payloads:
        current["payload"] = invalid
        response = client.get("/marm_summary", params=params)
        assert response.status_code == 500, invalid


def test_summary_requires_session_name(summary_server):
    before = local_client(_untyped_summary_app()).get("/marm_summary")
    after = local_client(summary_server.app).get("/marm_summary")

    assert before.status_code == after.status_code == 422
    assert after.json() == before.json()


def test_summary_preserves_mcp_metadata(summary_server):
    reasoning_endpoint = importlib.import_module("marm_mcp_server.endpoints.reasoning")
    baseline = FastApiMCP(
        _untyped_summary_app(), include_operations=["marm_summary"]
    ).tools[0]
    tools = {tool.name: tool for tool in summary_server.mcp.tools}
    actual = tools["marm_summary"]

    assert len(tools) == len(summary_server.mcp.tools) == 16
    assert set(tools) == set(summary_server.MCP_TOOL_OPERATIONS)
    assert actual.description == baseline.description
    assert "Marm Summary" in actual.description
    assert inspect.getdoc(reasoning_endpoint.marm_summary) in actual.description
    assert actual.inputSchema == baseline.inputSchema
    assert set(actual.inputSchema["properties"]) == {"session_name"}
    assert actual.inputSchema["required"] == ["session_name"]
    assert actual.inputSchema["properties"]["session_name"]["type"] == "string"


def test_summary_openapi_describes_all_shapes(summary_server):
    openapi = summary_server.app.openapi()
    schema = openapi["paths"]["/marm_summary"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert {item["$ref"] for item in schema["anyOf"]} == {
        "#/components/schemas/SummarySuccessResponse",
        "#/components/schemas/SummaryTruncatedResponse",
        "#/components/schemas/SummaryEmptyResponse",
        "#/components/schemas/SummaryErrorResponse",
    }
    success_fields = {
        "status",
        "session_name",
        "summary",
        "entry_count",
        "total_entries",
    }
    expected_fields = {
        "SummarySuccessResponse": success_fields,
        "SummaryTruncatedResponse": success_fields | set(_TRUNCATION_FIELDS),
        "SummaryEmptyResponse": {"status", "message"},
        "SummaryErrorResponse": {"status", "message"},
    }
    schemas = openapi["components"]["schemas"]
    for name, fields in expected_fields.items():
        assert set(schemas[name]["properties"]) == fields
        assert set(schemas[name]["required"]) == fields
        assert schemas[name]["additionalProperties"] is False
    for name in ("SummarySuccessResponse", "SummaryTruncatedResponse"):
        assert schemas[name]["properties"]["status"]["const"] == "success"
    assert schemas["SummaryEmptyResponse"]["properties"]["status"]["const"] == "empty"
    assert schemas["SummaryErrorResponse"]["properties"]["status"]["const"] == "error"
    assert (
        schemas["SummaryTruncatedResponse"]["properties"]["_mcp_truncated"]["const"]
        is True
    )
