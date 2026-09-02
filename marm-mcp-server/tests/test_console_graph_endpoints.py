import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marm_mcp_server.console import mcp_client
from marm_mcp_server.console.app import app
from marm_mcp_server.console.endpoints.projects import router as projects_router

ARCHITECTURE_0105 = {
    "project": "proj",
    "packages": [
        {"name": "apscheduler", "node_count": 1, "fan_in": 0, "fan_out": 0},
        {"name": "str", "node_count": 3, "fan_in": 0, "fan_out": 0},
        {"name": "print", "node_count": 1, "fan_in": 0, "fan_out": 0},
    ],
    "node_labels": [
        {"label": "Function", "count": 2028},
        {"label": "Variable", "count": 611},
    ],
    "edge_types": [
        {"type": "CALLS", "count": 6632},
        {"type": "DEFINES", "count": 5954},
    ],
    "schema": {
        "node_labels": [
            {"label": "Function", "count": 2028, "properties": ["name", "file_path"]},
        ],
        "edge_types": [{"type": "CALLS", "count": 6632, "properties": ["line"]}],
        "adr_present": False,
    },
}


@pytest.fixture
def architecture(monkeypatch):
    """Drive the endpoint with a chosen upstream payload."""

    def _run(payload: dict) -> dict:
        monkeypatch.setattr(mcp_client, "post", lambda *a, **k: payload)
        with TestClient(app) as client:
            response = client.get("/api/projects/proj/architecture")
        assert response.status_code == 200
        return response.json()

    return _run


def test_the_engines_packages_aspect_is_not_used_as_the_module_table(architecture):
    """`packages` looks like the module table's missing data source and is not.

    On a controlled two-package project it returns Python builtins (`str`, `list`,
    `print`) and module basenames, never the project's own packages, and its
    `fan_in`/`fan_out` are 0 on every row of every project measured. Mapping it here
    would replace an honest empty state with a table of builtins, so the table stays
    empty until a real source is proven.
    """
    body = architecture(ARCHITECTURE_0105)

    assert body["modules"] == []


def test_only_the_rendered_field_reaches_the_browser_as_a_string(architecture):
    """The defect itself. A dict rendered as a child is a crash, not a cosmetic issue.

    The response now carries the engine's count alongside the name, so the guard is
    no longer "every entry is a string": it is that the one field the UI renders as
    a child is a string, and that nothing nested (the schema fallback's `properties`
    array) rides along with it.
    """
    body = architecture(ARCHITECTURE_0105)

    assert body["schema"]["node_types"] == [
        {"name": "Function", "count": 2028},
        {"name": "Variable", "count": 611},
    ]
    assert body["schema"]["edge_types"] == [
        {"name": "CALLS", "count": 6632},
        {"name": "DEFINES", "count": 5954},
    ]
    for entry in body["schema"]["node_types"] + body["schema"]["edge_types"]:
        assert isinstance(entry["name"], str)
        assert isinstance(entry.get("count"), int)
        assert set(entry) <= {"name", "count"}


def test_the_schema_fallback_is_normalized_too(architecture):
    """The fallback was never a working path: get_graph_schema returns the same
    counted rows plus a properties array, so reaching it swapped one crash for a
    heavier one."""
    payload = {
        k: v
        for k, v in ARCHITECTURE_0105.items()
        if k not in ("node_labels", "edge_types")
    }
    body = architecture(payload)

    assert body["schema"]["node_types"] == [{"name": "Function", "count": 2028}]
    assert body["schema"]["edge_types"] == [{"name": "CALLS", "count": 6632}]


def test_an_engine_that_returns_plain_strings_passes_through(architecture):
    """Forward tolerance: the normalizer must not require the counted shape."""
    payload = {
        "packages": [],
        "node_labels": ["Function", "Class"],
        "edge_types": ["CALLS"],
    }
    body = architecture(payload)

    assert body["schema"]["node_types"] == [{"name": "Function"}, {"name": "Class"}]
    assert body["schema"]["edge_types"] == [{"name": "CALLS"}]


