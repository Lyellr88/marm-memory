import json
import math
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from conftest import bind_live_modules

from marm_mcp_server.core.compaction import (
    find_compaction_candidates,
    run_periodic_compaction_scan,
)
from marm_mcp_server.core.memory import MARMMemory


@pytest.fixture(autouse=True)
def _live_modules(monkeypatch):
    bind_live_modules(
        monkeypatch,
        {},
        settings="marm_mcp_server.config.settings",
        memory="marm_mcp_server.core.memory",
    )


@pytest.fixture
def mem(tmp_path, monkeypatch):
    import marm_mcp_server.config.settings as s

    monkeypatch.setattr(s, "COMPACTION_ENABLED", True)
    monkeypatch.setattr(s, "COMPACTION_MIN_CLUSTER_SIZE", 3)
    monkeypatch.setattr(s, "COMPACTION_MAX_CLUSTER_SIZE", 8)
    monkeypatch.setattr(s, "COMPACTION_SIMILARITY_THRESHOLD", 0.88)
    monkeypatch.setattr(s, "COMPACTION_MIN_CONTAINMENT", 0.9)
    monkeypatch.setattr(s, "COMPACTION_MIN_AGE_HOURS", 24)
    store = MARMMemory(str(tmp_path / "memory.db"))
    store._encoder_failed = True
    return store


def _at(degrees: float, dim: int = 384) -> bytes:
    """A unit vector in the first plane: cosine between two is cos(angle)."""
    v = np.zeros(dim, dtype=np.float32)
    v[0] = math.cos(math.radians(degrees))
    v[1] = math.sin(math.radians(degrees))
    return v.tobytes()


def _insert(
    mem: MARMMemory,
    embedding: bytes,
    session: str = "sess",
    content: str = "the release plan was approved",
    mem_id: str = "",
) -> str:
    mem_id = mem_id or str(uuid.uuid4())
    ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO memories (id, session_name, content, embedding, timestamp, "
            "context_type, metadata, content_hash) "
            "VALUES (?, ?, ?, ?, ?, 'general', '{}', ?)",
            (mem_id, session, content, embedding, ts, f"hash-{mem_id}"),
        )
    return mem_id


def _rescan(mem: MARMMemory) -> None:
    with mem.get_connection() as conn:
        conn.execute("DELETE FROM compaction_session_state")
    run_periodic_compaction_scan(mem)


def _staged(mem: MARMMemory) -> list:
    with mem.get_connection() as conn:
        return [
            (json.loads(ids), status)
            for ids, status in conn.execute(
                "SELECT source_memory_ids, status FROM compaction_staging "
                "ORDER BY created_at"
            )
        ]


def _cos(a: bytes, b: bytes) -> float:
    return float(np.dot(np.frombuffer(a, np.float32), np.frombuffer(b, np.float32)))


def test_a_chain_of_neighbours_is_not_one_cluster(mem):
    # Each step is 25 degrees (cosine 0.906), so neighbours pass 0.88 and
    # anything two steps apart (cosine 0.643) does not.
    for step in range(6):
        _insert(mem, _at(25 * step))

    assert find_compaction_candidates(mem, "sess") == []


def test_every_pair_in_a_cluster_clears_the_threshold(mem):
    embeddings = {}
    for degrees in (0, 1, 2, 25, 50, 75):
        embeddings[_insert(mem, _at(degrees))] = _at(degrees)

    [cluster] = find_compaction_candidates(mem, "sess")
    ids = cluster["source_memory_ids"]

    assert len(ids) == 4
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            assert _cos(embeddings[a], embeddings[b]) >= 0.88


def test_a_cluster_never_exceeds_the_size_cap(mem, monkeypatch):
    import marm_mcp_server.config.settings as s

    monkeypatch.setattr(s, "COMPACTION_MAX_CLUSTER_SIZE", 4)
    for i in range(10):
        _insert(mem, _at(i * 0.1))

    sizes = sorted(
        len(c["source_memory_ids"]) for c in find_compaction_candidates(mem, "sess")
    )

    assert sizes == [4, 4]


def test_a_discarded_cluster_is_not_re_offered_when_it_grows(mem):
    for i in range(3):
        _insert(mem, _at(i * 0.1))
    run_periodic_compaction_scan(mem)
    with mem.get_connection() as conn:
        conn.execute("UPDATE compaction_staging SET status = 'discarded'")

    _insert(mem, _at(0.05))
    _rescan(mem)

    assert [status for _, status in _staged(mem)] == ["discarded"]


