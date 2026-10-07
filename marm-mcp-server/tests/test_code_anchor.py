"""A memory linked to code says whether that code has changed since."""

import asyncio
import importlib
import os
import sqlite3
import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone

import pytest
from conftest import load_isolated_server

from marm_mcp_server.core.code_anchor import span_hash
from marm_mcp_server.core.concept_db import ConceptDB
from marm_mcp_server.services.graph_context import get_graph_context

_SOURCE = "def apply():\n    claim()\n    write_row()\n"


def _write(root, text=_SOURCE, name="module.py"):
    (root / name).write_text("import os\n\n" + text, encoding="utf-8")


def test_the_hash_follows_the_symbol_not_its_line_numbers(tmp_path):
    _write(tmp_path)
    before = span_hash(tmp_path, "module.py", 3, 5)
    (tmp_path / "module.py").write_text(
        "import os\nimport sys\n\n\n" + _SOURCE, encoding="utf-8"
    )
    assert span_hash(tmp_path, "module.py", 5, 7) == before


def test_trailing_whitespace_and_blank_lines_do_not_count(tmp_path):
    _write(tmp_path)
    before = span_hash(tmp_path, "module.py", 3, 5)
    _write(tmp_path, "def apply():   \n\n    claim()\n    write_row()\n")
    assert span_hash(tmp_path, "module.py", 3, 6) == before


def test_a_changed_body_changes_the_hash(tmp_path):
    _write(tmp_path)
    before = span_hash(tmp_path, "module.py", 3, 5)
    _write(tmp_path, "def apply():\n    write_row()\n    claim()\n")
    assert span_hash(tmp_path, "module.py", 3, 5) != before


@pytest.mark.parametrize(
    ("file_path", "start", "end"),
    [
        ("missing.py", 1, 2),
        ("../outside.py", 1, 2),
        ("/etc/hostname", 1, 1),
        ("module.py", 0, 2),
        ("module.py", 5, 3),
        ("module.py", 90, 99),
        (None, 1, 2),
    ],
)
def test_no_hash_is_claimed_without_a_readable_span_inside_the_root(
    tmp_path, file_path, start, end
):
    root = tmp_path / "repo"
    root.mkdir()
    _write(root)
    (tmp_path / "outside.py").write_text("x = 1\n", encoding="utf-8")
    assert span_hash(root, file_path, start, end) is None


