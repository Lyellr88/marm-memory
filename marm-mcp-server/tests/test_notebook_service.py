import sqlite3
import sys
import uuid

import pytest


@pytest.fixture
def notebook_svc(monkeypatch, tmp_path):
    for name in list(sys.modules):
        if name == "marm_mcp_server" or name.startswith("marm_mcp_server."):
            del sys.modules[name]

    monkeypatch.setenv("MARM_DB_PATH", str(tmp_path / "nb-test.db"))
    monkeypatch.setenv("MARM_ANALYTICS_DB_PATH", str(tmp_path / "nb-analytics.db"))
    monkeypatch.setenv("MARM_DOCS_DB_PATH", str(tmp_path / "nb-docs.db"))

    from marm_mcp_server.core.memory import memory
    from marm_mcp_server.services.notebook import notebook_dispatch

    monkeypatch.setattr(memory, "_encoder_failed", True)
    monkeypatch.setattr(memory, "active_notebook_entries_by_session", {})

    return notebook_dispatch, memory


@pytest.mark.asyncio
async def test_dispatch_add_saves_entry_and_returns_success(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="add", name="rule_a", data="always use snake_case")
    assert result["status"] == "success"
    assert result["name"] == "rule_a"


@pytest.mark.asyncio
async def test_dispatch_show_returns_added_entry(notebook_svc):
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="rule_b", data="keep responses short")
    result = await dispatch(action="show")
    assert result["status"] == "success"
    assert result["total_count"] == 1
    assert result["entries"][0]["name"] == "rule_b"


@pytest.mark.asyncio
async def test_dispatch_use_activates_existing_entry(notebook_svc):
    dispatch, memory = notebook_svc
    await dispatch(action="add", name="rule_c", data="cite sources")
    result = await dispatch(action="use", names="rule_c")
    assert result["status"] == "success"
    assert "rule_c" in result["activated_entries"]
    assert memory.get_active_notebook_entries("main")[0]["name"] == "rule_c"


@pytest.mark.asyncio
async def test_dispatch_status_reflects_active_entries(notebook_svc):
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="rule_d", data="be direct")
    await dispatch(action="use", names="rule_d")
    result = await dispatch(action="status")
    assert result["status"] == "success"
    assert result["active_count"] == 1
    assert "rule_d" in result["active_entries"]


@pytest.mark.asyncio
async def test_dispatch_clear_empties_active_entries(notebook_svc):
    dispatch, memory = notebook_svc
    await dispatch(action="add", name="rule_e", data="no padding")
    await dispatch(action="use", names="rule_e")
    result = await dispatch(action="clear")
    assert result["status"] == "success"
    assert result["active_count"] == 0
    assert memory.get_active_notebook_entries("main") == []


@pytest.mark.asyncio
async def test_dispatch_add_missing_name_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="add", name=None, data="some data")
    assert result["status"] == "error"
    assert "name" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_add_missing_data_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="add", name="rule_f", data=None)
    assert result["status"] == "error"
    assert "data" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_use_missing_names_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="use", names=None)
    assert result["status"] == "error"
    assert "names" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_add_blank_name_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="add", name="   ", data="some data")
    assert result["status"] == "error"
    assert "name" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_use_comma_only_names_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="use", names="  ,  ,  ")
    assert result["status"] == "error"
    assert "names" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_unknown_action_returns_error(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="explode")
    assert result["status"] == "error"
    assert "explode" in result["message"]


@pytest.mark.asyncio
async def test_dispatch_use_silently_skips_nonexistent_entries(notebook_svc):
    dispatch, memory = notebook_svc
    result = await dispatch(action="use", names="ghost_entry")
    assert result["status"] == "success"
    assert result["activated_entries"] == []
    assert memory.get_active_notebook_entries("main") == []


@pytest.mark.asyncio
async def test_dispatch_scopes_active_entries_by_session(notebook_svc):
    dispatch, memory = notebook_svc
    await dispatch(
        action="add", name="alpha_rule", data="alpha instructions", session_name="alpha"
    )
    await dispatch(
        action="add", name="beta_rule", data="beta instructions", session_name="beta"
    )

    await dispatch(action="use", names="alpha_rule", session_name="alpha")
    await dispatch(action="use", names="beta_rule", session_name="beta")

    alpha = await dispatch(action="status", session_name="alpha")
    beta = await dispatch(action="status", session_name="beta")

    assert alpha["active_entries"] == ["alpha_rule"]
    assert beta["active_entries"] == ["beta_rule"]
    assert memory.get_active_notebook_entries("alpha")[0]["name"] == "alpha_rule"
    assert memory.get_active_notebook_entries("beta")[0]["name"] == "beta_rule"


