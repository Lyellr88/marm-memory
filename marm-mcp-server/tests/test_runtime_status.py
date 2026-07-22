from marm_mcp_server.services import runtime_status


def test_knowledge_status_does_not_create_absent_concept_database(
    monkeypatch, tmp_path
):
    concept_path = tmp_path / "missing" / "marm_index.db"
    monkeypatch.setattr(
        runtime_status, "get_default_concept_db_path", lambda: str(concept_path)
    )

    result = runtime_status.knowledge_status()

    assert result["schema"] == "missing"
    assert result["database"]["exists"] is False
    assert not concept_path.exists()
    assert not concept_path.parent.exists()


def test_passive_status_does_not_start_graph(monkeypatch, tmp_path):
    memory_path = tmp_path / "missing-memory.db"
    monkeypatch.setattr(runtime_status, "DEFAULT_DB_PATH", str(memory_path))
    monkeypatch.setattr(
        runtime_status,
        "inspect_runtime",
        lambda: {"state": "stopped", "managed": False},
    )
    monkeypatch.setattr(
        runtime_status,
        "knowledge_status",
        lambda: {
            "state": "ready_no_build",
            "database": {"path": str(tmp_path / "concept.db"), "exists": False},
        },
    )

    result = runtime_status.full_status()

    assert result["projects"] == {"state": "runtime_stopped"}
    assert result["memory"]["exists"] is False
    assert not memory_path.exists()
