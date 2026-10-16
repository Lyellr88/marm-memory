import importlib
import inspect
import sqlite3
from contextlib import asynccontextmanager, closing
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest
from conftest import load_isolated_server
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_mcp import FastApiMCP

_SESSION = "notebook-parity"
_TEXT = 'Keep café, "quotes", and\nnewlines.'
_MIRROR_TEXT = "Keep café, &quot;quotes&quot;, and\nnewlines."
_SECRET = "ghp_" + "a" * 36
_REDACTED = {"count": 1, "kinds": {"github-token": 1}}
_MEMORY_ID = "00000000-0000-4000-8000-000000000001"
_STAMP = "2026-10-13T12:00:00+00:00"


@pytest.fixture
def notebook_server(monkeypatch, tmp_path):
    monkeypatch.setenv("MARM_DOCS_DB_PATH", str(tmp_path / "docs.db"))
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(tmp_path / "concepts.db"))
    server = load_isolated_server(monkeypatch, tmp_path, write_queue_enabled=True)
    # Exercise the real queue without starting unrelated graph workers at startup.
    monkeypatch.setattr(server.app.router, "lifespan_context", _notebook_lifespan)
    service = importlib.import_module("marm_mcp_server.services.notebook")
    monkeypatch.setattr(service, "MARM_PROJECT", None)
    monkeypatch.setattr(service, "MARM_PLATFORM", None)
    memory_ops = importlib.import_module("marm_mcp_server.core.memory_ops")
    # Only the generated identifier is fixed; both requests perform real writes.
    monkeypatch.setattr(
        memory_ops, "uuid", SimpleNamespace(uuid4=lambda: UUID(_MEMORY_ID))
    )
    yield server
    if service._docs_db is not None:
        service._docs_db.connection_pool.close_all()
    server.memory.connection_pool.close_all()


@asynccontextmanager
async def _notebook_lifespan(app):
    memory = importlib.import_module("marm_mcp_server.core.memory").memory
    try:
        yield
    finally:
        await memory.stop_write_queue()


def _post_notebook(app, request_body):
    with TestClient(
        app, client=("127.0.0.1", 50000), raise_server_exceptions=False
    ) as client:
        return client.post("/marm_notebook", json=request_body)


def _untyped_notebook_app():
    endpoint = importlib.import_module("marm_mcp_server.endpoints.notebook")
    app = FastAPI(lifespan=_notebook_lifespan)
    app.add_api_route(
        "/marm_notebook",
        endpoint.marm_notebook,
        methods=["POST"],
        operation_id="marm_notebook",
        response_model=dict,
    )
    return app


def _seed_entry(server, name="rule", data=_TEXT, session=_SESSION, stamp=_STAMP):
    with server.memory.get_connection() as conn:
        conn.execute(
            "INSERT INTO notebook_entries "
            "(name, data, session_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, data, session, stamp, stamp),
        )


def _assert_notebook_parity(server, request, status_code=200):
    service = importlib.import_module("marm_mcp_server.services.notebook")
    docs = service._get_docs_db()
    active = deepcopy(server.memory.active_notebook_entries_by_session)
    responses = []
    with closing(sqlite3.connect(":memory:")) as memory_snapshot:
        with closing(sqlite3.connect(":memory:")) as docs_snapshot:
            with server.memory.get_connection() as conn:
                conn.backup(memory_snapshot)
            with docs.get_connection() as conn:
                conn.backup(docs_snapshot)
            for app in (_untyped_notebook_app(), server.app):
                # A baseline add/save must not turn the converted request into an update.
                with server.memory.get_connection() as conn:
                    memory_snapshot.backup(conn)
                with docs.get_connection() as conn:
                    docs_snapshot.backup(conn)
                server.memory.active_notebook_entries_by_session = deepcopy(active)
                response = _post_notebook(app, request)
                assert response.status_code == status_code, response.text
                responses.append(response)
    assert responses[1].json() == responses[0].json()
    return responses[1].json()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("redacted", [False, True])