@pytest.mark.asyncio
async def test_dispatch_clear_only_clears_requested_session(notebook_svc):
    dispatch, _ = notebook_svc
    await dispatch(
        action="add", name="alpha_rule", data="alpha instructions", session_name="alpha"
    )
    await dispatch(
        action="add", name="beta_rule", data="beta instructions", session_name="beta"
    )
    await dispatch(action="use", names="alpha_rule", session_name="alpha")
    await dispatch(action="use", names="beta_rule", session_name="beta")

    cleared = await dispatch(action="clear", session_name="alpha")
    beta = await dispatch(action="status", session_name="beta")

    assert cleared["active_count"] == 0
    assert beta["active_entries"] == ["beta_rule"]


@pytest.mark.asyncio
async def test_dispatch_normalizes_session_name(notebook_svc):
    dispatch, memory = notebook_svc
    await dispatch(
        action="add", name="alpha_rule", data="alpha instructions", session_name="alpha"
    )

    await dispatch(action="use", names="alpha_rule", session_name="  alpha  ")
    result = await dispatch(action="status", session_name="alpha")

    assert result["active_entries"] == ["alpha_rule"]
    assert memory.get_active_notebook_entries("alpha")[0]["name"] == "alpha_rule"
    assert "  alpha  " not in memory.active_notebook_entries_by_session


@pytest.mark.asyncio
async def test_dispatch_blank_session_name_returns_error(notebook_svc):
    dispatch, _ = notebook_svc

    result = await dispatch(action="status", session_name="")
    padded_result = await dispatch(action="status", session_name="   ")

    assert result["status"] == "error"
    assert "session_name" in result["message"]
    assert padded_result["status"] == "error"
    assert "session_name" in padded_result["message"]


@pytest.mark.asyncio
async def test_memory_remove_active_notebook_entry_scopes_to_one_session(notebook_svc):
    """Session isolation is end-to-end: removing a deleted entry from the
    active scratchpad must only touch the session it was deleted from, not
    every session that happens to have an entry of the same name active."""
    dispatch, memory = notebook_svc
    await dispatch(
        action="add", name="shared_rule", data="alpha copy", session_name="alpha"
    )
    await dispatch(
        action="add", name="shared_rule", data="beta copy", session_name="beta"
    )
    await dispatch(action="use", names="shared_rule", session_name="alpha")
    await dispatch(action="use", names="shared_rule", session_name="beta")

    memory.remove_active_notebook_entry("shared_rule", "alpha")

    assert memory.get_active_notebook_entries("alpha") == []
    assert memory.get_active_notebook_entries("beta")[0]["name"] == "shared_rule"


@pytest.mark.asyncio
async def test_add_same_name_project_platform_different_sessions_do_not_collide(
    notebook_svc,
):
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="dup", data="alpha content", session_name="alpha")
    await dispatch(action="add", name="dup", data="beta content", session_name="beta")

    alpha_show = await dispatch(action="show", session_name="alpha")
    beta_show = await dispatch(action="show", session_name="beta")

    assert alpha_show["total_count"] == 1
    assert alpha_show["entries"][0]["preview"] == "alpha content"
    assert beta_show["total_count"] == 1
    assert beta_show["entries"][0]["preview"] == "beta content"


@pytest.mark.asyncio
async def test_show_only_returns_entries_for_requested_session(notebook_svc):
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="a1", data="alpha one", session_name="alpha")
    await dispatch(action="add", name="a2", data="alpha two", session_name="alpha")
    await dispatch(action="add", name="b1", data="beta one", session_name="beta")

    alpha_show = await dispatch(action="show", session_name="alpha")

    assert alpha_show["total_count"] == 2
    assert {e["name"] for e in alpha_show["entries"]} == {"a1", "a2"}


@pytest.mark.asyncio
async def test_use_does_not_fall_back_across_sessions(notebook_svc):
    """A scratchpad is session-local -- an entry saved under session 'alpha'
    must not be reachable via action='use' from session 'beta', even
    though project/platform match (both None)."""
    dispatch, memory = notebook_svc
    await dispatch(action="add", name="alpha-only", data="secret", session_name="alpha")

    result = await dispatch(action="use", names="alpha-only", session_name="beta")

    assert result["activated_entries"] == []
    assert memory.get_active_notebook_entries("beta") == []


