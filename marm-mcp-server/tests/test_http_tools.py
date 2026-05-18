import importlib
from datetime import datetime, timezone

from conftest import load_isolated_server, local_client


def test_session_log_summary_and_delete_workflow_persists_real_rows(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    start = client.post("/marm_start", json={"session_name": "release-notes"})
    assert start.status_code == 200
    assert start.json()["marm_active"] is True

    log_session = client.post("/marm_log_session", json={"session_name": "release-notes"})
    assert log_session.status_code == 200

    entry = "2026-05-17-docker-stdio transport validated"
    created = client.post(
        "/marm_log_entry",
        json={"session_name": "release-notes", "entry": entry},
    )
    assert created.status_code == 200
    entry_id = created.json()["entry_id"]

    shown = client.get("/marm_log_show", params={"session_name": "release-notes"})
    assert shown.status_code == 200
    assert shown.json()["total_entries"] == 1
    assert shown.json()["entries"][0] == {
        "id": entry_id,
        "entry_date": "2026-05-17",
        "topic": "docker",
        "summary": "stdio transport validated",
        "full_entry": entry,
    }

    summary = client.get("/marm_summary", params={"session_name": "release-notes"})
    assert summary.status_code == 200
    assert summary.json()["status"] == "success"
    assert "stdio transport validated" in summary.json()["summary"]

    deleted = client.delete(
        "/marm_log_delete",
        params={"session_name": "release-notes", "target": entry_id},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted_count"] == 1
    assert client.get("/marm_log_show", params={"session_name": "release-notes"}).json()["total_entries"] == 0


def test_malformed_log_entry_is_stored_as_general_without_losing_original_text(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    raw_entry = "decision without structured date still matters"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    created = client.post(
        "/marm_log_entry",
        json={"session_name": "freeform", "entry": raw_entry},
    )

    assert created.status_code == 200
    shown = client.get("/marm_log_show", params={"session_name": "freeform"})
    entry = shown.json()["entries"][0]

    assert entry["entry_date"] == today
    assert entry["topic"] == "general"
    assert entry["summary"] == raw_entry
    assert entry["full_entry"] == raw_entry


def test_empty_summary_returns_empty_status_for_missing_session(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.get("/marm_summary", params={"session_name": "missing-session"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "empty",
        "message": "No entries found in session 'missing-session'",
    }


def test_notebook_use_delete_clear_lifecycle_updates_active_state(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    add = client.post(
        "/marm_notebook_add",
        json={"name": "release_rule", "data": "Always verify Docker HTTP and STDIO."},
    )
    assert add.status_code == 200

    use = client.post("/marm_notebook_use", json={"names": "release_rule"})
    assert use.status_code == 200
    assert use.json()["activated_entries"] == ["release_rule"]

    status = client.get("/marm_notebook_status")
    assert status.status_code == 200
    assert status.json()["active_entries"] == ["release_rule"]

    deleted = client.delete("/marm_notebook_delete", params={"name": "release_rule"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    after_delete = client.get("/marm_notebook_status")
    assert after_delete.json()["active_entries"] == []
    assert after_delete.json()["active_count"] == 0

    missing = client.delete("/marm_notebook_delete", params={"name": "release_rule"})
    assert missing.status_code == 200
    assert missing.json()["status"] == "not_found"


def test_notebook_show_previews_long_entries_and_clear_resets_active_list(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    long_data = "A" * 150

    assert client.post("/marm_notebook_add", json={"name": "long_note", "data": long_data}).status_code == 200
    assert client.post("/marm_notebook_use", json={"names": "long_note"}).json()["status"] == "success"

    shown = client.get("/marm_notebook_show")
    assert shown.status_code == 200
    entry = shown.json()["entries"][0]
    assert entry["name"] == "long_note"
    assert entry["preview"] == ("A" * 100) + "..."

    cleared = client.delete("/marm_notebook_clear")
    assert cleared.status_code == 200
    assert cleared.json()["active_count"] == 0
    assert client.get("/marm_notebook_status").json()["active_entries"] == []


def test_contextual_log_recall_context_bridge_and_system_info(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    log = client.post(
        "/marm_contextual_log",
        json={
            "session_name": "search-session",
            "content": "project decision: qwen uses http transport command",
        },
    )
    assert log.status_code == 200
    assert log.json()["context_type"] == "project"

    recall = client.post(
        "/marm_smart_recall",
        json={"session_name": "search-session", "query": "qwen", "limit": 3},
    )
    assert recall.status_code == 200
    assert recall.json()["status"] == "success"
    assert recall.json()["results"][0]["content"] == "project decision: qwen uses http transport command"

    no_results = client.post(
        "/marm_smart_recall",
        json={"session_name": "search-session", "query": "nothing-matches-this", "limit": 3},
    )
    assert no_results.status_code == 200
    assert no_results.json()["status"] == "no_results"

    bridge = client.post(
        "/marm_context_bridge",
        json={"session_name": "search-session", "new_topic": "qwen"},
    )
    assert bridge.status_code == 200
    assert bridge.json()["status"] == "success"
    assert bridge.json()["related_count"] >= 0
    assert "Context Bridge: qwen" in bridge.json()["bridge_text"]

    system = client.get("/marm_system_info")
    assert system.status_code == 200
    assert system.json()["status"] == "operational"
    assert system.json()["database_stats"]["memories"] == 1
    assert "websocket" not in str(system.json()).lower()

    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    with memory_module.memory.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    assert count == 1


def test_endpoint_validation_rejects_wrong_payload_shapes(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    bad_recall = client.post("/marm_smart_recall", json={"session_name": "x"})
    bad_log = client.post("/marm_log_entry", json={"session_name": "x", "content": "old field"})
    bad_notebook = client.post("/marm_notebook_add", json={"name": "x", "content": "old field"})
    bad_summary = client.get("/marm_summary")

    assert bad_recall.status_code == 422
    assert bad_log.status_code == 422
    assert bad_notebook.status_code == 422
    assert bad_summary.status_code == 422


def test_marm_refresh_updates_session_and_returns_protocol(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    client.post("/marm_start", json={"session_name": "refresh-session"})

    response = client.post("/marm_refresh", json={"session_name": "refresh-session"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["session_name"] == "refresh-session"
    assert "protocol_content" in body

    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    with memory_module.memory.get_connection() as conn:
        row = conn.execute(
            "SELECT last_accessed FROM sessions WHERE session_name = ?",
            ("refresh-session",),
        ).fetchone()
    assert row is not None


def test_marm_reload_docs_returns_success(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.post("/marm_reload_docs")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "timestamp" in body


def test_log_entries_are_isolated_by_session(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    client.post("/marm_log_entry", json={"session_name": "alpha", "entry": "2026-01-01-alpha-decision recorded"})
    client.post("/marm_log_entry", json={"session_name": "beta", "entry": "2026-01-02-beta-decision recorded"})

    alpha = client.get("/marm_log_show", params={"session_name": "alpha"})
    beta = client.get("/marm_log_show", params={"session_name": "beta"})

    assert alpha.json()["total_entries"] == 1
    assert beta.json()["total_entries"] == 1
    assert alpha.json()["entries"][0]["topic"] == "alpha"
    assert beta.json()["entries"][0]["topic"] == "beta"
    assert alpha.json()["entries"][0]["entry_date"] == "2026-01-01"
    assert beta.json()["entries"][0]["entry_date"] == "2026-01-02"