def test_a_discard_still_lets_new_memories_cluster_together(mem):
    for i in range(3):
        _insert(mem, _at(i * 0.1))
    run_periodic_compaction_scan(mem)
    with mem.get_connection() as conn:
        conn.execute("UPDATE compaction_staging SET status = 'discarded'")

    fresh = {_insert(mem, _at(90 + i * 0.1)) for i in range(3)}
    _rescan(mem)

    pending = [ids for ids, status in _staged(mem) if status == "pending_summary"]
    assert [set(ids) for ids in pending] == [fresh]


def test_a_rescan_supersedes_the_pending_candidate_it_overlaps(mem):
    for i in range(3):
        _insert(mem, _at(i * 0.1))
    run_periodic_compaction_scan(mem)
    _insert(mem, _at(0.05))
    _rescan(mem)

    staged = _staged(mem)
    assert [status for _, status in staged] == ["stale", "pending_summary"]
    assert len(staged[1][0]) == 4


def test_a_rescan_leaves_a_staged_summary_alone(mem):
    for i in range(3):
        _insert(mem, _at(i * 0.1))
    run_periodic_compaction_scan(mem)
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE compaction_staging SET status = 'summary_staged', "
            "suggested_summary = 'reviewed'"
        )

    _insert(mem, _at(0.05))
    _rescan(mem)

    assert [status for _, status in _staged(mem)] == ["summary_staged"]


@pytest.mark.asyncio
async def test_deleting_a_source_keeps_a_rejection_but_ends_a_proposal(mem):
    from marm_mcp_server.core.memory_delete import _delete_memories

    rejected = [_insert(mem, _at(i * 0.1)) for i in range(3)]
    proposed = [_insert(mem, _at(90 + i * 0.1)) for i in range(3)]
    run_periodic_compaction_scan(mem)
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE compaction_staging SET status = 'discarded' "
            "WHERE source_memory_ids LIKE ?",
            (f"%{rejected[0]}%",),
        )

    await _delete_memories(mem, [rejected[0], proposed[0]])

    assert sorted(status for _, status in _staged(mem)) == ["discarded", "stale"]


@pytest.mark.asyncio
async def test_a_pending_candidate_can_be_discarded(mem, monkeypatch):
    from marm_mcp_server.core.models import ApplyCompactionRequest
    from marm_mcp_server.endpoints import compaction as endpoint

    monkeypatch.setattr(endpoint, "memory", mem)
    for i in range(3):
        _insert(mem, _at(i * 0.1))
    run_periodic_compaction_scan(mem)
    with mem.get_connection() as conn:
        [candidate_id] = [
            r[0] for r in conn.execute("SELECT id FROM compaction_staging")
        ]

    result = await endpoint.marm_apply_compaction(
        ApplyCompactionRequest(candidate_id=candidate_id, action="discard")
    )

    assert result["status"] == "discarded"
    assert [status for _, status in _staged(mem)] == ["discarded"]


def test_replacing_a_source_keeps_a_rejection(mem):
    import asyncio

    from marm_mcp_server.core.memory_ops import _replace_memory

    ids = [_insert(mem, _at(i * 0.1)) for i in range(3)]
    run_periodic_compaction_scan(mem)
    with mem.get_connection() as conn:
        conn.execute("UPDATE compaction_staging SET status = 'discarded'")

    asyncio.run(
        _replace_memory(mem, ids[0], "edited", "sess", "general", {}, None, None)
    )

    assert [status for _, status in _staged(mem)] == ["discarded"]


def test_a_rescan_leaves_an_unchanged_exhausted_candidate_alone(mem):
    for i in range(3):
        _insert(mem, _at(i * 0.1))
    run_periodic_compaction_scan(mem)
    with mem.get_connection() as conn:
        conn.execute(
            "UPDATE compaction_staging SET status = 'nudge_exhausted', nudge_count = 5"
        )

    _rescan(mem)

    assert [status for _, status in _staged(mem)] == ["nudge_exhausted"]


def test_a_failed_insert_does_not_strand_a_superseded_candidate(mem, monkeypatch):
    from marm_mcp_server.core import compaction

    for i in range(3):
        _insert(mem, _at(i * 0.1))
    run_periodic_compaction_scan(mem)
    _insert(mem, _at(0.05))

    def fail(*_args):
        raise RuntimeError("snapshot failed")

    candidates = find_compaction_candidates(mem, "sess")
    monkeypatch.setattr(compaction, "_get_source_snapshot", fail)
    with pytest.raises(RuntimeError):
        compaction.persist_candidates_to_staging(mem, candidates)

    assert [status for _, status in _staged(mem)] == ["pending_summary"]


