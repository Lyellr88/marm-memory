"""A pinned reference time makes recall scores independent of the wall clock."""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import marm_mcp_server.core.memory_recall as memory_recall_module
from marm_mcp_server.config import settings
from marm_mcp_server.core.memory import MARMMemory

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Clock(datetime):
    offset = timedelta(0)

    @classmethod
    def now(cls, tz=None):
        return _BASE + timedelta(days=40) + cls.offset


def _store(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True
    vec = np.ones(384, dtype=np.float32)
    vec /= np.linalg.norm(vec)
    with sqlite3.connect(str(tmp_path / "memory.db")) as conn:
        for days in (3, 30):
            mid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO memories (id, session_name, content, timestamp, "
                "context_type, metadata, embedding) VALUES (?, 'clock', "
                "'reference time keyword', ?, 'general', '{}', ?)",
                (mid, (_BASE + timedelta(days=days)).isoformat(), vec.tobytes()),
            )
            conn.execute(
                "INSERT INTO memories_fts(rowid, content) "
                "SELECT rowid, content FROM memories WHERE id = ?",
                (mid,),
            )
    return mem, vec


async def _semantic(mem, vec):
    rows = await mem.recall_similar(
        "reference time keyword", session="clock", limit=5, query_vec=vec.copy()
    )
    return sorted((r["id"], round(r["similarity"], 9)) for r in rows)


async def _fallback(mem, _vec):
    rows = await memory_recall_module._recall_text_search(
        mem, "reference time keyword", session="clock", apply_temporal=True
    )
    return sorted((r["id"], round(r["similarity"], 9)) for r in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", [_semantic, _fallback])
async def test_scores_move_with_the_clock_when_nothing_is_pinned(
    tmp_path, monkeypatch, lane
):
    monkeypatch.setattr(memory_recall_module, "datetime", _Clock)
    monkeypatch.setattr(memory_recall_module, "RECALL_REFERENCE_TIME", None)
    mem, vec = _store(tmp_path)

    monkeypatch.setattr(_Clock, "offset", timedelta(0))
    first = await lane(mem, vec)
    monkeypatch.setattr(_Clock, "offset", timedelta(days=10))
    second = await lane(mem, vec)

    assert first and first != second


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", [_semantic, _fallback])
async def test_a_pinned_reference_time_gives_identical_scores_as_the_clock_moves(
    tmp_path, monkeypatch, lane
):
    monkeypatch.setattr(memory_recall_module, "datetime", _Clock)
    monkeypatch.setattr(
        memory_recall_module, "RECALL_REFERENCE_TIME", _BASE + timedelta(days=40)
    )
    mem, vec = _store(tmp_path)

    monkeypatch.setattr(_Clock, "offset", timedelta(0))
    first = await lane(mem, vec)
    monkeypatch.setattr(_Clock, "offset", timedelta(days=10))
    second = await lane(mem, vec)

    assert first and first == second


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        ("2026-01-01T00:00:00Z", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ("2026-01-01T00:00:00", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ("2026-01-01T05:00:00+05:00", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ("not a time", None),
    ],
)
def test_the_reference_time_setting_parses_iso_8601_as_utc(raw, expected):
    assert settings._parse_reference_time(raw) == expected
