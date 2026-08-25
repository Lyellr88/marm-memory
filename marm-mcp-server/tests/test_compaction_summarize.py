import json
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from marm_mcp_server.core.compaction import _compute_candidate_hash
from marm_mcp_server.core.memory import MARMMemory
from marm_mcp_server.services import compaction_summarize

centroid_extract_summary = compaction_summarize.centroid_extract_summary
process_nudge_exhausted_candidates = (
    compaction_summarize.process_nudge_exhausted_candidates
)


def _make_vec(seed: int = 0, dim: int = 384) -> np.ndarray:
    rng = np.random.default_rng(seed=seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _insert_memory(mem: MARMMemory, session: str, content: str, embedding=None) -> str:
    mem_id = str(uuid.uuid4())
    ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    emb_bytes = embedding.tobytes() if embedding is not None else None
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories "
            "(id, session_name, content, embedding, timestamp, context_type, metadata, content_hash) "
            "VALUES (?, ?, ?, ?, ?, 'general', '{}', ?)",
            (mem_id, session, content, emb_bytes, ts, f"hash-{mem_id}"),
        )
    return mem_id


def _insert_nudge_exhausted(
    mem: MARMMemory,
    session: str,
    source_ids: list,
    expires_hours: float = 168.0,
) -> str:
    row_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=expires_hours)).isoformat()
    snap = {sid: f"hash-{sid}" for sid in source_ids}
    with mem.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO compaction_staging
                (id, session_name, source_memory_ids, preview, suggested_summary,
                 status, candidate_hash, source_updated_at_snapshot,
                 expires_at, created_at, updated_at, reviewed_at)
            VALUES (?, ?, ?, ?, NULL, 'nudge_exhausted', ?, ?, ?, ?, ?, NULL)
            """,
            (
                row_id,
                session,
                json.dumps(source_ids),
                "preview",
                _compute_candidate_hash(source_ids),
                json.dumps(snap),
                expires_at,
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return row_id


def _get_staging_row(mem: MARMMemory, row_id: str):
    with mem.get_connection() as conn:
        return conn.execute(
            "SELECT status, suggested_summary FROM compaction_staging WHERE id = ?",
            (row_id,),
        ).fetchone()


class TestCentroidExtractSummary:
    def test_returns_top_n_results(self):
        memories = [(f"memory {i}", _make_vec(seed=i).tobytes()) for i in range(10)]
        result = centroid_extract_summary(memories, top_n=3)
        parts = result.split("\n\n")
        assert len(parts) == 3

    def test_fewer_than_top_n_returns_all(self):
        memories = [(f"memory {i}", _make_vec(seed=i).tobytes()) for i in range(2)]
        result = centroid_extract_summary(memories, top_n=5)
        assert len(result.split("\n\n")) == 2

    def test_no_embeddings_falls_back_to_first_n(self):
        memories = [(f"memory {i}", None) for i in range(10)]
        result = centroid_extract_summary(memories, top_n=3)
        parts = result.split("\n\n")
        assert parts == ["memory 0", "memory 1", "memory 2"]

    def test_single_memory_returns_content(self):
        memories = [("only one", _make_vec(seed=0).tobytes())]
        assert centroid_extract_summary(memories, top_n=5) == "only one"

    def test_dedup_skips_near_identical_vectors(self):
        rng = np.random.default_rng(seed=99)
        base = rng.standard_normal(384).astype(np.float32)
        base /= np.linalg.norm(base)

        def near(seed: int) -> bytes:
            noise = (
                np.random.default_rng(seed).standard_normal(384).astype(np.float32)
                * 0.005
            )
            v = base + noise
            return (v / np.linalg.norm(v)).tobytes()

        memories = [
            ("near-1", near(1)),
            ("near-2", near(2)),
            ("near-3", near(3)),
            ("different-A", _make_vec(seed=200).tobytes()),
            ("different-B", _make_vec(seed=201).tobytes()),
        ]
        result = centroid_extract_summary(memories, top_n=3, dedup_threshold=0.85)
        parts = result.split("\n\n")
        near_count = sum(1 for p in parts if p.startswith("near-"))
        assert near_count == 1
        assert len(parts) == 3

    def test_prefers_central_memories_over_outlier(self):
        dim = 384
        cluster = []
        for seed in range(5):
            rng = np.random.default_rng(seed=seed)
            base = np.zeros(dim, dtype=np.float32)
            base[0] = 1.0
            noise = rng.standard_normal(dim).astype(np.float32) * 0.05
            v = base + noise
            cluster.append((f"cluster-{seed}", (v / np.linalg.norm(v)).tobytes()))

        outlier = np.zeros(dim, dtype=np.float32)
        outlier[1] = 1.0
        memories = [*cluster, ("outlier", outlier.tobytes())]

        result = centroid_extract_summary(memories, top_n=1, dedup_threshold=1.0)
        assert result != "outlier"

    def test_mixed_embedded_and_unembedded_includes_both(self):
        memories = [
            ("with-embedding", _make_vec(seed=0).tobytes()),
            ("no-embedding", None),
        ]
        result = centroid_extract_summary(memories, top_n=5)
        assert "with-embedding" in result
        assert "no-embedding" in result

    def test_wrong_dimension_embedding_treated_as_unembedded(self):
        """A vector with a mismatched dimension is skipped and its content still appears."""
        wrong_dim = np.ones(128, dtype=np.float32).tobytes()
        memories = [
            ("good-embedding", _make_vec(seed=0).tobytes()),
            ("bad-dimension", wrong_dim),
        ]
        result = centroid_extract_summary(memories, top_n=5)
        assert "good-embedding" in result
        assert "bad-dimension" in result

    def test_all_wrong_dimension_falls_back_to_unembedded(self):
        """When all embeddings have wrong/inconsistent dims, falls back gracefully."""
        memories = [
            ("mem-A", np.ones(100, dtype=np.float32).tobytes()),
            ("mem-B", np.ones(200, dtype=np.float32).tobytes()),
        ]
        result = centroid_extract_summary(memories, top_n=5)
        assert "mem-A" in result or "mem-B" in result

    def test_wrong_dimension_first_does_not_poison_valid_embeddings(self):
        """A malformed first vector must not cause valid same-dimension vectors to be treated as unembedded."""
        wrong_dim = np.ones(128, dtype=np.float32).tobytes()
        memories = [
            ("bad-first", wrong_dim),
            ("good-A", _make_vec(seed=1).tobytes()),
            ("good-B", _make_vec(seed=2).tobytes()),
            ("good-C", _make_vec(seed=3).tobytes()),
        ]
        result = centroid_extract_summary(memories, top_n=3, dedup_threshold=1.0)
        parts = result.split("\n\n")
        good_count = sum(1 for p in parts if p.startswith("good-"))
        assert good_count == 3
        assert "bad-first" not in parts


@pytest.fixture
def mem(tmp_path):
    return MARMMemory(db_path=str(tmp_path / "test.db"))


@pytest.mark.asyncio
async def test_promotes_nudge_exhausted_to_summary_staged(mem, monkeypatch):
    """Candidates in nudge_exhausted state are promoted to summary_staged with a generated summary."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", True)
    session = "test-session"
    ids = [
        _insert_memory(mem, session, f"memory content {i}", _make_vec(seed=i))
        for i in range(4)
    ]
    candidate_id = _insert_nudge_exhausted(mem, session, ids)

    count = await process_nudge_exhausted_candidates(mem)

    assert count == 1
    row = _get_staging_row(mem, candidate_id)
    assert row[0] == "summary_staged"
    assert row[1] and len(row[1]) > 0


