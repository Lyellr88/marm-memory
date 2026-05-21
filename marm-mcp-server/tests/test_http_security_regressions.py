import importlib

from conftest import load_isolated_server, local_client


def test_xss_payloads_are_sanitized_before_response_and_storage(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    payloads = [
        "<script>alert('xss')</script>project milestone",
        '<img src="x" onerror="alert(1)"> image note',
        "javascript:alert('xss') protocol note",
        "<iframe src='javascript:alert(1)'></iframe> frame note",
    ]

    stored_ids = []
    for index, payload in enumerate(payloads):
        response = client.post(
            "/marm_context_log",
            json={"session_name": "security-xss", "content": payload},
        )
        assert response.status_code == 200
        body = response.json()
        stored_ids.append(body["memory_id"])

        sanitized = body["content"].lower()
        assert "<script" not in sanitized
        assert "onerror" not in sanitized
        assert "javascript:" not in sanitized

    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    with memory_module.memory.get_connection() as conn:
        rows = conn.execute(
            "SELECT content FROM memories WHERE id IN ({})".format(
                ",".join("?" for _ in stored_ids)
            ),
            stored_ids,
        ).fetchall()

    assert len(rows) == len(payloads)
    for row in rows:
        content = row[0].lower()
        assert "<script" not in content
        assert "onerror" not in content
        assert "javascript:" not in content


def test_sql_injection_queries_do_not_escape_session_scope_or_damage_tables(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    assert client.post(
        "/marm_context_log",
        json={
            "session_name": "safe-session",
            "content": "ordinary safe content about docker transport",
        },
    ).status_code == 200
    assert client.post(
        "/marm_context_log",
        json={
            "session_name": "other-session",
            "content": "secret token should stay scoped to another session",
        },
    ).status_code == 200

    injection_queries = [
        "' OR '1'='1",
        "'; DROP TABLE memories; --",
        "' UNION SELECT * FROM memories --",
        "%' OR session_name != 'safe-session",
    ]

    for query in injection_queries:
        response = client.post(
            "/marm_smart_recall",
            json={"session_name": "safe-session", "query": query, "limit": 10},
        )
        assert response.status_code == 200
        for result in response.json().get("results", []):
            assert result["session_name"] == "safe-session"

    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    with memory_module.memory.get_connection() as conn:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchone()
        memory_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    assert table_exists is not None
    assert memory_count == 2


def test_recall_is_session_scoped_unless_search_all_is_requested(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    assert client.post(
        "/marm_context_log",
        json={"session_name": "alpha", "content": "alpha-only marker for scoped recall"},
    ).status_code == 200
    assert client.post(
        "/marm_context_log",
        json={"session_name": "beta", "content": "beta-only marker for scoped recall"},
    ).status_code == 200

    scoped = client.post(
        "/marm_smart_recall",
        json={"session_name": "alpha", "query": "marker", "limit": 10},
    )
    global_search = client.post(
        "/marm_smart_recall",
        json={
            "session_name": "alpha",
            "query": "marker",
            "limit": 10,
            "search_all": True,
        },
    )

    assert scoped.status_code == 200
    assert {item["session_name"] for item in scoped.json()["results"]} == {"alpha"}
    assert global_search.status_code == 200
    assert {item["session_name"] for item in global_search.json()["results"]} == {
        "alpha",
        "beta",
    }