def _link(db, conn, entity_id, anchor):
    db.store_code_link(
        conn,
        entity_id,
        "module.apply",
        "graph",
        file_path="module.py",
        anchor_hash=anchor,
    )
    return conn.execute(
        "SELECT anchor_hash, code_changed_at FROM entity_code_links "
        "WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()


def test_a_link_remembers_the_code_it_was_made_against(tmp_path):
    db = ConceptDB(str(tmp_path / "marm_index.db"))
    with db.get_connection() as conn:
        entity_id, _ = db.get_or_create_entity(conn, "apply", "concept", None, "p", "m")
        assert _link(db, conn, entity_id, "aaa") == ("aaa", None)
        assert _link(db, conn, entity_id, "aaa") == ("aaa", None)

        anchor, changed_at = _link(db, conn, entity_id, "bbb")
        assert anchor == "aaa" and changed_at

        # Changed stays changed: the memory was written against the old code.
        assert _link(db, conn, entity_id, "aaa") == ("aaa", changed_at)
        # A lookup that could not hash the span says nothing either way.
        assert _link(db, conn, entity_id, None) == ("aaa", changed_at)


def test_a_link_made_without_a_hash_adopts_the_first_one_it_sees(tmp_path):
    db = ConceptDB(str(tmp_path / "marm_index.db"))
    with db.get_connection() as conn:
        entity_id, _ = db.get_or_create_entity(conn, "apply", "concept", None, "p", "m")
        assert _link(db, conn, entity_id, None) == (None, None)
        assert _link(db, conn, entity_id, "aaa") == ("aaa", None)


@pytest.fixture
def refresh_env(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(tmp_path / "marm_index.db"))
    engine = importlib.import_module("marm_mcp_server.services.concept_build_engine")
    worker_module = importlib.import_module("marm_mcp_server.core.concept_worker")
    return {
        "concept_db": engine._get_concept_db(),
        "memory": sys.modules["marm_mcp_server.core.memory"].memory,
        "worker": worker_module.ConceptIndexWorker(),
    }


def _refresh(env, root, snapshot_at="now"):
    """Refresh as a completed index would queue it; `snapshot_at` is when that
    index started reading the tree, None when no index ran."""
    from marm_mcp_server.core import code_link_queue

    if snapshot_at == "now":
        snapshot_at = datetime.now(timezone.utc).isoformat()
    code_link_queue.enqueue_refresh(
        "graph", "memory-project", str(root), snapshot_at=snapshot_at
    )
    task = code_link_queue.claim()[0]
    asyncio.run(env["worker"]._refresh_code_links(task, threading.Event()))


def test_editing_the_linked_code_marks_the_link_changed_on_the_next_refresh(
    refresh_env, monkeypatch, tmp_path
):
    from marm_mcp_server.core import code_project_bindings, graph_client

    root = tmp_path / "repo"
    root.mkdir()
    _write(root)
    with refresh_env["memory"].get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, project) "
            "VALUES ('m', 's', 'apply claims first', datetime('now'), 'memory-project')"
        )
    code_project_bindings.set_user_binding("graph", "memory-project", str(root))
    db = refresh_env["concept_db"]
    with db.get_connection() as conn:
        entity_id, _ = db.get_or_create_entity(
            conn, "apply", "concept", None, "memory-project", "m"
        )
    monkeypatch.setattr(
        graph_client,
        "find_code_match",
        lambda name, project: {
            "status": "matched",
            "qualified_name": "module.apply",
            "label": "Function",
            "file_path": "module.py",
            "start_line": 3,
            "end_line": 5,
        },
    )

    def state():
        with db.get_connection() as conn:
            return conn.execute(
                "SELECT anchor_hash IS NOT NULL, code_changed_at IS NOT NULL "
                "FROM entity_code_links WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()

    _refresh(refresh_env, root)
    assert state() == (1, 0)
    _refresh(refresh_env, root)
    assert state() == (1, 0)

    _write(root, "def apply():\n    write_row()\n    claim()\n")
    _refresh(refresh_env, root)
    assert state() == (1, 1)


def test_recall_reports_whether_linked_code_changed(monkeypatch, tmp_path):
    db_path = tmp_path / "marm_index.db"
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(db_path))
    graph = ConceptDB(str(db_path))
    with graph.get_connection() as conn:
        for name, anchors in (
            ("apply", ["aaa"]),
            ("claim", ["aaa", "bbb"]),
            ("write row", [None]),
        ):
            entity_id, _ = graph.get_or_create_entity(
                conn, name, "concept", "s", "p", "m"
            )
            for anchor in anchors:
                graph.store_code_link(
                    conn, entity_id, f"module.{name}", "graph", anchor_hash=anchor
                )
    graph.close()

    freshness = {}
    for name in ("apply", "claim", "write row"):
        context = get_graph_context(query=name, session_name="s", project="p")
        for item in context["linked_code"]:
            freshness[item["qualified_name"]] = item["freshness"]

    assert freshness == {
        "module.apply": "unchanged",
        "module.claim": "changed",
        "module.write row": "unknown",
    }


def test_re_indenting_a_symbol_keeps_its_fingerprint(tmp_path):
    _write(tmp_path)
    before = span_hash(tmp_path, "module.py", 3, 5)
    _write(
        tmp_path,
        "class Holder:\n    def apply():\n        claim()\n        write_row()\n",
    )
    assert span_hash(tmp_path, "module.py", 4, 6) == before


def test_relative_indentation_still_counts(tmp_path):
    _write(tmp_path)
    before = span_hash(tmp_path, "module.py", 3, 5)
    _write(tmp_path, "def apply():\n    claim()\nwrite_row()\n")
    assert span_hash(tmp_path, "module.py", 3, 5) != before


def test_merging_duplicates_keeps_every_link_column(tmp_path):
    from marm_mcp_server.core import concept_review

    db_path = str(tmp_path / "marm_index.db")
    db = ConceptDB(db_path)
    with db.get_connection() as conn:
        winner, _ = db.get_or_create_entity(conn, "apply", "concept", "s", "p", "m1")
        loser, _ = db.get_or_create_entity(conn, "apply()", "concept", "s", "p", "m2")
        for anchor in ("aaa", "bbb"):
            db.store_code_link(conn, loser, "module.apply", "graph", anchor_hash=anchor)
        before = conn.execute(
            "SELECT link_method, resolved_at, last_verified_at, anchor_hash, "
            "code_changed_at FROM entity_code_links WHERE entity_id = ?",
            (loser,),
        ).fetchone()
    db.close()

    concept_review.merge_entities(db_path, winner, loser, "a")

    with sqlite3.connect(db_path) as conn:
        after = conn.execute(
            "SELECT link_method, resolved_at, last_verified_at, anchor_hash, "
            "code_changed_at FROM entity_code_links WHERE entity_id = ?",
            (winner,),
        ).fetchone()
    assert after == before and after[4], "a detected change must survive a merge"


