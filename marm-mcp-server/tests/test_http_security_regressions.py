import importlib

from conftest import load_isolated_server, local_client


def test_sql_injection_queries_do_not_escape_session_scope_or_damage_tables(
    monkeypatch, tmp_path
):
    import asyncio

    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    memory_module = importlib.import_module("marm_mcp_server.core.memory")

    asyncio.run(
        memory_module.memory.store_memory_queued(
            "ordinary safe content about docker transport", "safe-session"
        )
    )
    asyncio.run(
        memory_module.memory.store_memory_queued(
            "secret token should stay scoped to another session", "other-session"
        )
    )

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
    import asyncio

    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    memory_module = importlib.import_module("marm_mcp_server.core.memory")

    asyncio.run(
        memory_module.memory.store_memory_queued(
            "alpha-only marker for scoped recall", "alpha"
        )
    )
    asyncio.run(
        memory_module.memory.store_memory_queued(
            "beta-only marker for scoped recall", "beta"
        )
    )

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