def test_clusters_do_not_depend_on_row_order(mem, monkeypatch):
    import marm_mcp_server.config.settings as s

    monkeypatch.setattr(s, "COMPACTION_MAX_CLUSTER_SIZE", 3)
    ids = [f"0000000{i}-0000-0000-0000-000000000000" for i in range(4)]
    for mem_id in reversed(ids):
        _insert(mem, _at(0.0), mem_id=mem_id)

    [cluster] = find_compaction_candidates(mem, "sess")

    assert sorted(cluster["source_memory_ids"]) == ids[:3]


def test_replacing_a_doc_mirror_keeps_a_rejection_but_ends_a_proposal(mem):
    import asyncio

    from marm_mcp_server.core.memory_ops import _store_doc_mirror

    mirror = _insert(mem, _at(0.0))
    with mem.get_connection() as conn:
        for row_id, status in (
            ("rejected", "discarded"),
            ("proposed", "pending_summary"),
        ):
            conn.execute(
                "INSERT INTO compaction_staging (id, session_name, source_memory_ids, "
                "preview, status, candidate_hash, source_updated_at_snapshot, "
                "expires_at, created_at, updated_at) "
                "VALUES (?, 'sess', ?, '[]', ?, ?, '{}', '2099-01-01', '', '')",
                (row_id, json.dumps([mirror]), status, row_id),
            )

    asyncio.run(
        _store_doc_mirror(
            mem, "the doc, revised", "sess", None, None, {}, existing_memory_id=mirror
        )
    )

    with mem.get_connection() as conn:
        statuses = dict(conn.execute("SELECT id, status FROM compaction_staging"))
    assert statuses == {"rejected": "discarded", "proposed": "stale"}


def test_a_pair_rejected_during_a_scan_is_not_staged(mem):
    from marm_mcp_server.core import compaction

    ids = [_insert(mem, _at(i * 0.1)) for i in range(3)]
    candidates = find_compaction_candidates(mem, "sess")
    # A reviewer rejects two of them between the scan and staging.
    with mem.get_connection() as conn:
        conn.execute(
            "INSERT INTO compaction_staging (id, session_name, source_memory_ids, "
            "preview, status, candidate_hash, source_updated_at_snapshot, "
            "expires_at, created_at, updated_at) "
            "VALUES ('rejected', 'sess', ?, '[]', 'discarded', 'other', '{}', "
            "'2099-01-01', '', '')",
            (json.dumps(ids[:2]),),
        )

    assert compaction.persist_candidates_to_staging(mem, candidates) == 0


def test_memories_that_embed_alike_but_say_different_things_do_not_cluster(mem):
    for version, codename in (
        ("1.3.0", "bedrock"),
        ("1.4.0", "fidelity"),
        ("1.5.0", "lens"),
    ):
        _insert(
            mem,
            _at(0.1),
            content=f"Release v{version} {codename} shipped with its plan",
        )

    assert find_compaction_candidates(mem, "sess") == []


def test_a_memory_restated_inside_another_clusters_with_it(mem):
    short = "relicensed to GPL-3.0-or-later in v2.2.9"
    for extra in (
        "",
        " as a derivative work",
        " as a derivative work of GPL emulators",
    ):
        _insert(mem, _at(0.1), content=short + extra)

    [cluster] = find_compaction_candidates(mem, "sess")

    assert len(cluster["source_memory_ids"]) == 3


def test_containment_zero_restores_similarity_alone(mem, monkeypatch):
    import marm_mcp_server.config.settings as s

    monkeypatch.setattr(s, "COMPACTION_MIN_CONTAINMENT", 0.0)
    for version in ("1.3.0", "1.4.0", "1.5.0"):
        _insert(mem, _at(0.1), content=f"Release v{version} shipped")

    assert len(find_compaction_candidates(mem, "sess")) == 1


def test_trailing_punctuation_does_not_change_a_token():
    from marm_mcp_server.core.compaction import _containment, _tokens

    short = _tokens("The release shipped.")
    long = _tokens("The release shipped with tests")
    assert _containment(short, long) == 1.0
    assert {"v2.2.9", "gpl-3.0-or-later"} <= _tokens(
        "Relicensed to gpl-3.0-or-later in v2.2.9."
    )
