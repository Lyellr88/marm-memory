import time

import pytest

from marm_mcp_server.core.rate_limiter import IPRateLimiter


# ---------------------------------------------------------------------------
# Removal regression — get_stats() was deleted in this PR
# ---------------------------------------------------------------------------

def test_get_stats_method_was_removed():
    """get_stats() was deleted in this PR and must not exist on IPRateLimiter."""
    limiter = IPRateLimiter()
    assert not hasattr(limiter, "get_stats"), (
        "get_stats() must be removed from IPRateLimiter"
    )


def test_rate_limiter_blocks_only_after_configured_threshold_and_then_unblocks():
    limiter = IPRateLimiter()
    limiter.limits["default"] = {"requests": 2, "window": 60, "block_duration": 1}

    assert limiter.is_allowed("203.0.113.10", "default") == (True, None)
    assert limiter.is_allowed("203.0.113.10", "default") == (True, None)

    allowed, reason = limiter.is_allowed("203.0.113.10", "default")
    assert allowed is False
    assert "Rate limit exceeded: 2 requests per 60s" in reason

    allowed, reason = limiter.is_allowed("203.0.113.10", "default")
    assert allowed is False
    assert "IP blocked" in reason

    limiter.blocked_ips["203.0.113.10"] = 0
    limiter.request_buckets["203.0.113.10"].clear()
    assert limiter.is_allowed("203.0.113.10", "default") == (True, None)


def test_rate_limiter_isolated_by_ip_and_endpoint_type():
    limiter = IPRateLimiter()
    limiter.limits["memory_heavy"] = {"requests": 1, "window": 60, "block_duration": 10}

    assert limiter.is_allowed("203.0.113.20", "memory_heavy") == (True, None)
    blocked, _ = limiter.is_allowed("203.0.113.20", "memory_heavy")

    assert blocked is False
    assert limiter.is_allowed("203.0.113.21", "memory_heavy") == (True, None)
    allowed, reason = limiter.is_allowed("203.0.113.20", "default")
    assert allowed is False
    assert "IP blocked" in reason


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------

def test_is_allowed_first_request_is_always_permitted():
    limiter = IPRateLimiter()
    allowed, reason = limiter.is_allowed("10.0.0.1")
    assert allowed is True
    assert reason is None


def test_block_reason_contains_remaining_seconds():
    """The block message must include a numeric duration so clients can back off."""
    limiter = IPRateLimiter()
    limiter.limits["default"] = {"requests": 1, "window": 60, "block_duration": 30}

    limiter.is_allowed("10.0.0.2", "default")   # consume the one allowed request
    limiter.is_allowed("10.0.0.2", "default")   # trigger block

    allowed, reason = limiter.is_allowed("10.0.0.2", "default")
    assert allowed is False
    assert reason is not None
    assert any(ch.isdigit() for ch in reason), (
        f"Expected a numeric duration in block reason, got: {reason}"
    )


def test_blocked_ip_unblocks_when_timestamp_is_in_the_past():
    """Simulating clock advance by backdating the unblock timestamp."""
    limiter = IPRateLimiter()
    limiter.limits["default"] = {"requests": 1, "window": 60, "block_duration": 60}

    limiter.is_allowed("10.0.0.3", "default")
    limiter.is_allowed("10.0.0.3", "default")  # triggers block

    assert limiter.is_allowed("10.0.0.3", "default")[0] is False

    # Simulate expiry
    limiter.blocked_ips["10.0.0.3"] = time.time() - 1
    limiter.request_buckets["10.0.0.3"].clear()

    allowed, reason = limiter.is_allowed("10.0.0.3", "default")
    assert allowed is True
    assert reason is None


def test_all_configured_endpoint_types_are_present():
    """Verify the three endpoint categories introduced in the codebase still exist."""
    limiter = IPRateLimiter()
    for endpoint_type in ("default", "memory_heavy", "search"):
        assert endpoint_type in limiter.limits, (
            f"Missing expected endpoint type: {endpoint_type}"
        )