def test_recall_before_the_link_columns_are_migrated_reports_unknown(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "marm_index.db"
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(db_path))
    graph = ConceptDB(str(db_path))
    with graph.get_connection() as conn:
        entity_id, _ = graph.get_or_create_entity(
            conn, "apply", "concept", "s", "p", "m"
        )
        graph.store_code_link(conn, entity_id, "module.apply", "graph")
    graph.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE entity_code_links DROP COLUMN anchor_hash")
        conn.execute("ALTER TABLE entity_code_links DROP COLUMN code_changed_at")

    context = get_graph_context(query="apply", session_name="s", project="p")

    assert context["status"] == "available"
    assert [c["freshness"] for c in context["linked_code"]] == ["unknown"]


def test_merging_keeps_a_change_either_duplicate_saw(tmp_path):
    """Both duplicates link the same symbol; only the loser saw it change."""
    from marm_mcp_server.core import concept_review

    db_path = str(tmp_path / "marm_index.db")
    db = ConceptDB(db_path)
    with db.get_connection() as conn:
        winner, _ = db.get_or_create_entity(conn, "apply", "concept", "s", "p", "m1")
        loser, _ = db.get_or_create_entity(conn, "apply()", "concept", "s", "p", "m2")
        db.store_code_link(conn, winner, "module.apply", "graph", anchor_hash="aaa")
        for anchor in ("aaa", "bbb"):
            db.store_code_link(conn, loser, "module.apply", "graph", anchor_hash=anchor)
    db.close()

    concept_review.merge_entities(db_path, winner, loser, "a")

    with sqlite3.connect(db_path) as conn:
        anchor, changed_at = conn.execute(
            "SELECT anchor_hash, code_changed_at FROM entity_code_links "
            "WHERE entity_id = ? AND graph_qualified_name = 'module.apply'",
            (winner,),
        ).fetchone()
    assert anchor == "aaa"
    assert changed_at, "the merge discarded a detected change"


def test_no_hash_from_a_file_written_after_the_snapshot(tmp_path):
    _write(tmp_path)
    now = time.time()
    assert span_hash(tmp_path, "module.py", 3, 5, not_after=now + 5)
    assert span_hash(tmp_path, "module.py", 3, 5, not_after=now - 60) is None


