"""A memory linked to code says whether that code has changed since."""

import asyncio
import importlib
import sys
import threading

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


def _refresh(env, root):
    from marm_mcp_server.core import code_link_queue

    code_link_queue.enqueue_refresh("graph", "memory-project", str(root))
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
