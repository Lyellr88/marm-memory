"""Console Projects API contract tests with the MCP adapter stubbed."""

from fastapi.testclient import TestClient
from marm_mcp_server.console import app as console_app
from marm_mcp_server.console import mcp_client


def test_project_routes_map_graph_results(monkeypatch):
    projects = [
        {
            "name": "marm-memory",
            "root_path": "C:/repos/marm-memory",
            "nodes": 12,
            "edges": 18,
            "status": "ready",
        }
    ]

    def fake_post(operation: str, payload: dict, *, timeout: float = 10.0) -> dict:
        responses = {
            "internal/projects/index": {"job_id": "job-1"},
            "internal/projects/status": {
                "status": "success",
                "nodes": 12,
                "edges": 18,
            },
            "internal/projects/architecture": {
                "modules": [{"name": "core", "nodes": 4}],
                "schema": {
                    "node_labels": ["File", "Function"],
                    "edge_types": ["IMPORTS", "CALLS"],
                },
            },
            "internal/projects/search": {
                "results": [
                    {
                        "qualified_name": "marm.core.run",
                        "file_path": "core.py",
                        "line": 12,
                        "snippet": "def run():",
                        "kind": "function",
                    }
                ]
            },
            "internal/projects/trace": {
                "function": "marm.core.run",
                "callers": [{"qualified_name": "marm.main", "file_path": "main.py"}],
                "callees": [],
            },
            "internal/projects/impact": {
                "changed_files": ["core.py"],
                "affected_symbols": [
                    {
                        "qualified_name": "marm.core.run",
                        "file_path": "core.py",
                        "risk": "HIGH",
                    }
                ],
            },
            "internal/projects/delete": {"status": "success"},
        }
        return responses[operation]

    monkeypatch.setattr(console_app.mcp_client, "list_projects", lambda: projects)
    monkeypatch.setattr(console_app.mcp_client, "post", fake_post)
    monkeypatch.setattr(
        console_app.mcp_client,
        "get",
        lambda operation, *, timeout=10.0: {
            "job_id": "job-1",
            "status": "success",
            "phase": "complete",
        },
    )

    with TestClient(console_app.app) as client:
        assert client.get("/api/projects").json() == projects
        assert client.post(
            "/api/projects/index",
            json={"repo_path": "C:/repos/marm-memory", "mode": "fast"},
        ).json() == {"job_id": "job-1"}
        assert client.get("/api/projects/jobs/job-1").json()["status"] == "success"

        status = client.get("/api/projects/marm-memory/status")
        assert status.status_code == 200
        assert status.json()["status"] == "ready"

        architecture = client.get("/api/projects/marm-memory/architecture")
        assert architecture.status_code == 200
        assert architecture.json()["schema"]["edge_types"] == [
            {"name": "IMPORTS"},
            {"name": "CALLS"},
        ]

        search = client.post("/api/projects/marm-memory/search", json={"query": "run"})
        assert search.status_code == 200
        assert search.json()[0]["qualified_name"] == "marm.core.run"

        trace = client.post(
            "/api/projects/marm-memory/trace", json={"symbol": "marm.core.run"}
        )
        assert trace.status_code == 200
        assert trace.json()["steps"][0]["relation"] == "caller"

        impact = client.post(
            "/api/projects/marm-memory/impact", json={"since": "HEAD~1"}
        )
        assert impact.status_code == 200
        assert impact.json()["affected_symbols"][0]["risk"] == "high"

        deleted = client.request(
            "DELETE",
            "/api/projects/marm-memory",
            json={"name": "marm-memory", "confirm": True},
        )
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "success"


def test_project_request_error_preserves_mcp_status(monkeypatch):
    monkeypatch.setattr(
        console_app.mcp_client,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            mcp_client.McpRequestError(422, "Repository path is invalid.")
        ),
    )

    with TestClient(console_app.app) as client:
        response = client.post(
            "/api/projects/index", json={"repo_path": "bad", "mode": "fast"}
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Repository path is invalid."


def test_project_index_inline_error_status_maps_to_503(monkeypatch):
    """index_project must catch a 200-with-{"status": "error"} body too,
    not just a raised McpRequestError -- both are ways the graph backend
    reports a rejected index request."""
    monkeypatch.setattr(
        console_app.mcp_client,
        "post",
        lambda *args, **kwargs: {
            "status": "error",
            "message": "Repo already indexing.",
        },
    )

    with TestClient(console_app.app) as client:
        response = client.post(
            "/api/projects/index", json={"repo_path": "C:/repos/marm-memory"}
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Repo already indexing."


def test_get_projects_maps_request_error_instead_of_500(monkeypatch):
    monkeypatch.setattr(
        console_app.mcp_client,
        "list_projects",
        lambda: (_ for _ in ()).throw(
            mcp_client.McpRequestError(429, "Too many index requests.")
        ),
    )

    with TestClient(console_app.app) as client:
        response = client.get("/api/projects")

    assert response.status_code == 429
    assert response.json()["detail"] == "Too many index requests."