def test_notebook_add_payload_is_unchanged(notebook_server, existing, redacted):
    if existing:
        _seed_entry(notebook_server, data="Previous content")
    data = f"{_TEXT} {_SECRET}" if redacted else _TEXT

    body = _assert_notebook_parity(
        notebook_server,
        {"action": "add", "name": " rule ", "data": data, "session_name": _SESSION},
    )

    assert body == {
        "status": "success",
        "message": "📓 Notebook entry 'rule' added",
        "name": "rule",
        **({"redacted": _REDACTED} if redacted else {}),
    }
    with notebook_server.memory.get_connection() as conn:
        rows = conn.execute(
            "SELECT name, data, session_name FROM notebook_entries"
        ).fetchall()
    assert rows == [
        ("rule", data.replace(_SECRET, "[redacted:github-token]"), _SESSION)
    ]


@pytest.mark.parametrize("names", ["missing", " second, missing, rule, second "])
def test_notebook_use_payload_is_unchanged(notebook_server, names):
    _seed_entry(notebook_server)
    _seed_entry(notebook_server, name="second", data="Second instruction")
    _seed_entry(notebook_server, name="missing", session="other-session")
    entries = (
        [
            {"name": "second", "data": "Second instruction"},
            {"name": "rule", "data": _TEXT},
            {"name": "second", "data": "Second instruction"},
        ]
        if names != "missing"
        else []
    )

    body = _assert_notebook_parity(
        notebook_server, {"action": "use", "names": names, "session_name": _SESSION}
    )

    assert body == {
        "status": "success",
        "message": f"🔧 Activated {len(entries)} notebook entries",
        "activated_entries": [entry["name"] for entry in entries],
        "entries": entries,
    }
    assert notebook_server.memory.get_active_notebook_entries(_SESSION) == entries


@pytest.mark.parametrize("populated", [False, True])
def test_notebook_show_payload_is_unchanged(notebook_server, populated):
    _seed_entry(notebook_server, session="other-session")
    entries = []
    if populated:
        for length in (99, 100, 101):
            stamp = f"2026-10-13T12:00:{length - 99:02d}+00:00"
            _seed_entry(
                notebook_server, name=str(length), data="é" * length, stamp=stamp
            )
            entries.insert(
                0,
                {
                    "name": str(length),
                    "preview": "é" * min(length, 100) + ("..." if length > 100 else ""),
                    "created_at": stamp,
                    "updated_at": stamp,
                },
            )
        # These columns are nullable in both the current schema and legacy migrations.
        _seed_entry(notebook_server, name="legacy", stamp=None)
        entries.append(
            {"name": "legacy", "preview": _TEXT, "created_at": None, "updated_at": None}
        )

    body = _assert_notebook_parity(
        notebook_server, {"action": "show", "session_name": _SESSION}
    )

    assert body == {
        "status": "success",
        "message": f"📚 Found {len(entries)} notebook entries",
        "entries": entries,
        "total_count": len(entries),
    }


@pytest.mark.parametrize("action", ["status", "clear"])
@pytest.mark.parametrize("populated", [False, True])
def test_notebook_active_payloads_are_unchanged(notebook_server, action, populated):
    _seed_entry(notebook_server)
    if populated:
        assert (
            _post_notebook(
                notebook_server.app,
                {"action": "use", "names": "rule", "session_name": _SESSION},
            ).status_code
            == 200
        )
    other_entries = [{"name": "other", "data": "Another session's instruction"}]
    notebook_server.memory.set_active_notebook_entries("other-session", other_entries)
    entries = [{"name": "rule", "data": _TEXT}] if populated else []

    body = _assert_notebook_parity(
        notebook_server, {"action": action, "session_name": f"  {_SESSION}  "}
    )

    if action == "status":
        assert body == {
            "status": "success",
            "message": f"📊 {len(entries)} active notebook entries",
            "active_entries": [entry["name"] for entry in entries],
            "entries": entries,
            "active_count": len(entries),
        }
    else:
        assert body == {
            "status": "success",
            "message": "🧹 Active notebook entries cleared",
            "active_count": 0,
        }
        assert notebook_server.memory.get_active_notebook_entries(_SESSION) == []
        with notebook_server.memory.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM notebook_entries").fetchone() == (
                1,
            )
    assert (
        notebook_server.memory.get_active_notebook_entries("other-session")
        == other_entries
    )


