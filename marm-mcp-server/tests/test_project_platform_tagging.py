"""Tests for project/platform schema additions.

Covers:
- Memory write tagging (project and platform columns populated)
- Scoped recall excludes rows from other projects/platforms
- Consolidation dedup does not cross project/platform boundaries
- HTTP marm_smart_recall schema accepts and filters by project/platform
- Log entry write tagging and include_logs filtering
"""

import pytest
import sqlite3

from marm_mcp_server.core.memory import MARMMemory

from conftest import load_isolated_server, local_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _direct_insert_memory(
    conn, session: str, content: str, project=None, platform=None
):
    """Insert a memory row directly with explicit project/platform values."""
    import uuid
    from datetime import datetime, timezone

    conn.execute(
        """
        INSERT INTO memories
            (id, session_name, content, embedding, content_hash, timestamp,
             context_type, metadata, project, platform)
        VALUES (?, ?, ?, NULL, ?, ?, 'general', '{}', ?, ?)
        """,
        (
            str(uuid.uuid4()),
            session,
            content,
            content,
            datetime.now(timezone.utc).isoformat(),
            project,
            platform,
        ),
    )
    conn.commit()


def _direct_insert_log(conn, session: str, topic: str, project=None, platform=None):
    """Insert a log_entry row directly with explicit project/platform values."""
    import uuid
    from datetime import datetime, timezone

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


# ---------------------------------------------------------------------------
# 1. Write tagging — memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_insert_tags_project_and_platform(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory_ops as ops

    monkeypatch.setattr(ops, "MARM_PROJECT", "test-project")
    monkeypatch.setattr(ops, "MARM_PLATFORM", "claude-code")

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
    from marm_mcp_server.core import memory_ops as ops

    monkeypatch.setattr(ops, "MARM_PROJECT", "")
    monkeypatch.setattr(ops, "MARM_PLATFORM", "")

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    mid = await mem.store_memory("untagged memory", "session-a")

    with mem.get_connection() as conn:
        row = conn.execute(
            "SELECT project, platform FROM memories WHERE id = ?", (mid,)
        ).fetchone()

    assert row[0] is None
    assert row[1] is None


# ---------------------------------------------------------------------------
# 2. Scoped recall
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_project_filter_excludes_other_projects(monkeypatch, tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    with mem.get_connection() as conn:
        _direct_insert_memory(
            conn, "session-a", "alpha content", project="project-alpha"
        )
        _direct_insert_memory(conn, "session-a", "beta content", project="project-beta")

    results = await mem.recall_text_search(
        "content", session=None, limit=10, project="project-alpha"
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

    results = await mem.recall_text_search(
        "memory", session=None, limit=10, platform="claude-code"
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

    results = await mem.recall_text_search("content", session=None, limit=10)

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

    results = await mem.recall_text_search(
        "match", session=None, limit=10, project="proj-a", platform="claude-code"
    )

    # Only the first row matches both filters
    assert len(results) == 1
    assert results[0]["content"] == "match"


# ---------------------------------------------------------------------------
# 3. Consolidation does not cross project/platform boundaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exact_dedup_does_not_cross_project_boundary(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory_ops as ops
    from marm_mcp_server.core import consolidation as cons

    monkeypatch.setattr(ops, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    monkeypatch.setattr(ops, "MARM_PROJECT", "project-a")
    monkeypatch.setattr(ops, "MARM_PLATFORM", "claude-code")
    monkeypatch.setattr(cons, "MARM_PROJECT", "project-a")
    monkeypatch.setattr(cons, "MARM_PLATFORM", "claude-code")
    id_a = await mem.store_memory("identical content", "session-x")

    monkeypatch.setattr(ops, "MARM_PROJECT", "project-b")
    monkeypatch.setattr(ops, "MARM_PLATFORM", "claude-code")
    monkeypatch.setattr(cons, "MARM_PROJECT", "project-b")
    monkeypatch.setattr(cons, "MARM_PLATFORM", "claude-code")
    id_b = await mem.store_memory("identical content", "session-x")

    # Different projects — must not deduplicate
    assert id_a != id_b

    with mem.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    assert count == 2


@pytest.mark.asyncio
async def test_exact_dedup_does_not_cross_platform_boundary(monkeypatch, tmp_path):
    from marm_mcp_server.core import memory_ops as ops
    from marm_mcp_server.core import consolidation as cons

    monkeypatch.setattr(ops, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    monkeypatch.setattr(ops, "MARM_PROJECT", "proj-x")
    monkeypatch.setattr(ops, "MARM_PLATFORM", "claude-code")
    monkeypatch.setattr(cons, "MARM_PROJECT", "proj-x")
    monkeypatch.setattr(cons, "MARM_PLATFORM", "claude-code")
    id_a = await mem.store_memory("shared content", "session-x")

    monkeypatch.setattr(ops, "MARM_PROJECT", "proj-x")
    monkeypatch.setattr(ops, "MARM_PLATFORM", "cursor")
    monkeypatch.setattr(cons, "MARM_PROJECT", "proj-x")
    monkeypatch.setattr(cons, "MARM_PLATFORM", "cursor")
    id_b = await mem.store_memory("shared content", "session-x")

    # Same project but different platform — must not deduplicate
    assert id_a != id_b

    with mem.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    assert count == 2


@pytest.mark.asyncio
async def test_exact_dedup_still_works_within_same_project_and_platform(
    monkeypatch, tmp_path
):
    from marm_mcp_server.core import memory_ops as ops
    from marm_mcp_server.core import consolidation as cons

    monkeypatch.setattr(ops, "CONSOLIDATION_ENABLED", True)
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    for module in (ops, cons):
        monkeypatch.setattr(module, "MARM_PROJECT", "proj-x")
        monkeypatch.setattr(module, "MARM_PLATFORM", "claude-code")

    id_a = await mem.store_memory("deduplicated content", "session-x")
    id_b = await mem.store_memory("deduplicated content", "session-x")

    # Same project + platform + session — must deduplicate
    assert id_a == id_b

    with mem.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    assert count == 1


# ---------------------------------------------------------------------------
# 4. HTTP — schema and filtering
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 5. Log entry tagging and include_logs filtering
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 6. FTS and embedding-level scoring function filters
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 7. Semantic consolidation isolation
# ---------------------------------------------------------------------------


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

    # Scoped to proj-b — no match
    monkeypatch.setattr(cons, "MARM_PROJECT", "proj-b")
    monkeypatch.setattr(cons, "MARM_PLATFORM", "claude-code")
    result_b = await find_semantic_duplicate(
        mem, "machine learning deployment", "session-a", 0.5
    )
    assert result_b is None

    # Scoped to proj-a — finds the row
    monkeypatch.setattr(cons, "MARM_PROJECT", "proj-a")
    monkeypatch.setattr(cons, "MARM_PLATFORM", "claude-code")
    result_a = await find_semantic_duplicate(
        mem, "machine learning deployment", "session-a", 0.5
    )
    assert result_a is not None


# ---------------------------------------------------------------------------
# 8. Notebook tagging
# ---------------------------------------------------------------------------


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
