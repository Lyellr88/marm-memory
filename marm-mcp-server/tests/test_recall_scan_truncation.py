"""A truncated recall scan has to say so in terms a caller can act on.

`recall_scan_truncated` has been in this payload all along and nothing ever
read it, because a bare boolean says what happened and not what it means. When
the scan truncates, recall answered from the most recent `scan_limit` memories
only -- older ones were never scored, so a perfect match can be missing with no
other symptom at all.
"""

from __future__ import annotations

import numpy as np
import pytest

from marm_mcp_server.core import memory_recall as R
from marm_mcp_server.core.memory import memory


async def _recall(monkeypatch, truncated: bool, limit: int = 3):
    """Drive the semantic fallback and force its truncation verdict.

    Forced rather than provoked: which lane a query takes depends on whether
    FTS finds scoreable candidates, so steering it by choice of words tests the
    lane selector, not the reporting this file is about.
    """

    def fake_scan(*args, **kwargs):
        row = {
            "id": "m1",
            "session_name": "s",
            "content": "c",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "context_type": "general",
            "metadata": None,
            "project": None,
            "platform": None,
        }
        return [(row, 0.9)], 0, truncated

    monkeypatch.setattr(R, "_fetch_and_score_embedding_rows", fake_scan)
    # No lexical candidates -> the semantic fallback is the lane taken.
    monkeypatch.setattr(R, "_fetch_fts_candidate_ids", lambda *a, **k: [])
    monkeypatch.setattr(memory, "_load_encoder_lazily", lambda: True)
    monkeypatch.setattr(
        memory, "_encode_sync", lambda text: np.ones(512, dtype=np.float32)
    )
    return await memory.recall_similar(
        "anything", limit=limit, include_scan_metadata=True, exact_mode="semantic"
    )


@pytest.mark.asyncio
async def test_a_truncated_scan_explains_itself_and_names_the_way_out(monkeypatch):
    _, meta = await _recall(monkeypatch, truncated=True)

    assert meta["recall_scan_truncated"] is True
    note = meta.get("recall_scan_note")
    assert note, "a truncated scan reported no note"
    # The two things a caller can actually do about it.
    assert "project" in note
    assert "RECALL_SCAN_LIMIT" in note


@pytest.mark.asyncio
async def test_an_untruncated_scan_adds_no_noise(monkeypatch):
    _, meta = await _recall(monkeypatch, truncated=False)

    assert meta["recall_scan_truncated"] is False
    assert "recall_scan_note" not in meta


@pytest.mark.asyncio
async def test_truncation_is_also_logged_where_an_operator_would_see_it(monkeypatch):
    """The payload reaches the agent; the log reaches whoever runs the server.
    A silent degradation needs both, because the person who can raise the limit
    is not the one reading the JSON."""
    lines: list[str] = []
    monkeypatch.setattr(R, "_safe_print", lambda msg: lines.append(str(msg)))

    await _recall(monkeypatch, truncated=True)
    assert any("scan truncated" in line.lower() for line in lines), lines


@pytest.mark.asyncio
async def test_an_untruncated_scan_logs_nothing(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(R, "_safe_print", lambda msg: lines.append(str(msg)))

    await _recall(monkeypatch, truncated=False)
    assert not any("scan truncated" in line.lower() for line in lines), lines


def test_the_scan_really_does_truncate_at_the_limit(tmp_path):
    """Pins the premise: without this, the tests above assert the reporting of
    a condition that might no longer occur."""
    import sqlite3

    from marm_mcp_server.core.memory_scoring import _fetch_and_score_embedding_rows

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE memories (id TEXT, session_name TEXT, content TEXT, "
        "embedding BLOB, timestamp TEXT, context_type TEXT, metadata TEXT, "
        "project TEXT, platform TEXT, compaction_role TEXT)"
    )
    conn.execute("CREATE TABLE memory_chunks (memory_id TEXT, embedding BLOB)")
    vec = np.ones(512, dtype=np.float32).tobytes()
    for i in range(20):
        conn.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"m{i}",
                "s",
                "c",
                vec,
                f"2026-01-{i + 1:02d}",
                "general",
                None,
                None,
                None,
                None,
            ),
        )
    conn.commit()
    conn.close()

    q = np.ones(512, dtype=np.float32)
    _, _, truncated_small = _fetch_and_score_embedding_rows(str(db), None, 5, q, 3)
    _, _, truncated_large = _fetch_and_score_embedding_rows(str(db), None, 500, q, 3)
    assert truncated_small is True
    assert truncated_large is False
