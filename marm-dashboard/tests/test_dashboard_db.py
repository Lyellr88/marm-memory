import sqlite3

from conftest import load_dashboard, local_client


def test_memory_create_sanitizes_content_updates_session_and_can_delete(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    created = client.post(
        "/api/memories",
        json={
            "session_name": "dashboard-session",
            "context_type": "project",
            "content": "<script>alert(1)</script>javascript:alert(2) project note",
        },
    )

    assert created.status_code == 201
    memory_id = created.json()["id"]

    listed = client.get("/api/memories", params={"session": "dashboard-session"})
    item = listed.json()["items"][0]
    assert item["id"] == memory_id
    assert item["context_type"] == "project"
    assert "<script" not in item["content"].lower()
    assert "javascript:" not in item["content"].lower()
    assert "blocked-protocol:" in item["display_content"]

    sessions = client.get("/api/sessions").json()["items"]
    assert sessions[0]["session_name"] == "dashboard-session"
    assert sessions[0]["memory_count"] == 1

    deleted = client.delete(f"/api/memories/{memory_id}")
    assert deleted.status_code == 200
    assert client.delete(f"/api/memories/{memory_id}").status_code == 404


def test_memory_search_escapes_sql_like_wildcards(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    assert client.post(
        "/api/memories",
        json={
            "session_name": "search",
            "context_type": "general",
            "content": "literal 100% marker with underscore_a",
        },
    ).status_code == 201
    assert client.post(
        "/api/memories",
        json={
            "session_name": "search",
            "context_type": "general",
            "content": "ordinary marker without wildcard chars",
        },
    ).status_code == 201

    percent = client.get("/api/memories", params={"q": "100%"}).json()
    underscore = client.get("/api/memories", params={"q": "underscore_"}).json()

    assert percent["total"] == 1
    assert "100%" in percent["items"][0]["display_content"]
    assert underscore["total"] == 1
    assert "underscore_a" in underscore["items"][0]["display_content"]


def test_notebook_upsert_strips_scripts_and_delete_is_exact(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    saved = client.post(
        "/api/notebook",
        json={"name": "deploy-note", "data": "<script>x()</script>Use Docker STDIO"},
    )
    assert saved.status_code == 201

    item = client.get("/api/notebook").json()["items"][0]
    assert item["name"] == "deploy-note"
    assert "<script" not in item["data"].lower()
    assert "Use Docker STDIO" in item["data"]

    assert client.delete("/api/notebook/deploy-note").status_code == 200
    assert client.delete("/api/notebook/deploy-note").status_code == 404


def test_notebook_preserves_text_after_malformed_script_closers(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    payloads = [
        ("valid-close", "<script>alert(1)</script>keep this", "keep this", "alert(1)"),
        ("close-with-attrs", "<script>alert(1)</script foo>keep this", "keep this", "alert(1)"),
        ("close-with-space", "<script src=x>alert(1)</script x>keep this", "keep this", "alert(1)"),
        ("broken-close", "<script>alert(1)< /script>keep this", "keep this", None),
        ("unterminated-open", "keep this <script partial note", "keep this", "partial note"),
    ]

    for name, data, expected_kept, expected_removed in payloads:
        saved = client.post("/api/notebook", json={"name": name, "data": data})
        assert saved.status_code == 201

        item = next(
            entry for entry in client.get("/api/notebook").json()["items"]
            if entry["name"] == name
        )

        assert "<script" not in item["data"].lower()
        assert expected_kept in item["data"]
        if expected_removed:
            assert expected_removed not in item["data"]


def test_summary_reports_real_database_counts(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry)
            VALUES ('log-1', 'main', '2026-05-17', 'docker', 'validated', '2026-05-17-docker-validated')
            """
        )
        conn.commit()

    assert client.post(
        "/api/memories",
        json={"session_name": "main", "context_type": "general", "content": "memory"},
    ).status_code == 201
    assert client.post("/api/notebook", json={"name": "note", "data": "data"}).status_code == 201

    summary = client.get("/api/summary").json()

    assert summary["counts"] == {
        "memories": 1,
        "sessions": 1,
        "log_entries": 1,
        "notebook_entries": 1,
    }


def test_memory_content_truncated_at_10kb(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    res = client.post(
        "/api/memories",
        json={"session_name": "trunc", "context_type": "general", "content": "x" * 15_000},
    )
    assert res.status_code == 201

    item = client.get("/api/memories", params={"session": "trunc"}).json()["items"][0]
    assert len(item["content"]) <= 10_000


def test_logs_list_and_filter_by_session(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("l1", "alpha", "2026-05-17", "deploy", "deployed", "deployed alpha"),
                ("l2", "beta", "2026-05-17", "test", "tested", "tested beta"),
            ],
        )
        conn.commit()

    all_logs = client.get("/api/logs").json()
    assert all_logs["total"] == 2

    alpha_logs = client.get("/api/logs", params={"session": "alpha"}).json()
    assert alpha_logs["total"] == 1
    assert alpha_logs["items"][0]["topic"] == "deploy"

    beta_logs = client.get("/api/logs", params={"session": "beta"}).json()
    assert beta_logs["total"] == 1
    assert beta_logs["items"][0]["topic"] == "test"


def test_log_delete_returns_200_and_404_on_repeat(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry) VALUES ('del-1', 'main', '2026-05-17', 'topic', 'summary', 'full')"
        )
        conn.commit()

    assert client.delete("/api/logs/del-1").status_code == 200
    assert client.delete("/api/logs/del-1").status_code == 404


def test_session_names_aggregates_memories_and_logs(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    client.post(
        "/api/memories",
        json={"session_name": "mem-session", "context_type": "general", "content": "x"},
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry) VALUES ('sn-1', 'log-session', '2026-05-17', 't', 's', 'f')"
        )
        conn.commit()

    names = client.get("/api/session-names").json()["items"]
    assert "mem-session" in names
    assert "log-session" in names


def test_memories_pagination_limit_and_offset(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    for i in range(5):
        client.post(
            "/api/memories",
            json={"session_name": "pager", "context_type": "general", "content": f"memory {i}"},
        )

    page1 = client.get("/api/memories", params={"session": "pager", "limit": 2, "offset": 0}).json()
    page2 = client.get("/api/memories", params={"session": "pager", "limit": 2, "offset": 2}).json()

    assert page1["total"] == 5
    assert len(page1["items"]) == 2
    assert page2["total"] == 5
    assert len(page2["items"]) == 2
    assert {i["id"] for i in page1["items"]}.isdisjoint({i["id"] for i in page2["items"]})


def test_memory_update_changes_content_and_context_type(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    memory_id = client.post(
        "/api/memories",
        json={"session_name": "edit-test", "context_type": "general", "content": "original content"},
    ).json()["id"]

    updated = client.put(
        f"/api/memories/{memory_id}",
        json={"content": "updated content", "context_type": "code"},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == memory_id

    item = client.get("/api/memories", params={"session": "edit-test"}).json()["items"][0]
    assert "updated content" in item["display_content"]
    assert item["context_type"] == "code"

    assert client.put(
        "/api/memories/nonexistent-id",
        json={"content": "x", "context_type": "general"},
    ).status_code == 404


def test_session_create_rejects_duplicate(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    assert client.post("/api/sessions", json={"session_name": "new-session"}).status_code == 201
    assert client.post("/api/sessions", json={"session_name": "new-session"}).status_code == 400

    sessions = client.get("/api/sessions").json()["items"]
    assert len(sessions) == 1
    assert sessions[0]["session_name"] == "new-session"


def test_session_delete_single_and_delete_all(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    client.post("/api/sessions", json={"session_name": "s1"})
    client.post("/api/sessions", json={"session_name": "s2"})

    assert client.delete("/api/sessions/s1").status_code == 200
    assert client.delete("/api/sessions/s1").status_code == 404
    assert client.get("/api/sessions").json()["items"][0]["session_name"] == "s2"

    res = client.delete("/api/sessions")
    assert res.status_code == 200
    assert res.json()["count"] == 1
    assert client.get("/api/sessions").json()["items"] == []


def test_delete_all_memories_wipes_all_entries(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    for i in range(3):
        client.post(
            "/api/memories",
            json={"session_name": "wipe", "context_type": "general", "content": f"entry {i}"},
        )

    assert client.get("/api/memories").json()["total"] == 3

    res = client.delete("/api/memories")
    assert res.status_code == 200
    assert res.json()["count"] == 3
    assert client.get("/api/memories").json()["total"] == 0


def test_delete_all_notebook_wipes_all_entries(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    client.post("/api/notebook", json={"name": "note-a", "data": "alpha"})
    client.post("/api/notebook", json={"name": "note-b", "data": "beta"})

    res = client.delete("/api/notebook")
    assert res.status_code == 200
    assert res.json()["count"] == 2
    assert client.get("/api/notebook").json()["items"] == []


def test_delete_all_logs_wipes_all_entries(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry) VALUES (?, ?, ?, ?, ?, ?)",
            [("wl1", "main", "2026-05-17", "t1", "s1", "f1"), ("wl2", "main", "2026-05-17", "t2", "s2", "f2")],
        )
        conn.commit()

    res = client.delete("/api/logs")
    assert res.status_code == 200
    assert res.json()["count"] == 2
    assert client.get("/api/logs").json()["total"] == 0


def test_sessions_search_filters_by_name(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    client.post("/api/sessions", json={"session_name": "project-alpha"})
    client.post("/api/sessions", json={"session_name": "project-beta"})
    client.post("/api/sessions", json={"session_name": "unrelated"})

    results = client.get("/api/sessions", params={"q": "project"}).json()["items"]
    assert len(results) == 2
    names = {s["session_name"] for s in results}
    assert names == {"project-alpha", "project-beta"}


def test_logs_search_filters_by_topic_and_summary(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)
    db_path = tmp_path / "marm_memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO log_entries (id, session_name, entry_date, topic, summary, full_entry) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("sl1", "main", "2026-05-17", "docker-deploy", "routine deploy", "full"),
                ("sl2", "main", "2026-05-17", "testing", "docker image validated", "full"),
                ("sl3", "main", "2026-05-17", "unrelated", "nothing here", "full"),
            ],
        )
        conn.commit()

    by_topic = client.get("/api/logs", params={"q": "docker"}).json()
    assert by_topic["total"] == 2

    by_summary = client.get("/api/logs", params={"q": "validated"}).json()
    assert by_summary["total"] == 1
    assert by_summary["items"][0]["topic"] == "testing"


def test_notebook_search_filters_by_name_and_data(monkeypatch, tmp_path):
    server = load_dashboard(monkeypatch, tmp_path)
    client = local_client(server.app)

    client.post("/api/notebook", json={"name": "deploy-guide", "data": "Use Docker STDIO"})
    client.post("/api/notebook", json={"name": "setup-notes", "data": "Docker compose setup"})
    client.post("/api/notebook", json={"name": "roadmap", "data": "Q3 planning items"})

    by_name = client.get("/api/notebook", params={"q": "deploy"}).json()["items"]
    assert len(by_name) == 1
    assert by_name[0]["name"] == "deploy-guide"

    by_data = client.get("/api/notebook", params={"q": "Docker"}).json()["items"]
    assert len(by_data) == 2
