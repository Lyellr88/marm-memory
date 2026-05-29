from marm_mcp_server.core.rate_limiter import IPRateLimiter


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


def test_rate_limiter_can_be_disabled_with_zero_rpm():
    limiter = IPRateLimiter()
    limiter.configure(requests=0, window=60, block_duration=30)

    for _ in range(100):
        assert limiter.is_allowed("203.0.113.30", "default") == (True, None)

    assert limiter.blocked_ips == {}