@pytest.mark.asyncio
async def test_generated_summary_contains_source_content(mem, monkeypatch):
    """The promoted summary contains actual content from the source memories."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", True)
    session = "test-session"
    ids = [
        _insert_memory(mem, session, f"unique content {i}", _make_vec(seed=i))
        for i in range(3)
    ]
    candidate_id = _insert_nudge_exhausted(mem, session, ids)

    await process_nudge_exhausted_candidates(mem)

    row = _get_staging_row(mem, candidate_id)
    assert any(f"unique content {i}" in row[1] for i in range(3))


@pytest.mark.asyncio
async def test_skips_expired_candidates(mem, monkeypatch):
    """Candidates past their expiry are not processed and remain nudge_exhausted."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", True)
    session = "test-session"
    ids = [
        _insert_memory(mem, session, f"mem {i}", _make_vec(seed=i)) for i in range(2)
    ]
    candidate_id = _insert_nudge_exhausted(mem, session, ids, expires_hours=-1)

    count = await process_nudge_exhausted_candidates(mem)

    assert count == 0
    assert _get_staging_row(mem, candidate_id)[0] == "nudge_exhausted"


@pytest.mark.asyncio
async def test_returns_zero_when_compaction_disabled(mem, monkeypatch):
    """Returns 0 immediately when COMPACTION_ENABLED is False."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", False)
    session = "test-session"
    ids = [
        _insert_memory(mem, session, f"mem {i}", _make_vec(seed=i)) for i in range(2)
    ]
    _insert_nudge_exhausted(mem, session, ids)

    count = await process_nudge_exhausted_candidates(mem)

    assert count == 0


@pytest.mark.asyncio
async def test_marks_stale_when_all_source_memories_missing(mem, monkeypatch):
    """Candidates whose source memories no longer exist are marked stale."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", True)
    ghost_ids = [str(uuid.uuid4()) for _ in range(3)]
    candidate_id = _insert_nudge_exhausted(mem, "test-session", ghost_ids)

    count = await process_nudge_exhausted_candidates(mem)

    assert count == 0
    assert _get_staging_row(mem, candidate_id)[0] == "stale"