def _matched_refresh_env(refresh_env, monkeypatch, tmp_path):
    from marm_mcp_server.core import code_project_bindings, graph_client

    root = tmp_path / "repo"
    root.mkdir()
    _write(root)
    with refresh_env["memory"].get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, timestamp, project) "
            "VALUES ('m', 's', 'apply claims first', datetime('now'), 'memory-project')"
        )
    code_project_bindings.set_user_binding("graph", "memory-project", str(root))
    db = refresh_env["concept_db"]
    with db.get_connection() as conn:
        entity_id, _ = db.get_or_create_entity(
            conn, "apply", "concept", None, "memory-project", "m"
        )
    monkeypatch.setattr(
        graph_client,
        "find_code_match",
        lambda name, project: {
            "status": "matched",
            "qualified_name": "module.apply",
            "label": "Function",
            "file_path": "module.py",
            "start_line": 3,
            "end_line": 5,
        },
    )

    def anchor():
        with db.get_connection() as conn:
            return conn.execute(
                "SELECT anchor_hash, code_changed_at FROM entity_code_links "
                "WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()

    return root, anchor


def test_a_refresh_skips_a_file_saved_after_its_index_started(
    refresh_env, monkeypatch, tmp_path
):
    root, anchor = _matched_refresh_env(refresh_env, monkeypatch, tmp_path)
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    os.utime(root / "module.py", None)  # saved after that index began

    _refresh(refresh_env, root, snapshot_at=started.isoformat())
    assert anchor() == (None, None), "the graph's lines may predate this save"

    _refresh(refresh_env, root)
    assert anchor()[0] is not None


def test_a_refresh_no_index_queued_takes_no_fingerprint(
    refresh_env, monkeypatch, tmp_path
):
    # A binding confirmed in the Console queues a refresh without indexing.
    root, anchor = _matched_refresh_env(refresh_env, monkeypatch, tmp_path)
    _refresh(refresh_env, root, snapshot_at=None)
    assert anchor() == (None, None)


def test_an_index_queues_its_refresh_with_the_time_it_started(monkeypatch, tmp_path):
    from marm_mcp_server.core import code_link_queue, graph_index_repository

    queued = {}
    before = datetime.now(timezone.utc)
    monkeypatch.setattr(
        graph_index_repository.R, "do_index", lambda *_: {"project": "graph"}
    )
    monkeypatch.setattr(
        graph_index_repository.code_project_bindings,
        "auto_bind",
        lambda graph, root: (
            "bound",
            types.SimpleNamespace(
                graph_project="graph", memory_project="mem", root_path=root
            ),
        ),
    )
    monkeypatch.setattr(
        code_link_queue, "enqueue_refresh", lambda *a, **k: queued.update(k)
    )
    monkeypatch.setattr(
        graph_index_repository.runtime_flags, "clear_index_blocks", lambda _r: None
    )

    graph_index_repository.index_repository(
        object(), types.SimpleNamespace(repo_path=str(tmp_path))
    )

    started = datetime.fromisoformat(queued["snapshot_at"])
    assert before <= started <= datetime.now(timezone.utc)


def test_a_new_fingerprint_version_re_anchors_instead_of_marking_changed(tmp_path):
    """Changing how spans are hashed must not flag every link as changed."""
    db = ConceptDB(str(tmp_path / "marm_index.db"))
    with db.get_connection() as conn:
        entity_id, _ = db.get_or_create_entity(conn, "apply", "concept", None, "p", "m")
        assert _link(db, conn, entity_id, "1:aaa") == ("1:aaa", None)
        assert _link(db, conn, entity_id, "2:bbb") == ("2:bbb", None)
        # A hash from before versioning carries no prefix: a different version.
        assert _link(db, conn, entity_id, "ccc") == ("ccc", None)
        anchor, changed_at = _link(db, conn, entity_id, "ddd")
        assert anchor == "ccc" and changed_at, "same version, different code"


def test_span_hash_is_versioned(tmp_path):
    _write(tmp_path)
    from marm_mcp_server.core.code_anchor import ANCHOR_VERSION

    value = span_hash(tmp_path, "module.py", 3, 5)
    assert value.startswith(f"{ANCHOR_VERSION}:")


def _save_during_read(monkeypatch, path, how):
    """Change the file while span_hash is reading it."""
    from marm_mcp_server.core import code_anchor

    real = code_anchor.itertools.islice

    def islice(handle, *args):
        out = list(real(handle, *args))
        how(path)
        return iter(out)

    monkeypatch.setattr(code_anchor.itertools, "islice", islice)


def test_a_save_during_the_read_takes_no_fingerprint(tmp_path, monkeypatch):
    _write(tmp_path)
    path = tmp_path / "module.py"

    def save(p):
        p.write_text("import os\n\ndef apply():\n    write_row()\n", encoding="utf-8")
        later = time.time() + 1
        os.utime(p, (later, later))

    _save_during_read(monkeypatch, path, save)
    # Inside the cutoff, and still refused: the file is not the one read.
    assert span_hash(tmp_path, "module.py", 3, 5, not_after=time.time() + 60) is None


def test_a_save_past_the_cutoff_during_the_read_takes_no_fingerprint(
    tmp_path, monkeypatch
):
    _write(tmp_path)
    cutoff = time.time() + 5

    def save(p):
        p.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        os.utime(p, (cutoff + 10, cutoff + 10))

    _save_during_read(monkeypatch, tmp_path / "module.py", save)
    assert span_hash(tmp_path, "module.py", 3, 5, not_after=cutoff) is None


def test_a_file_replaced_during_the_read_takes_no_fingerprint(tmp_path, monkeypatch):
    _write(tmp_path)

    def replace(p):
        fresh = p.with_name("module.py.new")
        fresh.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        st = p.stat()
        os.utime(fresh, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(fresh, p)  # same content and time, a different file

    _save_during_read(monkeypatch, tmp_path / "module.py", replace)
    assert span_hash(tmp_path, "module.py", 3, 5) is None


def test_an_undisturbed_read_still_fingerprints(tmp_path):
    _write(tmp_path)
    assert span_hash(tmp_path, "module.py", 3, 5, not_after=time.time() + 60)
