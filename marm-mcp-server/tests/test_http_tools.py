import asyncio
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

    deleted = client.post(
        "/marm_delete",
        json={"type": "log", "session_name": "release-notes", "target": entry_id},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted_count"] == 1
    assert client.get("/marm_log_show", params={"session_name": "release-notes"}).json()["total_entries"] == 0


def test_log_entry_without_session_name_uses_active_session(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    switch = client.post("/marm_log_session", json={"session_name": "myproject"})
    assert switch.status_code == 200
    assert switch.json()["session_name"] == "myproject"

    # No session_name — should land in "myproject", not "main"
    entry = client.post("/marm_log_entry", json={"entry": "2026-05-20-setup-initial scaffolding done"})
    assert entry.status_code == 200

    in_project = client.get("/marm_log_show", params={"session_name": "myproject"})
    assert in_project.json()["total_entries"] == 1

    in_main = client.get("/marm_log_show", params={"session_name": "main"})
    assert in_main.json().get("total_entries", 0) == 0


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
        "/marm_notebook",
        json={"action": "add", "name": "release_rule", "data": "Always verify Docker HTTP and STDIO."},
    )
    assert add.status_code == 200

    use = client.post("/marm_notebook", json={"action": "use", "names": "release_rule"})
    assert use.status_code == 200
    assert use.json()["activated_entries"] == ["release_rule"]

    status = client.post("/marm_notebook", json={"action": "status"})
    assert status.status_code == 200
    assert status.json()["active_entries"] == ["release_rule"]

    deleted = client.post("/marm_delete", json={"type": "notebook", "target": "release_rule"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    after_delete = client.post("/marm_notebook", json={"action": "status"})
    assert after_delete.json()["active_entries"] == []
    assert after_delete.json()["active_count"] == 0

    missing = client.post("/marm_delete", json={"type": "notebook", "target": "release_rule"})
    assert missing.status_code == 200
    assert missing.json()["status"] == "not_found"


def test_notebook_show_previews_long_entries_and_clear_resets_active_list(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    long_data = "A" * 150

    assert client.post("/marm_notebook", json={"action": "add", "name": "long_note", "data": long_data}).status_code == 200
    assert client.post("/marm_notebook", json={"action": "use", "names": "long_note"}).json()["status"] == "success"

    shown = client.post("/marm_notebook", json={"action": "show"})
    assert shown.status_code == 200
    entry = shown.json()["entries"][0]
    assert entry["name"] == "long_note"
    assert entry["preview"] == ("A" * 100) + "..."

    cleared = client.post("/marm_notebook", json={"action": "clear"})
    assert cleared.status_code == 200
    assert cleared.json()["active_count"] == 0
    assert client.post("/marm_notebook", json={"action": "status"}).json()["active_entries"] == []


def test_notebook_active_state_is_scoped_by_session(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    assert client.post(
        "/marm_notebook",
        json={"action": "add", "name": "alpha_rule", "data": "alpha instructions"},
    ).status_code == 200
    assert client.post(
        "/marm_notebook",
        json={"action": "add", "name": "beta_rule", "data": "beta instructions"},
    ).status_code == 200

    alpha_use = client.post(
        "/marm_notebook",
        json={"action": "use", "names": "alpha_rule", "session_name": "alpha"},
    )
    beta_use = client.post(
        "/marm_notebook",
        json={"action": "use", "names": "beta_rule", "session_name": "beta"},
    )

    assert alpha_use.status_code == 200
    assert beta_use.status_code == 200

    alpha_status = client.post("/marm_notebook", json={"action": "status", "session_name": "alpha"})
    beta_status = client.post("/marm_notebook", json={"action": "status", "session_name": "beta"})

    assert alpha_status.json()["active_entries"] == ["alpha_rule"]
    assert beta_status.json()["active_entries"] == ["beta_rule"]

    alpha_clear = client.post("/marm_notebook", json={"action": "clear", "session_name": "alpha"})
    assert alpha_clear.status_code == 200

    alpha_after_clear = client.post("/marm_notebook", json={"action": "status", "session_name": "alpha"})
    beta_after_clear = client.post("/marm_notebook", json={"action": "status", "session_name": "beta"})

    assert alpha_after_clear.json()["active_entries"] == []
    assert beta_after_clear.json()["active_entries"] == ["beta_rule"]


def test_http_notebook_add_persists_entry_and_embedding(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    memory_module = importlib.import_module("marm_mcp_server.core.memory")

    class FakeEmbedding:
        def tobytes(self):
            return b"fake-embedding-bytes"

    class FakeEncoder:
        def encode(self, text):
            assert text == "Notebook entries should keep embeddings when available."
            return FakeEmbedding()

    monkeypatch.setattr(memory_module.memory, "encoder", FakeEncoder())

    response = client.post(
        "/marm_notebook",
        json={
            "action": "add",
            "name": "embedded_rule",
            "data": "Notebook entries should keep embeddings when available.",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    with memory_module.memory.get_connection() as conn:
        row = conn.execute(
            "SELECT name, data, embedding FROM notebook_entries WHERE name = ?",
            ("embedded_rule",),
        ).fetchone()

    assert row is not None
    assert row[0] == "embedded_rule"
    assert row[1] == "Notebook entries should keep embeddings when available."
    assert row[2] == b"fake-embedding-bytes"


def test_http_notebook_service_errors_return_400(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    missing_data = client.post(
        "/marm_notebook",
        json={"action": "add", "name": "missing_data"},
    )
    missing_names = client.post("/marm_notebook", json={"action": "use"})

    assert missing_data.status_code == 400
    assert "name and data are required" in missing_data.json()["detail"]
    assert missing_names.status_code == 400
    assert "names is required" in missing_names.json()["detail"]


def test_context_log_recall_include_logs_and_system_info(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    log = client.post(
        "/marm_context_log",
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

    # Write a log entry so include_logs=True has something real to return
    client.post("/marm_log_session", json={"session_name": "search-session"})
    client.post(
        "/marm_log_entry",
        json={"session_name": "search-session", "entry": "2026-05-20-qwen-qwen transport decision noted"},
    )

    # include_logs=True must return the log entry we just wrote
    recall_with_logs = client.post(
        "/marm_smart_recall",
        json={"session_name": "search-session", "query": "qwen", "limit": 3, "include_logs": True},
    )
    assert recall_with_logs.status_code == 200
    assert "log_results" in recall_with_logs.json()
    assert "log_results_count" in recall_with_logs.json()
    assert recall_with_logs.json()["log_results_count"] >= 1, (
        f"include_logs=True returned no log entries: {recall_with_logs.json()}"
    )
    log_topics = [r["topic"] for r in recall_with_logs.json()["log_results"]]
    assert any("qwen" in t for t in log_topics), f"Expected qwen in log topics, got: {log_topics}"

    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    with memory_module.memory.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    assert count == 1


def test_context_log_uses_write_queue_when_enabled(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path, write_queue_enabled=True)

    with local_client(server.app) as client:
        log = client.post(
            "/marm_context_log",
            json={
                "session_name": "queued-http",
                "content": "queued http memory write for swarm agents",
            },
        )
        memory_module = importlib.import_module("marm_mcp_server.core.memory")
        assert memory_module.memory._write_queue is not None

    assert log.status_code == 200
    assert log.json()["status"] == "success"

    with memory_module.memory.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = ?",
            ("queued-http",),
        ).fetchone()[0]

    assert count == 1


def test_smart_recall_include_logs_returns_log_matches_without_memory_hits(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    client.post("/marm_log_session", json={"session_name": "log-only-session"})
    created = client.post(
        "/marm_log_entry",
        json={
            "session_name": "log-only-session",
            "entry": "2026-05-20-logonlysentinel-transport command captured",
        },
    )
    assert created.status_code == 200

    recall = client.post(
        "/marm_smart_recall",
        json={
            "session_name": "log-only-session",
            "query": "logonlysentinel",
            "limit": 3,
            "include_logs": True,
        },
    )

    body = recall.json()
    assert recall.status_code == 200
    assert body["status"] == "no_results"
    assert body["results"] == []
    assert body["log_results_count"] == 1
    assert body["log_results"][0]["topic"] == "logonlysentinel"
    assert body["log_results"][0]["session_name"] == "log-only-session"


def test_cold_startup_leaves_doc_tables_empty(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)

    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    with memory_module.memory.get_connection() as conn:
        nb_count = conn.execute(
            "SELECT COUNT(*) FROM notebook_entries WHERE name LIKE 'marm_%'"
        ).fetchone()[0]
        mem_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = 'marm_system'"
        ).fetchone()[0]

    assert nb_count == 0, f"Expected 0 marm_ notebook entries on cold boot, got {nb_count}"
    assert mem_count == 0, f"Expected 0 marm_system memories on cold boot, got {mem_count}"


def test_marm_start_loads_docs_once_not_on_repeated_calls(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")
    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    client = local_client(server.app)

    assert not doc_module.docs_are_loaded()

    client.post("/marm_start", json={"session_name": "s1"})
    assert doc_module.docs_are_loaded()

    with memory_module.memory.get_connection() as conn:
        count_after_first = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = 'marm_system'"
        ).fetchone()[0]

    # Reset the in-memory flag to simulate a second startup without clearing doc_index
    doc_module._docs_loaded = False
    client.post("/marm_start", json={"session_name": "s2"})

    with memory_module.memory.get_connection() as conn:
        count_after_second = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = 'marm_system'"
        ).fetchone()[0]

    assert count_after_second == count_after_first, (
        f"marm_system memory count grew on repeated load: {count_after_first} -> {count_after_second}"
    )


def test_doc_loader_reindexes_when_memory_row_deleted(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")
    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    client = local_client(server.app)

    # First load — populates doc_index with memory_id
    client.post("/marm_start", json={"session_name": "s1"})
    assert doc_module.docs_are_loaded()

    with memory_module.memory.get_connection() as conn:
        memory_id = conn.execute(
            "SELECT memory_id FROM doc_index LIMIT 1"
        ).fetchone()

    assert memory_id and memory_id[0], "doc_index should have a memory_id after first load"

    # Delete the memory row externally (simulates dashboard/manual cleanup)
    with memory_module.memory.get_connection() as conn:
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id[0],))
        conn.commit()

    # Reset flag and reload — loader should detect missing memory and re-index
    doc_module._docs_loaded = False
    client.post("/marm_start", json={"session_name": "s2"})

    with memory_module.memory.get_connection() as conn:
        new_memory_id = conn.execute(
            "SELECT memory_id FROM doc_index LIMIT 1"
        ).fetchone()
        marm_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = 'marm_system'"
        ).fetchone()[0]

    assert marm_count > 0, "Re-index after missing memory row should restore marm_system memories"
    assert new_memory_id and new_memory_id[0], "doc_index should have a memory_id after re-index"
    assert new_memory_id[0] != memory_id[0], "doc_index memory_id should be updated to the new row after re-index"
    with memory_module.memory.get_connection() as conn:
        new_row_exists = conn.execute(
            "SELECT 1 FROM memories WHERE id = ?", (new_memory_id[0],)
        ).fetchone()
    assert new_row_exists, "new doc_index memory_id must point to an existing memories row"


def test_legacy_system_notebook_entries_cleaned_on_load(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")
    memory_module = importlib.import_module("marm_mcp_server.core.memory")

    # Pre-populate stale system notebook entries as an old MARM version would have
    legacy_names = ["marm_protocol", "marm_commands_summary", "mcp_integration_guide"]
    with memory_module.memory.get_connection() as conn:
        for name in legacy_names:
            conn.execute(
                "INSERT OR REPLACE INTO notebook_entries (name, data, updated_at) VALUES (?, ?, ?)",
                (name, "stale system data", "2025-01-01T00:00:00"),
            )
        conn.commit()

    asyncio.run(doc_module.load_marm_documentation())

    with memory_module.memory.get_connection() as conn:
        remaining = conn.execute(
            "SELECT name FROM notebook_entries WHERE name IN (?, ?, ?)",
            tuple(legacy_names),
        ).fetchall()

    assert remaining == [], f"Legacy system notebook entries should be removed: {remaining}"


def test_marm_reload_docs_indexes_documentation(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")
    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    client = local_client(server.app)

    # Force docs loaded flag so reload has something to reset
    doc_module._docs_loaded = True

    response = client.post("/marm_reload_docs")
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert doc_module.docs_are_loaded()

    with memory_module.memory.get_connection() as conn:
        mem_count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE session_name = 'marm_system'"
        ).fetchone()[0]

    assert mem_count > 0, "marm_reload_docs did not index any docs into memories"


def test_doc_loader_does_not_mark_loaded_when_no_docs_found(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")

    monkeypatch.setattr(doc_module, "get_docs_to_load", lambda: [])

    assert not doc_module.docs_are_loaded()
    asyncio.run(doc_module.load_marm_documentation())
    assert not doc_module.docs_are_loaded()


def test_endpoint_validation_rejects_wrong_payload_shapes(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    bad_recall = client.post("/marm_smart_recall", json={"session_name": "x"})
    bad_log = client.post("/marm_log_entry", json={"session_name": "x", "content": "old field"})
    bad_notebook = client.post("/marm_notebook", json={"name": "x", "data": "no action field"})
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


def test_marm_delete_session_resets_active_log_session(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    client.post("/marm_log_session", json={"session_name": "project-a"})
    client.post("/marm_log_entry", json={"session_name": "project-a", "entry": "2026-05-20-init-setup complete"})

    deleted = client.post("/marm_delete", json={"type": "log", "target": "project-a"})
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "success"

    # Session rows gone
    shown = client.get("/marm_log_show", params={"session_name": "project-a"})
    assert shown.json().get("total_entries", 0) == 0

    # Next log entry without session_name must NOT re-land in project-a
    client.post("/marm_log_entry", json={"entry": "2026-05-20-follow-up-should not go to project-a"})
    still_gone = client.get("/marm_log_show", params={"session_name": "project-a"})
    assert still_gone.json().get("total_entries", 0) == 0


def test_http_removed_tools_absent_from_openapi_schema(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json().get("paths", {})

    assert "/marm_start" not in paths, "marm_start must be hidden from MCP (include_in_schema=False)"
    assert "/marm_refresh" not in paths, "marm_refresh must be hidden from MCP"
    assert "/marm_reload_docs" not in paths, "marm_reload_docs must be hidden from MCP"
    assert "/marm_current_context" not in paths, "marm_current_context must be hidden from MCP"
    assert "/marm_system_info" not in paths, "marm_system_info must be hidden from MCP"

    assert "/marm_smart_recall" in paths
    assert "/marm_delete" in paths
    assert "/marm_notebook" in paths
    assert "/marm_notebook_add" not in paths, "old marm_notebook_add must be removed"
    assert "/marm_notebook_use" not in paths, "old marm_notebook_use must be removed"
    assert "/marm_notebook_show" not in paths, "old marm_notebook_show must be removed"
    assert "/marm_notebook_status" not in paths, "old marm_notebook_status must be removed"
    assert "/marm_notebook_clear" not in paths, "old marm_notebook_clear must be removed"
    assert "/marm_compaction" in paths
    assert "/marm_get_compaction_candidates" not in paths
    assert "/marm_stage_compaction_summaries" not in paths
    assert "/marm_get_staged_summaries" not in paths
    assert "/marm_apply_compaction" not in paths


def test_http_mcp_tools_call_body_triggers_doc_loading(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")
    client = local_client(server.app)

    assert not doc_module.docs_are_loaded()

    # POST /mcp with "tools/call" in body fires the middleware doc-load path
    # before the handler; response status doesn't matter for this assertion
    client.post(
        "/mcp",
        content=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}',
        headers={"content-type": "application/json"},
    )

    assert doc_module.docs_are_loaded()


def test_auto_refresh_triggers_reload_after_threshold(monkeypatch, tmp_path):
    import asyncio

    load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")

    reload_calls = []

    async def mock_reload():
        doc_module._docs_loaded = True
        reload_calls.append(1)

    monkeypatch.setattr(doc_module, "reload_marm_documentation", mock_reload)
    doc_module._tool_call_count = 0
    doc_module._refresh_in_progress = False

    async def run_n(n):
        for _ in range(n):
            await doc_module.maybe_auto_refresh()

    asyncio.run(run_n(49))
    assert len(reload_calls) == 0, "Reload fired before threshold"

    asyncio.run(run_n(1))
    assert len(reload_calls) == 1, f"Expected 1 reload at threshold, got {len(reload_calls)}"
    assert doc_module._tool_call_count == 0, "Counter should reset after reload"


def test_auto_refresh_allows_only_one_concurrent_reload(monkeypatch, tmp_path):
    import asyncio

    load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")

    reload_started = asyncio.Event()
    release_reload = asyncio.Event()
    reload_calls = []

    async def mock_reload():
        reload_calls.append(1)
        reload_started.set()
        await release_reload.wait()

    monkeypatch.setattr(doc_module, "reload_marm_documentation", mock_reload)
    doc_module._tool_call_count = doc_module.REFRESH_EVERY - 1
    doc_module._refresh_in_progress = False

    async def run_concurrent_refreshes():
        first = asyncio.create_task(doc_module.maybe_auto_refresh())
        await reload_started.wait()

        second = asyncio.create_task(doc_module.maybe_auto_refresh())
        await asyncio.sleep(0)

        release_reload.set()
        await asyncio.gather(first, second)

    asyncio.run(run_concurrent_refreshes())

    assert len(reload_calls) == 1


def test_ensure_marm_started_allows_only_one_concurrent_doc_load(monkeypatch, tmp_path):
    import asyncio

    load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")

    load_started = asyncio.Event()
    release_load = asyncio.Event()
    load_calls = []

    async def mock_load():
        load_calls.append(1)
        load_started.set()
        await release_load.wait()
        doc_module._docs_loaded = True

    monkeypatch.setattr(doc_module, "load_marm_documentation", mock_load)
    doc_module._docs_loaded = False
    doc_module._docs_load_in_progress = False

    async def run_concurrent_starts():
        first = asyncio.create_task(doc_module.ensure_marm_started("alpha"))
        await load_started.wait()

        second = asyncio.create_task(doc_module.ensure_marm_started("beta"))
        await asyncio.sleep(0)

        release_load.set()
        await asyncio.gather(first, second)

    asyncio.run(run_concurrent_starts())

    assert len(load_calls) == 1
    assert doc_module.docs_are_loaded()


def test_http_mcp_tool_response_injects_compaction_prompt(monkeypatch, tmp_path):
    import json
    import uuid
    from datetime import timedelta
    from unittest.mock import AsyncMock, MagicMock

    server = load_isolated_server(monkeypatch, tmp_path)
    compaction_module = importlib.import_module("marm_mcp_server.core.compaction")

    monkeypatch.setattr(compaction_module.settings, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_MAX_NUDGES", 5)
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_NUDGE_COOLDOWN_SECONDS", 2
    )
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_INJECTION_BYTE_BUDGET", 2048
    )
    server._protocol_delivered = True

    candidate_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with server.memory.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO compaction_staging
                (id, session_name, source_memory_ids, preview, suggested_summary,
                 status, candidate_hash, source_updated_at_snapshot,
                 expires_at, created_at, updated_at, reviewed_at)
            VALUES (?, 'sess', ?, ?, NULL, 'pending_summary', 'hash', '{}', ?, ?, ?, NULL)
            """,
            (
                candidate_id,
                json.dumps(["m1", "m2", "m3"]),
                json.dumps(["one", "two", "three"]),
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )

    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": '{"status":"ok"}'}]},
    }).encode()

    async def _iter():
        yield body

    resp = MagicMock()
    resp.status_code = 200
    resp.headers = MagicMock()
    resp.headers.items.return_value = [("x-request-id", "1")]
    resp.body_iterator = _iter()

    req = MagicMock()
    req.method = "POST"
    req.url.path = "/mcp"
    req.body = AsyncMock(
        return_value=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}'
    )

    async def run():
        call = AsyncMock(return_value=resp)
        return await server._mcp_tool_call_tracker(req, call)

    response = asyncio.run(run())
    payload = json.loads(response.body)
    content = payload["result"]["content"]

    assert "[MARM COMPACTION REQUEST]" in content[0]["text"]
    assert candidate_id in content[0]["text"]
    with server.memory.get_connection() as conn:
        nudge_count = conn.execute(
            "SELECT nudge_count FROM compaction_staging WHERE id = ?",
            (candidate_id,),
        ).fetchone()[0]
    assert nudge_count == 1


def test_http_mcp_tool_response_orders_protocol_before_compaction(monkeypatch, tmp_path):
    import json
    import uuid
    from datetime import timedelta
    from unittest.mock import AsyncMock, MagicMock

    server = load_isolated_server(monkeypatch, tmp_path)
    compaction_module = importlib.import_module("marm_mcp_server.core.compaction")
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")

    monkeypatch.setattr(compaction_module.settings, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(compaction_module.settings, "COMPACTION_MAX_NUDGES", 5)
    monkeypatch.setattr(
        compaction_module.settings, "COMPACTION_NUDGE_COOLDOWN_SECONDS", 2
    )
    doc_module._docs_loaded = True
    server._protocol_delivered = False

    candidate_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with server.memory.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO compaction_staging
                (id, session_name, source_memory_ids, preview, suggested_summary,
                 status, candidate_hash, source_updated_at_snapshot,
                 expires_at, created_at, updated_at, reviewed_at)
            VALUES (?, 'sess', ?, ?, NULL, 'pending_summary', 'hash', '{}', ?, ?, ?, NULL)
            """,
            (
                candidate_id,
                json.dumps(["m1", "m2", "m3"]),
                json.dumps(["one", "two", "three"]),
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )

    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": '{"status":"ok"}'}]},
    }).encode()

    async def _iter():
        yield body

    resp = MagicMock()
    resp.status_code = 200
    resp.headers = MagicMock()
    resp.headers.items.return_value = [("x-request-id", "1")]
    resp.body_iterator = _iter()

    req = MagicMock()
    req.method = "POST"
    req.url.path = "/mcp"
    req.body = AsyncMock(
        return_value=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{}}'
    )

    async def run():
        async def body_iter():
            yield body

        # Call 1: protocol is injected, compaction is suppressed on this call
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.headers = MagicMock()
        resp1.headers.items.return_value = [("x-request-id", "1")]
        resp1.body_iterator = body_iter()
        call1 = AsyncMock(return_value=resp1)
        r1 = await server._mcp_tool_call_tracker(req, call1)

        # Call 2: protocol already delivered, compaction fires
        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.headers = MagicMock()
        resp2.headers.items.return_value = [("x-request-id", "2")]
        resp2.body_iterator = body_iter()
        call2 = AsyncMock(return_value=resp2)
        r2 = await server._mcp_tool_call_tracker(req, call2)

        return r1, r2

    r1, r2 = asyncio.run(run())

    content1 = json.loads(r1.body)["result"]["content"]
    assert content1[0]["text"].startswith("[MARM SESSION INIT]"), "protocol must inject on first call"
    assert not any("[MARM COMPACTION REQUEST]" in c["text"] for c in content1), \
        "compaction must not co-inject with protocol on first call"

    content2 = json.loads(r2.body)["result"]["content"]
    assert content2[0]["text"].startswith("[MARM COMPACTION REQUEST]"), "compaction must inject on second call"
    assert candidate_id in content2[0]["text"]


def test_http_protocol_injected_on_first_mcp_tool_call_not_on_second(monkeypatch, tmp_path):
    import json
    from unittest.mock import AsyncMock, MagicMock

    server = load_isolated_server(monkeypatch, tmp_path)
    doc_module = importlib.import_module("marm_mcp_server.services.documentation")

    doc_module._docs_loaded = False
    server._protocol_delivered = False

    tool_call_body = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"marm_notebook","arguments":{"action":"status"}}}'

    def make_mock_response():
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": '{"status":"ok"}'}]}
        }).encode()

        async def _iter():
            yield body

        resp = MagicMock()
        resp.status_code = 200
        resp.headers = MagicMock()
        resp.headers.items.return_value = [("x-request-id", "1")]
        resp.body_iterator = _iter()
        # Explicit bytes so json.loads works when middleware returns mock unchanged (second call)
        resp.body = body
        return resp

    def make_mock_request():
        req = MagicMock()
        req.method = "POST"
        req.url.path = "/mcp"
        req.body = AsyncMock(return_value=tool_call_body)
        return req

    async def run():
        call_1 = AsyncMock(return_value=make_mock_response())
        resp_1 = await server._mcp_tool_call_tracker(make_mock_request(), call_1)

        call_2 = AsyncMock(return_value=make_mock_response())
        resp_2 = await server._mcp_tool_call_tracker(make_mock_request(), call_2)

        return resp_1, resp_2

    resp_1, resp_2 = asyncio.run(run())

    body_1 = json.loads(resp_1.body)
    content_1 = body_1["result"]["content"]
    assert any("[MARM SESSION INIT]" in c["text"] for c in content_1), \
        "Protocol not injected in first MCP tool call response"

    body_2 = json.loads(resp_2.body)
    content_2 = body_2["result"]["content"]
    assert not any("[MARM SESSION INIT]" in c["text"] for c in content_2), \
        "Protocol must not repeat on second MCP tool call"


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
