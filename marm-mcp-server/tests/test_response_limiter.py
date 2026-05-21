from marm_mcp_server.core.response_limiter import MCPResponseLimiter


def test_response_size_estimate_matches_json_encoding():
    response = {
        "status": "success",
        "message": "plain ascii",
        "unicode": "memory cafe",
        "items": [{"id": "a", "content": "x" * 20}],
    }

    estimated = MCPResponseLimiter.estimate_response_size(response)

    assert estimated == len(
        __import__("json").dumps(response, ensure_ascii=False).encode("utf-8")
    )


def test_content_truncation_preserves_requested_side():
    content = "A" * 120

    head = MCPResponseLimiter.truncate_content(content, 40, preserve_start=True)
    tail = MCPResponseLimiter.truncate_content(content, 40, preserve_start=False)

    assert len(head) == 40
    assert head.startswith("A")
    assert head.endswith("...")
    assert len(tail) == 40
    assert tail.startswith("...")
    assert tail.endswith("A")


def test_large_memory_response_is_truncated_below_mcp_limit():
    memories = [
        {
            "id": f"mem-{index}",
            "session_name": "release-test",
            "content": f"entry-{index} " + ("x" * 80_000),
            "timestamp": "2026-05-17T00:00:00Z",
            "context_type": "general",
            "metadata": {"source": "test"},
            "similarity": 0.8,
        }
        for index in range(30)
    ]
    metadata = {
        "status": "success",
        "message": "large recall result",
        "query": "entry",
        "session_name": "release-test",
        "search_all": False,
    }

    limited, was_truncated = MCPResponseLimiter.limit_memory_response(memories, metadata)
    response = metadata | {"results": limited}

    assert was_truncated is True
    assert limited
    assert MCPResponseLimiter.estimate_response_size(response) <= MCPResponseLimiter.CONTENT_LIMIT
    assert any(memory.get("_truncated") for memory in limited)


def test_error_context_preserves_tail_when_truncated():
    memory = {
        "id": "error-1",
        "content": "start " + ("x" * 500) + " final traceback line",
        "context_type": "error",
    }

    truncated = MCPResponseLimiter.truncate_memory_content(memory, max_content_chars=80)

    assert truncated["_truncated"] is True
    assert truncated["_truncation_strategy"] == "end"
    assert truncated["content"].startswith("...")
    assert truncated["content"].endswith("final traceback line")


def test_truncation_notice_adds_machine_readable_metadata_and_message():
    response = {"status": "success", "message": "found memories"}

    limited = MCPResponseLimiter.add_truncation_notice(
        response, was_truncated=True, total_available=42
    )

    assert limited["_mcp_truncated"] is True
    assert limited["_total_available"] == 42
    assert "1MB" in limited["_truncation_reason"]
    assert "partial results" in limited["message"]


def test_empty_and_boundary_memory_responses_stay_valid():
    empty, empty_truncated = MCPResponseLimiter.limit_memory_response([], {})
    assert empty == []
    assert empty_truncated is False

    base_response = {"status": "success", "message": "boundary"}
    available = MCPResponseLimiter.CONTENT_LIMIT - MCPResponseLimiter.estimate_response_size(
        base_response | {"results": []}
    )
    memories = [
        {"id": f"boundary-{index}", "content": "b" * (available // 4), "similarity": 0.8}
        for index in range(3)
    ]

    limited, _ = MCPResponseLimiter.limit_memory_response(memories, base_response)
    response = base_response | {"results": limited}

    assert limited
    assert MCPResponseLimiter.estimate_response_size(response) <= MCPResponseLimiter.CONTENT_LIMIT
