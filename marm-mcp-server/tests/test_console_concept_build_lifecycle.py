import pytest
from fastapi.testclient import TestClient

from marm_mcp_server.console import mcp_client
from marm_mcp_server.console.app import app
from marm_mcp_server.console.endpoints import concepts
from marm_mcp_server.core.concept_db import ConceptDB


@pytest.fixture(autouse=True)
def clear_launching_concept_builds():
    with concepts._launching_concept_builds_lock:
        concepts._launching_concept_builds.clear()
    yield
    with concepts._launching_concept_builds_lock:
        concepts._launching_concept_builds.clear()


def _seed_build(db_path, *, run_id="run-1", status="cancelled", scope="project"):
    concept_db = ConceptDB(str(db_path))
    with concept_db.get_connection() as conn:
        concept_db.create_build_run(
            conn,
            run_id=run_id,
            scope_type=scope,
            scope_value="proj-a" if scope == "project" else None,
            created_at="2026-08-21T12:00:00+00:00",
        )
        concept_db.update_build_run(
            conn,
            run_id,
            status=status,
            error_code="cancelled_by_user" if status == "cancelled" else None,
        )
    concept_db.close()


def test_history_returns_persisted_cancelled_runs(monkeypatch, tmp_path):
    db_path = tmp_path / "marm_index.db"
    _seed_build(db_path)
    monkeypatch.setattr(concepts, "get_concept_db_path", lambda: db_path)

    with TestClient(app) as client:
        response = client.get("/api/concepts/builds")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "run-1"
    assert body[0]["status"] == "cancelled"
    assert body[0]["cancelled_at"] is None


def test_stop_proxies_the_private_server_control(monkeypatch):
    seen = {}

    def fake_post(path, payload, **_kwargs):
        seen["path"] = path
        seen["payload"] = payload
        return {
            "status": "cancellation_requested",
            "run_id": "run-1",
            "cancel_requested_at": "2026-08-21T12:00:00+00:00",
        }

    monkeypatch.setattr(mcp_client, "post", fake_post)
    with TestClient(app) as client:
        response = client.post("/api/concepts/builds/run-1/stop")

    assert response.status_code == 200
    assert response.json()["status"] == "cancellation_requested"
    assert seen == {"path": "internal/concepts/builds/run-1/stop", "payload": {}}


def test_retry_reuses_the_stored_scope(monkeypatch, tmp_path):
    db_path = tmp_path / "marm_index.db"
    _seed_build(db_path)
    monkeypatch.setattr(concepts, "get_concept_db_path", lambda: db_path)
    launched = {}

    class NoopThread:
        def __init__(self, *args, **kwargs):
            target = kwargs.get("target")
            if target is concepts._run_concept_build:
                launched["target"] = target
                launched["args"] = kwargs["args"]
                launched["daemon"] = kwargs["daemon"]

        def start(self):
            return None

    monkeypatch.setattr(concepts.threading, "Thread", NoopThread)
    with TestClient(app) as client:
        response = client.post("/api/concepts/builds/run-1/retry")

    assert response.status_code == 202
    assert response.json()["job_id"] != "run-1"
    assert launched["args"][1] == {"project": "proj-a", "search_all": False}


def test_delete_graph_requires_the_literal_confirmation(monkeypatch):
    with TestClient(app) as client:
        rejected = client.request(
            "DELETE", "/api/concepts/graph", json={"confirm": "DELETE"}
        )

    assert rejected.status_code == 422

    monkeypatch.setattr(
        mcp_client,
        "delete",
        lambda path, payload, **_kwargs: {
            "status": "reset",
            "backup_created": True,
            "schema_status": "rebuild_required",
        },
    )
    with TestClient(app) as client:
        response = client.request(
            "DELETE", "/api/concepts/graph", json={"confirm": "DELETE_GRAPH"}
        )

    assert response.status_code == 200
    assert response.json()["schema_status"] == "rebuild_required"


def test_terminal_builds_are_never_presented_as_stale_runs():
    job = {
        "status": "cancelled",
        "created_at": "2020-01-01T00:00:00+00:00",
    }

    assert concepts._stale_build_result(job) is job