@pytest.mark.parametrize("source", ["inline", "scratch"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("redacted", [False, True])
def test_notebook_save_payload_is_unchanged(
    notebook_server, source, existing, redacted
):
    service = importlib.import_module("marm_mcp_server.services.notebook")
    if existing:
        initial = _post_notebook(
            _untyped_notebook_app(),
            {
                "action": "save",
                "name": "rule",
                "data": "Previous content",
                "session_name": _SESSION,
            },
        ).json()
        assert initial["mirror_status"] == "synced"
    data = f"{_TEXT} {_SECRET}" if redacted else _TEXT
    request = {"action": "save", "name": "rule", "session_name": _SESSION}
    if source == "inline":
        request["data"] = data
    else:
        _seed_entry(notebook_server, data=data)

    body = _assert_notebook_parity(notebook_server, request)

    verb = "updated" if existing else "saved"
    promoted = " (promoted from scratch)" if source == "scratch" else ""
    assert body == {
        "status": "success",
        "message": f"📄 Doc 'rule' {verb}{promoted}",
        "doc_id": 1,
        "memory_id": _MEMORY_ID,
        "mirror_status": "synced",
        **({"redacted": _REDACTED} if redacted else {}),
    }
    stored = data.replace(_SECRET, "[redacted:github-token]")
    mirror_content = (
        f"{_MIRROR_TEXT} [redacted:github-token]" if redacted else _MIRROR_TEXT
    )
    with service._get_docs_db().get_connection() as conn:
        assert conn.execute("SELECT id, content, memory_id FROM docs").fetchall() == [
            (1, stored, _MEMORY_ID)
        ]
    with notebook_server.memory.get_connection() as conn:
        assert conn.execute("SELECT id, content FROM memories").fetchall() == [
            (_MEMORY_ID, mirror_content)
        ]
        scratch = conn.execute("SELECT data FROM notebook_entries").fetchall()
    assert scratch == ([(data,)] if source == "scratch" else [])


@pytest.mark.parametrize("failure", ["mirror-write", "mirror-link"])
@pytest.mark.parametrize("existing", [False, True])
def test_notebook_pending_mirror_payload_is_unchanged(
    notebook_server, monkeypatch, failure, existing
):
    service = importlib.import_module("marm_mcp_server.services.notebook")
    if existing:
        initial = _post_notebook(
            _untyped_notebook_app(),
            {
                "action": "save",
                "name": "rule",
                "data": "Previous content",
                "session_name": _SESSION,
            },
        ).json()
        assert initial["mirror_status"] == "synced"

    async def fail_mirror(*args, **kwargs):
        raise RuntimeError("write queue unavailable")

    def fail_link(*args, **kwargs):
        raise sqlite3.OperationalError("docs database is locked")

    if failure == "mirror-write":
        monkeypatch.setattr(notebook_server.memory, "store_doc_mirror", fail_mirror)
    else:
        monkeypatch.setattr(service.DocsDB, "set_memory_id", fail_link)

    body = _assert_notebook_parity(
        notebook_server,
        {"action": "save", "name": "rule", "data": _TEXT, "session_name": _SESSION},
    )

    verb = "updated" if existing else "saved"
    assert body == {
        "status": "success",
        "message": f"📄 Doc 'rule' {verb}",
        "doc_id": 1,
        "memory_id": _MEMORY_ID if existing or failure == "mirror-link" else None,
        "mirror_status": "pending",
    }
    with service._get_docs_db().get_connection() as conn:
        assert conn.execute("SELECT content, memory_id FROM docs").fetchall() == [
            (_TEXT, _MEMORY_ID if existing else None)
        ]
    with notebook_server.memory.get_connection() as conn:
        mirrors = conn.execute("SELECT id, content FROM memories").fetchall()
    if failure == "mirror-link":
        assert mirrors == [(_MEMORY_ID, _MIRROR_TEXT)]
    else:
        assert mirrors == ([(_MEMORY_ID, "Previous content")] if existing else [])


@pytest.mark.parametrize(
    "request_body,message",
    [
        (
            {"action": "add", "data": _TEXT},
            "name and data are required for action='add'",
        ),
        (
            {"action": "add", "name": "rule"},
            "name and data are required for action='add'",
        ),
        ({"action": "use"}, "names is required for action='use'"),
        ({"action": "use", "names": " , , "}, "names is required for action='use'"),
        ({"action": "save"}, "name is required for action='save'"),
        (
            {"action": "save", "name": "missing"},
            "No scratch entry named 'missing' found to promote; pass data= to save new content directly",
        ),
        (
            {
                "action": "save",
                "name": "rule",
                "data": _TEXT,
                "session_name": "marm_system",
            },
            "session_name 'marm_system' is reserved and cannot be used for action='save'",
        ),
        (
            {"action": "show", "session_name": " "},
            "session_name must be a non-empty string",
        ),
        (
            {"action": "add", "name": _SECRET, "data": _TEXT},
            "That name contains a credential; choose a different name.",
        ),
        (
            {"action": "save", "name": "rule", "data": _TEXT, "project": _SECRET},
            "That project contains a credential; choose a different project.",
        ),
    ],
)
def test_notebook_business_errors_are_unchanged(notebook_server, request_body, message):
    assert _assert_notebook_parity(notebook_server, request_body) == {
        "status": "error",
        "message": message,
    }


@pytest.mark.parametrize("failure", ["database", "unexpected"])
def test_notebook_caught_exceptions_are_unchanged(
    notebook_server, monkeypatch, failure
):
    if failure == "database":
        with notebook_server.memory.get_connection() as conn:
            conn.execute("DROP TABLE notebook_entries")
    else:
        service = importlib.import_module("marm_mcp_server.services.notebook")

        async def fail_show(**kwargs):
            raise RuntimeError("private/database/path.sqlite")

        monkeypatch.setitem(service._ACTION_HANDLERS, "show", fail_show)

    assert _assert_notebook_parity(notebook_server, {"action": "show"}) == {
        "status": "error",
        "message": "Notebook operation failed.",
    }


@pytest.mark.parametrize(
    "request_body",
    [{}, {"action": "unknown"}, {"action": "show", "session_name": None}],
)
def test_notebook_request_validation_is_unchanged(notebook_server, request_body):
    _assert_notebook_parity(notebook_server, request_body, status_code=422)


def test_notebook_use_keeps_large_content_without_a_limiter(notebook_server):
    content = "é" * 550_000
    _seed_entry(notebook_server, data=content)

    body = _assert_notebook_parity(
        notebook_server, {"action": "use", "names": "rule", "session_name": _SESSION}
    )

    assert body == {
        "status": "success",
        "message": "🔧 Activated 1 notebook entries",
        "activated_entries": ["rule"],
        "entries": [{"name": "rule", "data": content}],
    }


@pytest.mark.parametrize(
    "shape",
    [
        "add",
        "use",
        "show",
        "status",
        "clear",
        "save",
        "error",
        "add-redacted",
        "save-redacted",
    ],
)
def test_notebook_rejects_response_drift(notebook_server, monkeypatch, shape):
    endpoint = importlib.import_module("marm_mcp_server.endpoints.notebook")
    _seed_entry(notebook_server)
    notebook_server.memory.set_active_notebook_entries(
        _SESSION, [{"name": "rule", "data": _TEXT}]
    )
    action = "save" if shape == "error" else shape.split("-")[0]
    request = {"action": action, "session_name": _SESSION}
    if shape != "error":
        request.update(
            name="rule", names="rule", data=_SECRET if "redacted" in shape else _TEXT
        )
    payload = _post_notebook(_untyped_notebook_app(), request).json()
    current = {"payload": payload}

    async def changed_dispatch(**kwargs):
        return current["payload"]

    monkeypatch.setattr(endpoint, "notebook_dispatch", changed_dispatch)
    valid = _post_notebook(notebook_server.app, request)
    assert valid.status_code == 200
    assert valid.json() == payload
    invalid = [
        {**payload, "undeclared": "must not disappear"},
        {**payload, "status": "unknown"},
    ]
    for field in payload:
        if field != "redacted":
            missing = {key: value for key, value in payload.items() if key != field}
            invalid.extend([missing, {**missing, "renamed": payload[field]}])
        invalid.append({**payload, field: {}})
    if "mirror_status" in payload:
        invalid.append({**payload, "mirror_status": "unknown"})
    for field in ("entries", "redacted"):
        if field not in payload:
            continue
        nested = payload[field][0] if field == "entries" else payload[field]
        variants = [{**nested, "undeclared": "must not disappear"}]
        variants.extend(
            {key: value for key, value in nested.items() if key != missing}
            for missing in nested
        )
        invalid.extend(
            {**payload, field: [variant] if field == "entries" else variant}
            for variant in variants
        )
    for changed in invalid:
        current["payload"] = changed
        response = _post_notebook(notebook_server.app, request)
        assert response.status_code == 500, changed


@pytest.mark.parametrize("action", ["add", "save"])
def test_notebook_response_drift_after_a_write_returns_500(
    notebook_server, monkeypatch, action
):
    endpoint = importlib.import_module("marm_mcp_server.endpoints.notebook")
    dispatch = endpoint.notebook_dispatch

    async def changed_dispatch(**kwargs):
        return {**await dispatch(**kwargs), "undeclared": "already committed"}

    monkeypatch.setattr(endpoint, "notebook_dispatch", changed_dispatch)
    response = _post_notebook(
        notebook_server.app,
        {
            "action": action,
            "name": "rule",
            "data": _TEXT,
            "session_name": _SESSION,
        },
    )

    # Response validation runs after the write; a 500 does not mean a rollback.
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    if action == "add":
        with notebook_server.memory.get_connection() as conn:
            assert conn.execute("SELECT data FROM notebook_entries").fetchall() == [
                (_TEXT,)
            ]
    else:
        service = importlib.import_module("marm_mcp_server.services.notebook")
        with service._get_docs_db().get_connection() as conn:
            assert conn.execute("SELECT content FROM docs").fetchall() == [(_TEXT,)]
        with notebook_server.memory.get_connection() as conn:
            assert conn.execute("SELECT content FROM memories").fetchall() == [
                (_MIRROR_TEXT,)
            ]


def test_notebook_preserves_mcp_metadata(notebook_server):
    endpoint = importlib.import_module("marm_mcp_server.endpoints.notebook")
    baseline = FastApiMCP(
        _untyped_notebook_app(), include_operations=["marm_notebook"]
    ).tools[0]
    tools = {tool.name: tool for tool in notebook_server.mcp.tools}
    actual = tools["marm_notebook"]

    assert len(tools) == len(notebook_server.mcp.tools) == 16
    assert set(tools) == set(notebook_server.MCP_TOOL_OPERATIONS)
    assert actual.description == baseline.description
    assert "Marm Notebook" in actual.description
    assert inspect.getdoc(endpoint.marm_notebook) in actual.description
    assert actual.inputSchema == baseline.inputSchema
    assert set(actual.inputSchema["properties"]) == {
        "action",
        "name",
        "data",
        "names",
        "session_name",
        "project",
        "platform",
    }
    assert actual.inputSchema["required"] == ["action"]
    assert actual.inputSchema["properties"]["action"]["enum"] == [
        "add",
        "use",
        "show",
        "status",
        "clear",
        "save",
    ]


def test_notebook_openapi_describes_all_shapes(notebook_server):
    openapi = notebook_server.app.openapi()
    schema = openapi["paths"]["/marm_notebook"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    common = {"status", "message"}
    fields = {
        "NotebookAddedResponse": common | {"name", "redacted"},
        "NotebookUsedResponse": common | {"activated_entries", "entries"},
        "NotebookShownResponse": common | {"entries", "total_count"},
        "NotebookStatusResponse": common
        | {"active_entries", "entries", "active_count"},
        "NotebookClearedResponse": common | {"active_count"},
        "NotebookSavedResponse": common
        | {"doc_id", "memory_id", "mirror_status", "redacted"},
        "NotebookErrorResponse": common,
    }
    assert {item["$ref"] for item in schema["anyOf"]} == {
        f"#/components/schemas/{name}" for name in fields
    }
    schemas = openapi["components"]["schemas"]
    for name in fields:
        assert schemas[name]["properties"]["status"]["const"] == (
            "error" if name == "NotebookErrorResponse" else "success"
        )
    fields.update(
        NotebookActiveEntry={"name", "data"},
        NotebookEntryPreview={"name", "preview", "created_at", "updated_at"},
        RedactionSummary={"count", "kinds"},
    )
    for name, properties in fields.items():
        assert set(schemas[name]["properties"]) == properties
        assert set(schemas[name]["required"]) == properties - {"redacted"}
        assert schemas[name]["additionalProperties"] is False
    for model, field in (
        ("NotebookSavedResponse", "memory_id"),
        ("NotebookEntryPreview", "created_at"),
        ("NotebookEntryPreview", "updated_at"),
    ):
        assert {
            item["type"] for item in schemas[model]["properties"][field]["anyOf"]
        } == {"string", "null"}
    assert schemas["NotebookSavedResponse"]["properties"]["mirror_status"]["enum"] == [
        "synced",
        "pending",
    ]
