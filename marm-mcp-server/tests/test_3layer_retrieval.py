import importlib

import pytest
from conftest import load_isolated_server, local_client
from pydantic import ValidationError

import marm_mcp_server.services.recall as recall_mod
from marm_mcp_server.core.memory import MARMMemory
from marm_mcp_server.core.models import SmartRecallRequest
from marm_mcp_server.services.recall import _apply_detail_level, smart_recall


def test_apply_detail_level_1_truncates_long_content():
    content = "a" * 300
    result = _apply_detail_level(content, 1)
    assert result == "a" * 200 + "…"


def test_apply_detail_level_2_truncates_long_content():
    content = "b" * 600
    result = _apply_detail_level(content, 2)
    assert result == "b" * 500 + "…"


def test_apply_detail_level_3_returns_full_content():
    content = "c" * 1000
    assert _apply_detail_level(content, 3) is content


def test_apply_detail_level_short_content_unchanged():
    short = "short content"
    assert _apply_detail_level(short, 1) == short
    assert _apply_detail_level(short, 2) == short


def test_apply_detail_level_at_exact_limit_not_truncated():
    content = "x" * 200
    assert _apply_detail_level(content, 1) == content

    content2 = "y" * 500
    assert _apply_detail_level(content2, 2) == content2


def test_smart_recall_request_default_detail_is_1():
    req = SmartRecallRequest(query="test")
    assert req.detail == 1


def test_smart_recall_request_accepts_detail_1_to_3():
    for d in (1, 2, 3):
        req = SmartRecallRequest(query="test", detail=d)
        assert req.detail == d


def test_smart_recall_request_rejects_detail_below_1():
    with pytest.raises(ValidationError):
        SmartRecallRequest(query="test", detail=0)


def test_smart_recall_request_rejects_detail_above_3():
    with pytest.raises(ValidationError):
        SmartRecallRequest(query="test", detail=4)


@pytest.mark.asyncio
async def test_smart_recall_detail_1_caps_content_at_200_chars(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    long_content = "word " * 120
    await mem.store_memory(long_content, session="d1-test")

    original = recall_mod.memory
    recall_mod.memory = mem
    try:
        result = await smart_recall("word", session_name="d1-test", limit=5, detail=1)
    finally:
        recall_mod.memory = original

    assert result["status"] == "success"
    for r in result["results"]:
        assert len(r["content"]) <= 201


@pytest.mark.asyncio
async def test_smart_recall_detail_2_caps_content_at_500_chars(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    long_content = "word " * 120
    await mem.store_memory(long_content, session="d2-test")

    original = recall_mod.memory
    recall_mod.memory = mem
    try:
        result = await smart_recall("word", session_name="d2-test", limit=5, detail=2)
    finally:
        recall_mod.memory = original

    assert result["status"] == "success"
    for r in result["results"]:
        assert len(r["content"]) <= 501


@pytest.mark.asyncio
async def test_smart_recall_detail_3_returns_full_content(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    long_content = "word " * 120
    await mem.store_memory(long_content, session="d3-test")

    original = recall_mod.memory
    recall_mod.memory = mem
    try:
        result = await smart_recall("word", session_name="d3-test", limit=5, detail=3)
    finally:
        recall_mod.memory = original

    assert result["status"] == "success"
    for r in result["results"]:
        assert len(r["content"]) > 500


@pytest.mark.asyncio
async def test_smart_recall_response_envelope_includes_detail_level(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    await mem.store_memory("envelope check content", session="env-test")

    original = recall_mod.memory
    recall_mod.memory = mem
    try:
        result = await smart_recall(
            "envelope", session_name="env-test", limit=5, detail=2
        )
    finally:
        recall_mod.memory = original

    assert result["status"] == "success"
    assert "detail_level" in result
    assert result["detail_level"] == 2


@pytest.mark.asyncio
async def test_smart_recall_default_detail_is_1_without_explicit_arg(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    long_content = "z" * 600
    await mem.store_memory(long_content, session="default-detail")

    original = recall_mod.memory
    recall_mod.memory = mem
    try:
        result = await smart_recall("z", session_name="default-detail", limit=5)
    finally:
        recall_mod.memory = original

    assert result.get("detail_level", 1) == 1
    for r in result.get("results", []):
        assert len(r["content"]) <= 201


@pytest.mark.asyncio
async def test_no_results_envelope_includes_detail_level(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    original = recall_mod.memory
    recall_mod.memory = mem
    try:
        result = await smart_recall(
            "nonexistent query xyz", session_name="empty-session", limit=5, detail=2
        )
    finally:
        recall_mod.memory = original

    assert result["status"] == "no_results"
    assert "detail_level" in result
    assert result["detail_level"] == 2


@pytest.mark.asyncio
async def test_no_results_system_fallback_respects_detail_cap(tmp_path):
    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    long_content = "system fallback word " * 30
    await mem.store_memory(long_content, session="marm_system")

    original = recall_mod.memory
    recall_mod.memory = mem
    try:
        result = await smart_recall(
            "system fallback word",
            session_name="other-session",
            limit=5,
            detail=1,
            search_all=False,
        )
    finally:
        recall_mod.memory = original

    assert result["status"] == "no_results"
    assert "detail_level" in result
    assert result["detail_level"] == 1
    system_hits = result.get("system_results", [])
    assert len(system_hits) >= 1
    for r in system_hits:
        assert len(r["content"]) <= 201


def test_http_no_result_system_fallback_respects_detail_cap(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    import asyncio

    long_content = "http system fallback word " * 25
    memory_module = importlib.import_module("marm_mcp_server.core.memory")
    asyncio.run(memory_module.memory.store_memory_queued(long_content, "marm_system"))

    resp = client.post(
        "/marm_smart_recall",
        json={
            "query": "http system fallback word",
            "session_name": "empty-http",
            "detail": 1,
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "no_results"
    assert data.get("detail_level") == 1
    system_hits = data.get("system_results", [])
    assert len(system_hits) >= 1
    for r in system_hits:
        assert len(r["content"]) <= 201