@pytest.mark.asyncio
async def test_marks_stale_when_partial_source_memories_missing(mem, monkeypatch):
    """Candidates with only some source memories present are marked stale, not partially summarized."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", True)
    session = "test-session"
    real_id = _insert_memory(mem, session, "real memory", _make_vec(seed=0))
    ghost_id = str(uuid.uuid4())
    candidate_id = _insert_nudge_exhausted(mem, session, [real_id, ghost_id])

    count = await process_nudge_exhausted_candidates(mem)

    assert count == 0
    assert _get_staging_row(mem, candidate_id)[0] == "stale"


@pytest.mark.asyncio
async def test_marks_stale_when_source_ids_empty(mem, monkeypatch):
    """Malformed staging rows are terminally marked stale instead of retried forever."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", True)
    candidate_id = _insert_nudge_exhausted(mem, "test-session", [])

    count = await process_nudge_exhausted_candidates(mem)

    assert count == 0
    assert _get_staging_row(mem, candidate_id)[0] == "stale"


@pytest.mark.asyncio
async def test_source_memories_must_match_staging_session(mem, monkeypatch):
    """Server-side summaries must not pull source rows from another session."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", True)
    source_id = _insert_memory(
        mem, "source-session", "cross-session memory", _make_vec(seed=0)
    )
    candidate_id = _insert_nudge_exhausted(mem, "staging-session", [source_id])

    count = await process_nudge_exhausted_candidates(mem)

    assert count == 0
    assert _get_staging_row(mem, candidate_id)[0] == "stale"


@pytest.mark.asyncio
async def test_processes_multiple_candidates(mem, monkeypatch):
    """All eligible nudge_exhausted candidates in one pass are promoted."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", True)
    session = "test-session"
    candidate_ids = []
    for batch in range(3):
        ids = [
            _insert_memory(
                mem, session, f"batch {batch} item {i}", _make_vec(seed=batch * 10 + i)
            )
            for i in range(3)
        ]
        candidate_ids.append(_insert_nudge_exhausted(mem, session, ids))

    count = await process_nudge_exhausted_candidates(mem)

    assert count == 3
    with mem.get_connection() as conn:
        statuses = conn.execute(
            "SELECT status FROM compaction_staging WHERE id IN ({})".format(
                ",".join("?" * len(candidate_ids))
            ),
            candidate_ids,
        ).fetchall()
    assert all(row[0] == "summary_staged" for row in statuses)


@pytest.mark.asyncio
async def test_does_not_touch_other_statuses(mem, monkeypatch):
    """Only nudge_exhausted candidates are affected — pending_summary and stale are left alone."""
    monkeypatch.setattr(compaction_summarize, "COMPACTION_ENABLED", True)
    session = "test-session"
    ids = [
        _insert_memory(mem, session, f"mem {i}", _make_vec(seed=i)) for i in range(2)
    ]

    exhausted_id = _insert_nudge_exhausted(mem, session, ids)
    now = datetime.now(timezone.utc)
    staged_id = str(uuid.uuid4())
    with mem.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO compaction_staging
                (id, session_name, source_memory_ids, preview, suggested_summary,
                 status, candidate_hash, source_updated_at_snapshot,
                 expires_at, created_at, updated_at, reviewed_at)
            VALUES (?, ?, ?, ?, 'existing summary', 'summary_staged', ?, ?, ?, ?, ?, NULL)
            """,
            (
                staged_id,
                session,
                json.dumps(ids),
                "preview",
                _compute_candidate_hash(ids),
                json.dumps({sid: f"hash-{sid}" for sid in ids}),
                (now + timedelta(hours=168)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )

    await process_nudge_exhausted_candidates(mem)

    assert _get_staging_row(mem, exhausted_id)[0] == "summary_staged"
    staged_row = _get_staging_row(mem, staged_id)
    assert staged_row[0] == "summary_staged"
    assert staged_row[1] == "existing summary"
