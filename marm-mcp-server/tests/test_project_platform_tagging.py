import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from conftest import load_isolated_server, local_client

from marm_mcp_server.core.memory import MARMMemory
from marm_mcp_server.core.memory_recall import _recall_text_search


def _direct_insert_memory(
    conn, session: str, content: str, project=None, platform=None
):
    """Insert a memory row directly with explicit project/platform values."""
    memory_id = str(uuid.uuid4())

    conn.execute(
        """
        INSERT INTO memories
            (id, session_name, content, embedding, content_hash, timestamp,
             context_type, metadata, project, platform)
        VALUES (?, ?, ?, NULL, ?, ?, 'general', '{}', ?, ?)
        """,
        (
            memory_id,
            session,
            content,
            content,
            datetime.now(timezone.utc).isoformat(),
            project,
            platform,
        ),
    )
    conn.commit()
    return memory_id


def _direct_insert_log(conn, session: str, topic: str, project=None, platform=None):
    """Insert a log_entry row directly with explicit project/platform values."""

    conn.execute(
        """
        INSERT INTO log_entries
            (id, session_name, entry_date, topic, summary, full_entry, project, platform)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            session,
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            topic,
            topic,
            topic,
            project,
            platform,
        ),
    )
    conn.commit()


def _stage_compaction_candidate(conn, session: str, source_ids: list[str]) -> str:
    """Create a ready-to-apply compaction candidate for source memories."""
    candidate_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        f"SELECT id, content_hash FROM memories WHERE id IN ({','.join('?' * len(source_ids))})",
        source_ids,
    ).fetchall()
    snapshot = {row[0]: row[1] for row in rows}
    conn.execute(
        """
        INSERT INTO compaction_staging
            (id, session_name, source_memory_ids, preview, suggested_summary,
             status, candidate_hash, source_updated_at_snapshot, expires_at,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'summary_staged', ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            session,
            json.dumps(source_ids),
            "preview",
            "compacted project summary",
            "candidate-hash",
            json.dumps(snapshot),
            (now + timedelta(hours=1)).isoformat(),
            now.isoformat(),
            now.isoformat(),
        ),
    )
    conn.commit()
    return candidate_id


def _patch_memory_write_scope(monkeypatch, project, platform) -> None:
    """Patch scope constants on the exact write/consolidation functions under test.

    Some HTTP tests reload marm_mcp_server modules mid-suite. This test module's
    top-level MARMMemory import can then point at a different function graph than
    a fresh import by module name.
    """
    store_globals = MARMMemory.store_memory.__globals__["_store_memory"].__globals__
    monkeypatch.setitem(store_globals, "MARM_PROJECT", project)
    monkeypatch.setitem(store_globals, "MARM_PLATFORM", platform)

    exact_globals = store_globals["find_exact_duplicate"].__globals__
    monkeypatch.setitem(exact_globals, "MARM_PROJECT", project)
    monkeypatch.setitem(exact_globals, "MARM_PLATFORM", platform)

    semantic_globals = store_globals["find_semantic_duplicate"].__globals__
    monkeypatch.setitem(semantic_globals, "MARM_PROJECT", project)
    monkeypatch.setitem(semantic_globals, "MARM_PLATFORM", platform)


@pytest.mark.asyncio
async def test_memory_insert_tags_project_and_platform(monkeypatch, tmp_path):
    _patch_memory_write_scope(monkeypatch, "test-project", "claude-code")

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    mid = await mem.store_memory("testing tagging", "session-a")

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT project, platform FROM memories WHERE id = ?", (mid,)
        ).fetchone()

    assert row[0] == "test-project"
    assert row[1] == "claude-code"


@pytest.mark.asyncio
async def test_memory_insert_null_tags_when_no_project_or_platform(
    monkeypatch, tmp_path
):
    _patch_memory_write_scope(monkeypatch, "", "")

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    mid = await mem.store_memory("untagged memory", "session-a")

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT project, platform FROM memories WHERE id = ?", (mid,)
        ).fetchone()

    assert row[0] is None
    assert row[1] is None