def test_an_empty_index_reports_an_empty_table(architecture):
    """The empty state has to stay reachable."""
    body = architecture({"project": "proj", "packages": [], "node_labels": []})

    assert body["modules"] == []
    assert body["schema"]["node_types"] == []


def test_a_modules_key_from_the_engine_would_still_be_used(architecture):
    """The key this endpoint has always read keeps working if an engine adds it."""
    payload = dict(ARCHITECTURE_0105)
    payload["modules"] = [{"name": "real.module", "node_count": 7}]
    body = architecture(payload)

    assert [m["name"] for m in body["modules"]] == ["real.module"]


def test_a_non_dict_schema_does_not_break_the_response(architecture):
    body = architecture({"packages": [], "schema": "unavailable"})

    assert body["schema"] == {"node_types": [], "edge_types": []}


def test_the_code_units_endpoint_passes_the_view_through_unchanged(monkeypatch):
    """The architecture endpoint above reshapes at the last hop because the shared
    router cannot change. This one owns its response end to end, so a second
    normalization here would be a place for the two shapes to drift apart."""
    view_response = {
        "state": "ready",
        "total": 238,
        "shown": 2,
        "fan_in_is_lower_bound": True,
        "code_units": [
            {"unit": "marm_mcp_server/core/memory.py", "fan_in": 33, "fan_out": 9},
            {"unit": "marm_mcp_server/server.py", "fan_in": 0, "fan_out": 24},
        ],
    }
    seen: dict = {}

    def fake_post(path, payload=None, **kwargs):
        seen["path"] = path
        seen["payload"] = payload
        return view_response

    monkeypatch.setattr(mcp_client, "post", fake_post)
    with TestClient(app) as client:
        response = client.get("/api/projects/proj/code-units")

    assert response.status_code == 200
    assert response.json() == view_response
    assert seen["path"] == "internal/projects/code-units"
    assert seen["payload"] == {"project": "proj"}


def test_the_code_units_endpoint_does_not_flatten_a_degraded_state(monkeypatch):
    """An unavailable state must reach the browser as unavailable. Turning it into
    an empty list is how the old module table said "no data" for its whole life."""
    unavailable = {
        "state": "unavailable",
        "reason": "contract_mismatch",
        "message": "query_graph did not run the query as written",
        "total": 0,
        "shown": 0,
        "code_units": [],
    }
    monkeypatch.setattr(mcp_client, "post", lambda *a, **k: unavailable)
    with TestClient(app) as client:
        body = client.get("/api/projects/proj/code-units").json()

    assert body["state"] == "unavailable"
    assert body["reason"] == "contract_mismatch"


def test_the_code_graph_endpoint_passes_the_bounded_snapshot_through(monkeypatch):
    snapshot = {
        "state": "ready",
        "total": {"code_units": 238, "import_edges": 950},
        "rendered": {"code_units": 80, "import_edges": 124},
        "truncated": True,
        "sample_reason": "bounded",
        "nodes": [
            {
                "id": "src/main.py",
                "label": "main.py",
                "path": "src/main.py",
                "kind": "file",
                "fan_in": 3,
                "fan_out": 4,
            }
        ],
        "edges": [],
    }
    monkeypatch.setattr(mcp_client, "post", lambda *a, **k: snapshot)

    with TestClient(app) as client:
        response = client.get("/api/projects/proj/graph")

    assert response.status_code == 200
    assert response.json() == snapshot


def test_normalization_did_not_leak_into_the_agent_facing_tool():
    """The counts are the useful part for a model, and `tool_router` is shared.
    Reducing labels there to satisfy one UI table would strip data from every
    agent, so the normalization belongs at the last hop before the browser."""
    from marm_graph.core import tool_router as R
    from marm_graph.core.models import GraphArchitectureRequest

    class FakeClient:
        def call_tool(self, name, args):
            if name == "get_architecture":
                return {k: v for k, v in ARCHITECTURE_0105.items() if k != "schema"}
            if name == "get_graph_schema":
                return ARCHITECTURE_0105["schema"]
            raise AssertionError(f"unexpected upstream call: {name}")

    result = R.do_architecture(FakeClient(), GraphArchitectureRequest(project="proj"))

    assert result["node_labels"][0] == {"label": "Function", "count": 2028}
    assert result["edge_types"][0] == {"type": "CALLS", "count": 6632}


