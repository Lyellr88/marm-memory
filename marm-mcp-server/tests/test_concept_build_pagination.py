import importlib
import sys

import pytest
from conftest import load_isolated_server


@pytest.fixture
def concepts_env(monkeypatch, tmp_path):
    load_isolated_server(monkeypatch, tmp_path)
    monkeypatch.setenv("MARM_CONCEPT_DB_PATH", str(tmp_path / "marm_index.db"))
    concepts = importlib.import_module("marm_mcp_server.endpoints.concepts")
    memory_module = sys.modules["marm_mcp_server.core.memory"]
    return concepts, memory_module


def _engine():
    return importlib.import_module("marm_mcp_server.services.concept_build_engine")


def _seed(memory_module, count, session="sess-a"):
    with memory_module.memory.get_connection() as conn:
        conn.executemany(
            "INSERT INTO memories (id, session_name, content, timestamp) "
            "VALUES (?, ?, ?, datetime('now'))",
            [(f"m{i:05d}", session, f"memory content {i}") for i in range(count)],
        )


def _one_entity_per_memory(monkeypatch, concepts):
    """Name the entity after the content so each memory produces its own."""
    from marm_mcp_server.core.concept_extraction import Entity, ExtractionResult

    concept_build_engine = _engine()
    monkeypatch.setattr(
        concept_build_engine,
        "extract_entities",
        lambda content: ExtractionResult(
            entities=[Entity(content, "concept")], relationship_pairs=[]
        ),
    )


def test_build_over_1200_memories_reaches_every_row_at_default_cap(
    concepts_env, monkeypatch
):
    """The regression this feature exists to fix, at the shipped default of
    500: memory 0 is the oldest of 1,200 and must still be extracted."""
    concepts, memory_module = concepts_env
    assert _engine().CONCEPT_BUILD_ROW_CAP == 500
    _seed(memory_module, 1200)
    _one_entity_per_memory(monkeypatch, concepts)

    pages = concepts._fetch_memory_pages(
        session_name=None, project=None, search_all=True
    )
    result = concepts._run_build(pages)

    assert result["memories_processed"] == 1200
    assert result["entities_extracted"] == 1200

    concept_db = concepts._get_concept_db()
    with concept_db.get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        oldest = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE name = ?", ("memory content 0",)
        ).fetchone()[0]
    assert total == 1200
    assert oldest == 1


def test_build_stops_at_a_safe_memory_boundary_when_cancelled(
    concepts_env, monkeypatch
):
    concepts, memory_module = concepts_env
    _seed(memory_module, 3)
    _one_entity_per_memory(monkeypatch, concepts)
    checks = iter((False, True))

    result = concepts._run_build(
        concepts._fetch_memory_pages(session_name=None, project=None, search_all=True),
        cancel_requested=lambda: next(checks),
    )

    assert result["aborted"] is False
    assert result["cancelled"] is True
    assert result["memories_processed"] == 1


def test_paged_ids_match_an_unpaginated_baseline_exactly(concepts_env, monkeypatch):
    """Page boundaries must lose nothing and repeat nothing. Compared against
    the same query run as one statement, not against a hand-written list."""
    concepts, memory_module = concepts_env
    monkeypatch.setattr(_engine(), "CONCEPT_BUILD_ROW_CAP", 7)
    _seed(memory_module, 100)

    paged = [
        row[0]
        for page in concepts._fetch_memory_pages(
            session_name=None, project=None, search_all=True
        )
        for row in page
    ]
    with memory_module.memory.get_connection() as conn:
        baseline = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM memories WHERE session_name != 'marm_system' "
                "AND content IS NOT NULL AND content != '' "
                "AND (compaction_role IS NULL OR compaction_role != 'summary') "
                "ORDER BY created_at DESC, id DESC"
            ).fetchall()
        ]

    assert paged == baseline
    assert len(paged) == 100


def test_page_size_of_one_still_terminates_and_reads_everything(
    concepts_env, monkeypatch
):
    """CONCEPT_BUILD_ROW_CAP clamps to a minimum of 1. A cap of 1 makes every
    page a single row, which is the degenerate case where a keyset cursor bug
    would either loop forever or stop after the first page."""
    concepts, memory_module = concepts_env
    monkeypatch.setattr(_engine(), "CONCEPT_BUILD_ROW_CAP", 1)
    _seed(memory_module, 12)

    pages = list(
        concepts._fetch_memory_pages(session_name=None, project=None, search_all=True)
    )

    assert [len(p) for p in pages] == [1] * 12
    assert len({page[0][0] for page in pages}) == 12


def test_progress_updates_once_per_page_with_live_totals(concepts_env, monkeypatch):
    concepts, memory_module = concepts_env
    monkeypatch.setattr(_engine(), "CONCEPT_BUILD_ROW_CAP", 2)
    _seed(memory_module, 5)
    _one_entity_per_memory(monkeypatch, concepts)

    progress: list[tuple[int, int, int, int]] = []
    result = concepts._run_build(
        concepts._fetch_memory_pages(session_name=None, project=None, search_all=True),
        progress_callback=lambda *counts: progress.append(counts),
    )

    assert concepts.count_memory_rows(None, None, True) == 5
    assert [counts[0] for counts in progress] == [2, 4, 5]
    assert progress[-1] == (
        result["memories_processed"],
        result["entities_extracted"],
        result["relationships_created"],
        result["code_links_created"],
    )


def test_failed_extractions_still_report_interval_progress(concepts_env, monkeypatch):
    concepts, memory_module = concepts_env
    _seed(memory_module, 25)
    concept_build_engine = _engine()

    def fail_extraction(_content):
        raise RuntimeError("bad input")

    monkeypatch.setattr(concept_build_engine, "extract_entities", fail_extraction)
    progress: list[tuple[int, int, int, int]] = []

    result = concepts._run_build(
        concepts._fetch_memory_pages(session_name=None, project=None, search_all=True),
        progress_callback=lambda *counts: progress.append(counts),
    )

    assert result["memories_processed"] == 25
    assert progress == [(25, 0, 0, 0)]


def test_progress_callback_failure_does_not_abort_build(concepts_env, monkeypatch):
    concepts, memory_module = concepts_env
    _seed(memory_module, 5)
    _one_entity_per_memory(monkeypatch, concepts)

    def fail_progress(*_counts):
        raise RuntimeError("console disconnected")

    result = concepts._run_build(
        concepts._fetch_memory_pages(session_name=None, project=None, search_all=True),
        progress_callback=fail_progress,
    )

    assert result["memories_processed"] == 5
    assert result["entities_extracted"] == 5


def test_memories_written_during_a_build_are_not_reprocessed(concepts_env, monkeypatch):
    """Descending keyset means a row written mid-build sorts ahead of the
    cursor and is skipped, rather than shifting the window and causing a
    repeat. The queue worker re-indexes it separately."""
    concepts, memory_module = concepts_env
    monkeypatch.setattr(_engine(), "CONCEPT_BUILD_ROW_CAP", 4)
    _seed(memory_module, 8)

    seen = []
    pages = concepts._fetch_memory_pages(
        session_name=None, project=None, search_all=True
    )
    for index, page in enumerate(pages):
        seen.extend(row[0] for row in page)
        if index == 0:
            with memory_module.memory.get_connection() as conn:
                conn.execute(
                    "INSERT INTO memories (id, session_name, content, timestamp) "
                    "VALUES ('m99999', 'sess-a', 'written mid build', datetime('now'))"
                )

    assert "m99999" not in seen
    assert len(seen) == len(set(seen)) == 8