@pytest.mark.asyncio
async def test_recall_project_filter_excludes_other_projects(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        _direct_insert_memory(
            conn, "session-a", "alpha content", project="project-alpha"
        )
        _direct_insert_memory(conn, "session-a", "beta content", project="project-beta")

    results = await _recall_text_search(
        mem, "content", session=None, limit=10, project="project-alpha"
    )

    assert len(results) == 1
    assert results[0]["content"] == "alpha content"
    assert results[0]["project"] == "project-alpha"


@pytest.mark.asyncio
async def test_recall_platform_filter_excludes_other_platforms(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        _direct_insert_memory(
            conn, "session-a", "claude memory", platform="claude-code"
        )
        _direct_insert_memory(conn, "session-a", "cursor memory", platform="cursor")

    results = await _recall_text_search(
        mem, "memory", session=None, limit=10, platform="claude-code"
    )

    assert len(results) == 1
    assert results[0]["content"] == "claude memory"
    assert results[0]["platform"] == "claude-code"


@pytest.mark.asyncio
async def test_recall_unfiltered_returns_all_projects(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        _direct_insert_memory(
            conn, "session-a", "alpha content", project="project-alpha"
        )
        _direct_insert_memory(conn, "session-a", "beta content", project="project-beta")
        _direct_insert_memory(conn, "session-a", "untagged content", project=None)

    results = await _recall_text_search(mem, "content", session=None, limit=10)

    assert len(results) == 3


@pytest.mark.asyncio
async def test_recall_project_and_platform_combined_filter(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        _direct_insert_memory(
            conn, "s", "match", project="proj-a", platform="claude-code"
        )
        _direct_insert_memory(
            conn, "s", "wrong platform", project="proj-a", platform="cursor"
        )
        _direct_insert_memory(
            conn, "s", "wrong project", project="proj-b", platform="claude-code"
        )

    results = await _recall_text_search(
        mem, "match", session=None, limit=10, project="proj-a", platform="claude-code"
    )

    assert len(results) == 1
    assert results[0]["content"] == "match"


@pytest.mark.asyncio
async def test_exact_recall_project_filter_respected(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        _direct_insert_memory(
            conn,
            "s",
            "CONFIG_KEY",
            project="proj-a",
        )
        _direct_insert_memory(
            conn,
            "s",
            "CONFIG_KEY",
            project="proj-b",
        )

    results = await mem.recall_similar(
        "CONFIG_KEY",
        session=None,
        limit=10,
        exact_mode="exact",
        project="proj-a",
    )

    assert len(results) == 1
    assert results[0]["project"] == "proj-a"


@pytest.mark.asyncio
async def test_exact_dedup_does_not_cross_project_boundary(monkeypatch, tmp_path):
    store_globals = MARMMemory.store_memory.__globals__["_store_memory"].__globals__
    monkeypatch.setitem(store_globals, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    _patch_memory_write_scope(monkeypatch, "project-a", "claude-code")
    id_a = await mem.store_memory("identical content", "session-x")

    _patch_memory_write_scope(monkeypatch, "project-b", "claude-code")
    id_b = await mem.store_memory("identical content", "session-x")

    assert id_a != id_b

    with mem.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    assert count == 2


@pytest.mark.asyncio
async def test_exact_dedup_does_not_cross_platform_boundary(monkeypatch, tmp_path):
    store_globals = MARMMemory.store_memory.__globals__["_store_memory"].__globals__
    monkeypatch.setitem(store_globals, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    _patch_memory_write_scope(monkeypatch, "proj-x", "claude-code")
    id_a = await mem.store_memory("shared content", "session-x")

    _patch_memory_write_scope(monkeypatch, "proj-x", "cursor")
    id_b = await mem.store_memory("shared content", "session-x")

    assert id_a != id_b

    with mem.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    assert count == 2


@pytest.mark.asyncio
async def test_exact_dedup_still_works_within_same_project_and_platform(
    monkeypatch, tmp_path
):
    store_globals = MARMMemory.store_memory.__globals__["_store_memory"].__globals__
    monkeypatch.setitem(store_globals, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    _patch_memory_write_scope(monkeypatch, "proj-x", "claude-code")

    id_a = await mem.store_memory("deduplicated content", "session-x")
    id_b = await mem.store_memory("deduplicated content", "session-x")

    assert id_a == id_b

    with mem.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    assert count == 1


def test_http_smart_recall_accepts_project_and_platform_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("MARM_PROJECT", "test-proj")
    monkeypatch.setenv("MARM_PLATFORM", "claude-code")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    resp = client.post(
        "/marm_smart_recall",
        json={
            "query": "anything",
            "session_name": "main",
            "project": "test-proj",
            "platform": "claude-code",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("success", "no_results")


def test_http_smart_recall_project_filter_returns_only_matching_project(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MARM_PROJECT", "proj-a")
    monkeypatch.setenv("MARM_PLATFORM", "claude-code")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    db_path = str(tmp_path / "marm_memory.db")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = None
        _direct_insert_memory(conn, "main", "alpha recall content", project="proj-a")
        _direct_insert_memory(conn, "main", "beta recall content", project="proj-b")

    resp = client.post(
        "/marm_smart_recall",
        json={"query": "content", "search_all": True, "project": "proj-a", "detail": 3},
    )
    assert resp.status_code == 200
    results = resp.json().get("results", [])
    assert all(r["project"] == "proj-a" for r in results)
    assert any("alpha" in r["content"] for r in results)
    assert not any("beta" in r["content"] for r in results)


def test_http_smart_recall_platform_filter_returns_only_matching_platform(
    monkeypatch, tmp_path
):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    db_path = str(tmp_path / "marm_memory.db")
    with sqlite3.connect(db_path) as conn:
        _direct_insert_memory(conn, "main", "claude work", platform="claude-code")
        _direct_insert_memory(conn, "main", "cursor work", platform="cursor")

    resp = client.post(
        "/marm_smart_recall",
        json={
            "query": "work",
            "search_all": True,
            "platform": "claude-code",
            "detail": 3,
        },
    )
    assert resp.status_code == 200
    results = resp.json().get("results", [])
    assert all(r["platform"] == "claude-code" for r in results)
    assert not any(r["platform"] == "cursor" for r in results)


def test_http_smart_recall_results_include_project_and_platform_fields(
    monkeypatch, tmp_path
):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    db_path = str(tmp_path / "marm_memory.db")
    with sqlite3.connect(db_path) as conn:
        _direct_insert_memory(
            conn, "main", "tagged memory", project="my-proj", platform="vscode"
        )

    resp = client.post(
        "/marm_smart_recall",
        json={"query": "tagged", "search_all": True, "detail": 3},
    )
    assert resp.status_code == 200
    results = resp.json().get("results", [])
    assert len(results) >= 1
    r = results[0]
    assert "project" in r
    assert "platform" in r
    assert r["project"] == "my-proj"
    assert r["platform"] == "vscode"


@pytest.mark.asyncio
async def test_scoped_smart_recall_filters_system_fallback(monkeypatch, tmp_path):
    from marm_mcp_server.services import recall as recall_module

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(recall_module, "memory", mem)

    with mem.get_connection() as conn:
        _direct_insert_memory(
            conn,
            "marm_system",
            "fallback system canary",
            project=None,
            platform=None,
        )

    result = await recall_module.smart_recall(
        "canary",
        session_name="empty-session",
        project="proj-a",
        platform="claude-code",
        detail=3,
    )

    assert result["status"] == "no_results"
    assert "system_results" not in result


def test_log_entry_tags_project_and_platform_on_write(monkeypatch, tmp_path):
    monkeypatch.setenv("MARM_PROJECT", "log-proj")
    monkeypatch.setenv("MARM_PLATFORM", "claude-code")
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    resp = client.post(
        "/marm_log_entry",
        json={
            "session_name": "main",
            "entry": "2026-06-18-testing-project platform log tagging",
        },
    )
    assert resp.status_code == 200

    db_path = str(tmp_path / "marm_memory.db")
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT project, platform FROM log_entries WHERE session_name = 'main'"
        ).fetchone()

    assert row is not None
    assert row[0] == "log-proj"
    assert row[1] == "claude-code"


def test_include_logs_platform_filter_excludes_other_platforms(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    db_path = str(tmp_path / "marm_memory.db")
    with sqlite3.connect(db_path) as conn:
        _direct_insert_log(conn, "main", "claude log entry", platform="claude-code")
        _direct_insert_log(conn, "main", "cursor log entry", platform="cursor")

    resp = client.post(
        "/marm_smart_recall",
        json={
            "query": "log entry",
            "search_all": True,
            "include_logs": True,
            "platform": "claude-code",
        },
    )
    assert resp.status_code == 200
    log_results = resp.json().get("log_results", [])
    assert all(r["platform"] == "claude-code" for r in log_results)
    assert not any(r["platform"] == "cursor" for r in log_results)


def test_include_logs_project_filter_excludes_other_projects(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    db_path = str(tmp_path / "marm_memory.db")
    with sqlite3.connect(db_path) as conn:
        _direct_insert_log(conn, "main", "alpha log", project="proj-alpha")
        _direct_insert_log(conn, "main", "beta log", project="proj-beta")

    resp = client.post(
        "/marm_smart_recall",
        json={
            "query": "log",
            "search_all": True,
            "include_logs": True,
            "project": "proj-alpha",
        },
    )
    assert resp.status_code == 200
    log_results = resp.json().get("log_results", [])
    assert all(r["project"] == "proj-alpha" for r in log_results)
    assert not any(r["project"] == "proj-beta" for r in log_results)


def test_include_logs_results_contain_project_and_platform_fields(
    monkeypatch, tmp_path
):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    db_path = str(tmp_path / "marm_memory.db")
    with sqlite3.connect(db_path) as conn:
        _direct_insert_log(
            conn, "main", "tagged log", project="my-proj", platform="vscode"
        )

    resp = client.post(
        "/marm_smart_recall",
        json={"query": "tagged", "search_all": True, "include_logs": True},
    )
    assert resp.status_code == 200
    log_results = resp.json().get("log_results", [])
    assert len(log_results) >= 1
    r = log_results[0]
    assert r["project"] == "my-proj"
    assert r["platform"] == "vscode"


def _direct_insert_memory_with_embedding(
    conn, session: str, content: str, project=None, platform=None
):
    """Insert a memory row with a real (fake) embedding blob so semantic scoring fires."""
    import uuid
    from datetime import datetime, timezone

    import numpy as np

    embed_bytes = np.ones(384, dtype=np.float32).tobytes()
    conn.execute(
        """
        INSERT INTO memories
            (id, session_name, content, embedding, content_hash, timestamp,
             context_type, metadata, project, platform)
        VALUES (?, ?, ?, ?, ?, ?, 'general', '{}', ?, ?)
        """,
        (
            str(uuid.uuid4()),
            session,
            content,
            embed_bytes,
            content,
            datetime.now(timezone.utc).isoformat(),
            project,
            platform,
        ),
    )
    conn.commit()


def test_fts_candidate_ids_filter_respects_project(tmp_path):
    from marm_mcp_server.core.memory_scoring import _fetch_fts_candidate_ids

    mem = MARMMemory(str(tmp_path / "memory.db"))
    with mem.get_connection() as conn:
        _direct_insert_memory(conn, "s", "python debugging session", project="proj-a")
        _direct_insert_memory(conn, "s", "python debugging notes", project="proj-b")

    ids = _fetch_fts_candidate_ids(
        mem.db_path, None, "python debugging", 10, project="proj-a"
    )
    assert len(ids) == 1

    ids_all = _fetch_fts_candidate_ids(mem.db_path, None, "python debugging", 10)
    assert len(ids_all) == 2


def test_fts_rows_scoring_filter_respects_platform(tmp_path):
    from marm_mcp_server.core.memory_scoring import _fetch_and_score_fts_rows

    mem = MARMMemory(str(tmp_path / "memory.db"))
    with mem.get_connection() as conn:
        _direct_insert_memory(
            conn, "s", "refactor session notes", platform="claude-code"
        )
        _direct_insert_memory(conn, "s", "refactor cursor notes", platform="cursor")

    rows = _fetch_and_score_fts_rows(
        mem.db_path, None, "refactor", 10, platform="claude-code"
    )
    assert len(rows) == 1
    assert rows[0][0]["platform"] == "claude-code"


def test_embedding_rows_filter_respects_project(tmp_path):
    import numpy as np

    from marm_mcp_server.core.memory_scoring import _fetch_and_score_embedding_rows

    mem = MARMMemory(str(tmp_path / "memory.db"))
    with mem.get_connection() as conn:
        _direct_insert_memory_with_embedding(
            conn, "s", "embedding alpha", project="proj-a"
        )
        _direct_insert_memory_with_embedding(
            conn, "s", "embedding beta", project="proj-b"
        )

    query_vec = np.ones(384, dtype=np.float32)
    results, _, _ = _fetch_and_score_embedding_rows(
        mem.db_path, None, 1000, query_vec, 10, project="proj-a"
    )
    assert len(results) == 1
    assert results[0][0]["project"] == "proj-a"

    results_all, _, _ = _fetch_and_score_embedding_rows(
        mem.db_path, None, 1000, query_vec, 10
    )
    assert len(results_all) == 2


@pytest.mark.asyncio
async def test_semantic_dedup_passes_project_and_platform_to_recall(
    monkeypatch, tmp_path
):
    from marm_mcp_server.core import consolidation as cons
    from marm_mcp_server.core.consolidation import find_semantic_duplicate

    monkeypatch.setattr(cons, "MARM_PROJECT", "proj-x")
    monkeypatch.setattr(cons, "MARM_PLATFORM", "claude-code")

    captured_kwargs = {}

    async def mock_recall(query, session=None, limit=5, query_vec=None, **kwargs):
        captured_kwargs.update(kwargs)
        return []

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._load_encoder_lazily = lambda: True
    mem.recall_similar = mock_recall

    await find_semantic_duplicate(mem, "some content", "session-a", 0.92)

    assert captured_kwargs.get("project") == "proj-x"
    assert captured_kwargs.get("platform") == "claude-code"


@pytest.mark.asyncio
async def test_semantic_dedup_does_not_match_across_project_boundary(
    monkeypatch, tmp_path
):
    import numpy as np

    from marm_mcp_server.core import consolidation as cons
    from marm_mcp_server.core.consolidation import find_semantic_duplicate

    mem = MARMMemory(str(tmp_path / "memory.db"))

    with mem.get_connection() as conn:
        _direct_insert_memory_with_embedding(
            conn,
            "session-a",
            "machine learning deployment",
            project="proj-a",
            platform="claude-code",
        )

    fake_vec = np.ones(384, dtype=np.float32)
    mem._load_encoder_lazily = lambda: True
    mem._encode_sync = lambda _text: fake_vec

    monkeypatch.setattr(cons, "MARM_PROJECT", "proj-b")
    monkeypatch.setattr(cons, "MARM_PLATFORM", "claude-code")
    result_b = await find_semantic_duplicate(
        mem, "machine learning deployment", "session-a", 0.5
    )
    assert result_b is None

    monkeypatch.setattr(cons, "MARM_PROJECT", "proj-a")
    monkeypatch.setattr(cons, "MARM_PLATFORM", "claude-code")
    result_a = await find_semantic_duplicate(
        mem, "machine learning deployment", "session-a", 0.5
    )
    assert result_a is not None


@pytest.mark.asyncio
async def test_compaction_summary_inherits_source_project_and_platform(tmp_path):
    from marm_mcp_server.services.compaction_apply import apply_compaction_write

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        source_a = _direct_insert_memory(
            conn, "session-a", "source one", project="proj-a", platform="claude-code"
        )
        source_b = _direct_insert_memory(
            conn, "session-a", "source two", project="proj-a", platform="claude-code"
        )
        candidate_id = _stage_compaction_candidate(
            conn, "session-a", [source_a, source_b]
        )

    summary_id = await apply_compaction_write(mem, candidate_id)

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT project, platform FROM memories WHERE id = ?", (summary_id,)
        ).fetchone()

    assert row == ("proj-a", "claude-code")


@pytest.mark.asyncio
async def test_compaction_rejects_mixed_project_or_platform_sources(tmp_path):
    from marm_mcp_server.services.compaction_apply import apply_compaction_write

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        source_a = _direct_insert_memory(
            conn, "session-a", "source one", project="proj-a", platform="claude-code"
        )
        source_b = _direct_insert_memory(
            conn, "session-a", "source two", project="proj-b", platform="claude-code"
        )
        candidate_id = _stage_compaction_candidate(
            conn, "session-a", [source_a, source_b]
        )

    with pytest.raises(RuntimeError, match="multiple project/platform scopes"):
        await apply_compaction_write(mem, candidate_id)


@pytest.mark.asyncio
async def test_notebook_add_tags_project_and_platform(monkeypatch, tmp_path):
    from marm_mcp_server.services import notebook as nb_module

    mem = MARMMemory(str(tmp_path / "nb-test.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(nb_module, "memory", mem)
    monkeypatch.setattr(nb_module, "MARM_PROJECT", "notebook-proj")
    monkeypatch.setattr(nb_module, "MARM_PLATFORM", "vscode")

    result = await nb_module.notebook_dispatch(
        action="add", name="test-rule", data="always test your code"
    )
    assert result["status"] == "success"

    import sqlite3 as _sqlite3

    with _sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        row = conn.execute(
            "SELECT project, platform FROM notebook_entries WHERE name = 'test-rule'"
        ).fetchone()

    assert row is not None
    assert row[0] == "notebook-proj"
    assert row[1] == "vscode"


@pytest.mark.asyncio
async def test_notebook_add_null_tags_when_detection_empty(monkeypatch, tmp_path):
    from marm_mcp_server.services import notebook as nb_module

    mem = MARMMemory(str(tmp_path / "nb-test.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(nb_module, "memory", mem)
    monkeypatch.setattr(nb_module, "MARM_PROJECT", "")
    monkeypatch.setattr(nb_module, "MARM_PLATFORM", "")

    result = await nb_module.notebook_dispatch(
        action="add", name="untagged-rule", data="some rule"
    )
    assert result["status"] == "success"

    import sqlite3 as _sqlite3

    with _sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        row = conn.execute(
            "SELECT project, platform FROM notebook_entries WHERE name = 'untagged-rule'"
        ).fetchone()

    assert row is not None
    assert row[0] is None
    assert row[1] is None


@pytest.mark.asyncio
async def test_notebook_same_name_can_exist_in_different_scopes(monkeypatch, tmp_path):
    from marm_mcp_server.services import notebook as nb_module

    mem = MARMMemory(str(tmp_path / "nb-test.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(nb_module, "memory", mem)

    monkeypatch.setattr(nb_module, "MARM_PROJECT", "proj-a")
    monkeypatch.setattr(nb_module, "MARM_PLATFORM", "claude-code")
    await nb_module.notebook_dispatch(
        action="add", name="shared-rule", data="project a rule"
    )

    monkeypatch.setattr(nb_module, "MARM_PROJECT", "proj-b")
    monkeypatch.setattr(nb_module, "MARM_PLATFORM", "claude-code")
    await nb_module.notebook_dispatch(
        action="add", name="shared-rule", data="project b rule"
    )

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        rows = conn.execute(
            """
            SELECT data, project, platform
            FROM notebook_entries
            WHERE name = 'shared-rule'
            ORDER BY project
            """
        ).fetchall()

    assert rows == [
        ("project a rule", "proj-a", "claude-code"),
        ("project b rule", "proj-b", "claude-code"),
    ]


@pytest.mark.asyncio
async def test_notebook_use_prefers_current_project_scope(monkeypatch, tmp_path):
    from marm_mcp_server.services import notebook as nb_module

    mem = MARMMemory(str(tmp_path / "nb-test.db"))
    mem._encoder_failed = True
    monkeypatch.setattr(nb_module, "memory", mem)

    monkeypatch.setattr(nb_module, "MARM_PROJECT", "proj-a")
    monkeypatch.setattr(nb_module, "MARM_PLATFORM", "claude-code")
    await nb_module.notebook_dispatch(
        action="add", name="shared-rule", data="project a rule"
    )

    monkeypatch.setattr(nb_module, "MARM_PROJECT", "proj-b")
    monkeypatch.setattr(nb_module, "MARM_PLATFORM", "claude-code")
    await nb_module.notebook_dispatch(
        action="add", name="shared-rule", data="project b rule"
    )

    result = await nb_module.notebook_dispatch(
        action="use", names="shared-rule", session_name="main"
    )

    assert result["status"] == "success"
    assert result["entries"] == [{"name": "shared-rule", "data": "project b rule"}]