def test_project_intelligence_routes_preserve_the_console_contract(monkeypatch):
    """These are Console-only routes; each must reach its internal adapter intact."""
    responses = {
        "internal/projects/coverage": {
            "signal": "best_effort",
            "metadata": {"generation_matches": True},
            "scopes": [{"total": 0, "entries": []}],
        },
        "internal/projects/graph": {
            "state": "ready",
            "total": {"code_units": 3, "import_edges": 5},
            "rendered": {"code_units": 3, "import_edges": 2},
            "truncated": True,
            "nodes": [],
            "edges": [],
        },
        "internal/projects/graph/neighborhood": {
            "state": "ready",
            "seed_id": "src/main.py",
            "total_imports": 1,
            "rendered_imports": 1,
            "truncated": False,
            "nodes": [],
            "edges": [],
        },
        "internal/projects/code-units/edges": {
            "state": "ready",
            "unit": "src/main.py",
            "imports": [{"path": "src/db.py", "count": 1}],
            "imported_by": [],
        },
        "internal/projects/adr": {"content": "# Decisions"},
        "internal/projects/adr/update": {"status": "success"},
        "internal/projects/runtime-traces": {"status": "success", "ingested": 1},
    }
    calls: list[tuple[str, dict]] = []

    def fake_post(path, payload=None, **kwargs):
        calls.append((path, payload))
        return responses[path]

    monkeypatch.setattr(mcp_client, "post", fake_post)
    contract_app = FastAPI()
    contract_app.include_router(projects_router)
    with TestClient(contract_app) as client:
        coverage = client.get("/api/projects/proj/coverage")
        graph = client.get("/api/projects/proj/graph")
        neighborhood = client.get(
            "/api/projects/proj/graph/neighborhood?node_id=src/main.py"
        )
        code_unit_edges = client.get(
            "/api/projects/proj/code-units/edges?unit=src/main.py"
        )
        adr = client.get("/api/projects/proj/adr")
        update = client.put("/api/projects/proj/adr", json={"content": "# Decisions"})
        traces = client.post(
            "/api/projects/proj/runtime-traces",
            json={"traces": [{"caller": "app.main", "callee": "db.save", "count": 3}]},
        )

    assert (
        coverage.status_code
        == graph.status_code
        == neighborhood.status_code
        == code_unit_edges.status_code
        == adr.status_code
        == 200
    )
    assert update.status_code == traces.status_code == 200
    assert coverage.json()["signal"] == "best_effort"
    assert graph.json()["rendered"] == {"code_units": 3, "import_edges": 2}
    assert neighborhood.json()["seed_id"] == "src/main.py"
    assert code_unit_edges.json()["imports"] == [{"path": "src/db.py", "count": 1}]
    assert adr.json()["content"] == "# Decisions"
    assert update.json()["status"] == traces.json()["status"] == "success"
    assert calls == [
        ("internal/projects/coverage", {"project": "proj"}),
        ("internal/projects/graph", {"project": "proj"}),
        (
            "internal/projects/graph/neighborhood",
            {"project": "proj", "node_id": "src/main.py"},
        ),
        (
            "internal/projects/code-units/edges",
            {"project": "proj", "unit": "src/main.py"},
        ),
        ("internal/projects/adr", {"project": "proj"}),
        ("internal/projects/adr/update", {"project": "proj", "content": "# Decisions"}),
        (
            "internal/projects/runtime-traces",
            {
                "project": "proj",
                "traces": [{"caller": "app.main", "callee": "db.save", "count": 3}],
            },
        ),
    ]