@pytest.mark.asyncio
async def test_add_writes_no_embedding(notebook_svc, tmp_path):
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="no-embed", data="plain scratch text")

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        embedding = conn.execute(
            "SELECT embedding FROM notebook_entries WHERE name = 'no-embed'"
        ).fetchone()[0]
    assert embedding is None


@pytest.mark.asyncio
async def test_save_with_data_creates_doc_without_existing_scratch_entry(
    notebook_svc,
):
    dispatch, _ = notebook_svc
    result = await dispatch(
        action="save", name="new-doc", data="fresh permanent content"
    )

    assert result["status"] == "success"
    assert result["doc_id"] is not None
    assert result["mirror_status"] == "synced"


@pytest.mark.asyncio
async def test_save_without_data_promotes_existing_scratch_entry(notebook_svc):
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="promote-me", data="scratch content to promote")

    result = await dispatch(action="save", name="promote-me")

    assert result["status"] == "success"
    assert "promoted from scratch" in result["message"]


@pytest.mark.asyncio
async def test_save_without_data_and_no_scratch_entry_fails_cleanly(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(action="save", name="ghost-doc")

    assert result["status"] == "error"
    assert "ghost-doc" in result["message"]


@pytest.mark.asyncio
async def test_save_leaves_source_scratch_entry_untouched(notebook_svc, tmp_path):
    """save is a copy, not a move -- the scratch entry must survive exactly
    as it was."""
    dispatch, _ = notebook_svc
    await dispatch(action="add", name="copy-not-move", data="original scratch")

    await dispatch(action="save", name="copy-not-move")

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        row = conn.execute(
            "SELECT data FROM notebook_entries WHERE name = 'copy-not-move'"
        ).fetchone()
    assert row is not None
    assert row[0] == "original scratch"


@pytest.mark.asyncio
async def test_save_twice_updates_existing_doc_not_duplicate(notebook_svc, tmp_path):
    dispatch, _ = notebook_svc
    first = await dispatch(action="save", name="resaved", data="version one")
    second = await dispatch(action="save", name="resaved", data="version two")

    assert first["doc_id"] == second["doc_id"]

    with sqlite3.connect(str(tmp_path / "nb-docs.db")) as conn:
        rows = conn.execute(
            "SELECT content FROM docs WHERE name = 'resaved'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "version two"


@pytest.mark.asyncio
async def test_save_resave_replaces_mirror_row_in_place(notebook_svc, tmp_path):
    """Resave must reuse the same memories row id rather than leaving a
    stale duplicate mirror behind."""
    dispatch, _ = notebook_svc
    first = await dispatch(action="save", name="stable-mirror", data="version one")
    second = await dispatch(action="save", name="stable-mirror", data="version two")

    assert first["mirror_status"] == "synced"
    assert second["mirror_status"] == "synced"
    assert first["memory_id"] == second["memory_id"]

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        rows = conn.execute(
            "SELECT content, context_type FROM memories WHERE id = ?",
            (second["memory_id"],),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "version two"
    assert rows[0][1] == "doc"


@pytest.mark.asyncio
async def test_save_resave_marks_staged_compaction_candidates_stale(
    notebook_svc, tmp_path
):
    """_store_doc_mirror's replace branch overwrites the mirror memory row
    in place, just like core/compaction.py's _replace_memory -- but unlike
    _replace_memory, it wasn't marking active compaction_staging rows that
    reference that memory id as stale. Without this, a resave could silently
    leave a staged summary pointing at content that no longer exists,
    letting marm_apply_compaction_summary later apply a summary against
    changed content."""
    dispatch, _ = notebook_svc
    first = await dispatch(
        action="save", name="staged-doc", data="version one -- pre-resave"
    )
    assert first["mirror_status"] == "synced"
    memory_id = first["memory_id"]

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        conn.execute(
            """
            INSERT INTO compaction_staging (
                id, session_name, source_memory_ids, preview, suggested_summary,
                status, candidate_hash, source_updated_at_snapshot,
                expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "candidate-doc-mirror",
                "main",
                f'["{memory_id}"]',
                "version one -- pre-resave",
                "a suggested summary",
                "pending_summary",
                "hash-doesnt-matter",
                "{}",
                "2099-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()

    second = await dispatch(
        action="save", name="staged-doc", data="version two -- post-resave"
    )
    assert second["mirror_status"] == "synced"
    assert second["memory_id"] == memory_id

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        status = conn.execute(
            "SELECT status FROM compaction_staging WHERE id = ?",
            ("candidate-doc-mirror",),
        ).fetchone()[0]
    assert status == "stale", (
        "compaction_staging candidate referencing the resaved doc's memory "
        "id must be invalidated, matching _replace_memory's behavior"
    )


@pytest.mark.asyncio
async def test_save_rejects_reserved_marm_system_session(notebook_svc):
    dispatch, _ = notebook_svc
    result = await dispatch(
        action="save", name="bad", data="content", session_name="marm_system"
    )

    assert result["status"] == "error"
    assert "marm_system" in result["message"]


@pytest.mark.asyncio
async def test_save_mirror_write_failure_still_saves_doc_as_pending(
    notebook_svc, monkeypatch, tmp_path
):
    dispatch, memory = notebook_svc

    async def _boom(*args, **kwargs):
        raise RuntimeError("write queue unavailable")

    monkeypatch.setattr(memory, "store_doc_mirror", _boom)

    result = await dispatch(action="save", name="mirror-fails", data="durable content")

    assert result["status"] == "success"
    assert result["mirror_status"] == "pending"
    assert result["doc_id"] is not None
    assert result["memory_id"] is None

    with sqlite3.connect(str(tmp_path / "nb-docs.db")) as conn:
        row = conn.execute(
            "SELECT content, memory_id FROM docs WHERE name = 'mirror-fails'"
        ).fetchone()
    assert row[0] == "durable content"
    assert row[1] is None

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM memories WHERE context_type = 'doc'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
async def test_save_preserves_session_project_platform_on_mirror(
    notebook_svc, tmp_path
):
    dispatch, _ = notebook_svc
    result = await dispatch(
        action="save",
        name="scoped-doc",
        data="scoped content",
        session_name="proj-session",
        project="marm",
        platform="claude-code",
    )

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        row = conn.execute(
            "SELECT session_name, project, platform FROM memories WHERE id = ?",
            (result["memory_id"],),
        ).fetchone()
    assert row == ("proj-session", "marm", "claude-code")


@pytest.mark.asyncio
async def test_save_reports_pending_when_docs_memory_id_link_fails(
    notebook_svc, tmp_path, monkeypatch
):
    """A set_memory_id failure must not escape _save.

    The docs row is already committed at that point, so raising would report
    total failure for a save that durably succeeded, and would drop the
    mirror_status the caller uses to know a repair is owed.
    """
    dispatch, _ = notebook_svc
    from marm_mcp_server.core.docs_db import DocsDB

    def boom(self, conn, doc_id, memory_id):
        raise sqlite3.OperationalError("docs db is locked")

    monkeypatch.setattr(DocsDB, "set_memory_id", boom)
    result = await dispatch(action="save", name="link-fail", data="durable content")

    assert result["status"] == "success"
    assert result["mirror_status"] == "pending"

    with sqlite3.connect(str(tmp_path / "nb-docs.db")) as conn:
        row = conn.execute(
            "SELECT content, memory_id FROM docs WHERE name = 'link-fail'"
        ).fetchone()
    assert row[0] == "durable content"
    assert row[1] is None

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        mirrors = conn.execute(
            "SELECT id, content FROM memories WHERE context_type = 'doc'"
        ).fetchall()
    assert len(mirrors) == 1
    assert mirrors[0][1] == "durable content"
    assert result["memory_id"] == mirrors[0][0]


@pytest.mark.asyncio
async def test_save_after_failed_link_repairs_instead_of_duplicating_mirror(
    notebook_svc, tmp_path, monkeypatch
):
    """The whole point of the pending status: the next save must repair.

    With docs.memory_id still NULL, the resave passes existing_memory_id=None.
    Before store_doc_mirror resolved the orphan by metadata.doc_id, that created
    a second mirror row for one doc on every subsequent save.
    """
    dispatch, _ = notebook_svc
    from marm_mcp_server.core.docs_db import DocsDB

    original = DocsDB.set_memory_id

    def boom(self, conn, doc_id, memory_id):
        raise sqlite3.OperationalError("docs db is locked")

    monkeypatch.setattr(DocsDB, "set_memory_id", boom)
    first = await dispatch(action="save", name="repairable", data="version one")
    assert first["mirror_status"] == "pending"

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        orphan_id = conn.execute(
            "SELECT id FROM memories WHERE context_type = 'doc'"
        ).fetchone()[0]

    monkeypatch.setattr(DocsDB, "set_memory_id", original)
    second = await dispatch(action="save", name="repairable", data="version two")

    assert second["mirror_status"] == "synced"
    assert second["doc_id"] == first["doc_id"]
    assert second["memory_id"] == orphan_id

    with sqlite3.connect(str(tmp_path / "nb-test.db")) as conn:
        mirrors = conn.execute(
            "SELECT id, content FROM memories WHERE context_type = 'doc'"
        ).fetchall()
    assert len(mirrors) == 1
    assert mirrors[0] == (orphan_id, "version two")

    with sqlite3.connect(str(tmp_path / "nb-docs.db")) as conn:
        linked = conn.execute(
            "SELECT memory_id FROM docs WHERE name = 'repairable'"
        ).fetchone()[0]
    assert linked == orphan_id


@pytest.mark.asyncio
async def test_save_with_dangling_link_reuses_a_surviving_duplicate_mirror(
    notebook_svc, tmp_path
):
    """A stale docs.memory_id must not add a mirror when one already survives.

    Reaching this needs a doc that already has two mirrors, which only an
    install predating the doc_id resolve can have. Deleting the linked one
    leaves docs.memory_id dangling, and resolving by doc_id only when the
    caller passed no id at all skipped the survivor and inserted a third row.
    """
    dispatch, _ = notebook_svc
    first = await dispatch(action="save", name="dupe", data="version one")
    linked_id = first["memory_id"]
    db = str(tmp_path / "nb-test.db")

    duplicate_id = str(uuid.uuid4())
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO memories
                (id, session_name, content, embedding, content_hash, timestamp,
                 context_type, metadata, project, platform)
            SELECT ?, session_name, content, embedding, content_hash, timestamp,
                   context_type, metadata, project, platform
            FROM memories WHERE id = ?
            """,
            (duplicate_id, linked_id),
        )
        conn.execute("DELETE FROM memories WHERE id = ?", (linked_id,))
        conn.commit()

    second = await dispatch(action="save", name="dupe", data="version two")

    assert second["memory_id"] == duplicate_id
    with sqlite3.connect(db) as conn:
        mirrors = conn.execute(
            "SELECT id, content FROM memories WHERE context_type = 'doc'"
        ).fetchall()
    assert mirrors == [(duplicate_id, "version two")]

    with sqlite3.connect(str(tmp_path / "nb-docs.db")) as conn:
        linked = conn.execute(
            "SELECT memory_id FROM docs WHERE name = 'dupe'"
        ).fetchone()[0]
    assert linked == duplicate_id


@pytest.mark.asyncio
async def test_repeated_saves_converge_on_one_of_two_duplicate_mirrors(
    notebook_svc, tmp_path, monkeypatch
):
    """Resolution must be stable across saves, not just within one save.

    The resolve reads a column the write then mutates, so ordering by timestamp
    made each save pick whichever duplicate it had not just touched, alternating
    between them and leaving whichever it skipped stale.
    """
    dispatch, _ = notebook_svc
    from marm_mcp_server.core.docs_db import DocsDB

    first = await dispatch(action="save", name="tie", data="version one")
    db = str(tmp_path / "nb-test.db")

    clones = [str(uuid.uuid4()) for _ in range(2)]
    with sqlite3.connect(db) as conn:
        for clone_id in clones:
            conn.execute(
                """
                INSERT INTO memories
                    (id, session_name, content, embedding, content_hash, timestamp,
                     context_type, metadata, project, platform)
                SELECT ?, session_name, content, embedding, content_hash, timestamp,
                       context_type, metadata, project, platform
                FROM memories WHERE id = ?
                """,
                (clone_id, first["memory_id"]),
            )
        conn.execute("DELETE FROM memories WHERE id = ?", (first["memory_id"],))
        conn.commit()

    def boom(self, conn, doc_id, memory_id):
        raise sqlite3.OperationalError("docs db is locked")

    monkeypatch.setattr(DocsDB, "set_memory_id", boom)

    written = []
    for n in range(2, 6):
        await dispatch(action="save", name="tie", data=f"version {n}")
        with sqlite3.connect(db) as conn:
            written.append(
                conn.execute(
                    "SELECT id FROM memories WHERE context_type = 'doc' AND content = ?",
                    (f"version {n}",),
                ).fetchone()[0]
            )

    assert len(set(written)) == 1, f"saves alternated between duplicates: {written}"
    with sqlite3.connect(db) as conn:
        rows = dict(
            conn.execute(
                "SELECT id, content FROM memories WHERE context_type = 'doc'"
            ).fetchall()
        )
    assert rows[written[0]] == "version 5"
    other = next(c for c in clones if c != written[0])
    assert rows[other] == "version one"
