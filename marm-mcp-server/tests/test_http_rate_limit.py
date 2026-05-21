import importlib

from conftest import load_isolated_server, local_client


def test_http_rate_limit_blocks_abuse_and_preserves_public_health(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    rate_limiter_module = importlib.import_module("marm_mcp_server.core.rate_limiter")
    limiter = rate_limiter_module.rate_limiter
    original_limits = {name: config.copy() for name, config in limiter.limits.items()}
    limiter.limits["default"] = {"requests": 2, "window": 60, "block_duration": 60}

    try:
        client = local_client(server.app)

        assert client.get("/marm_log_show").status_code == 200
        assert client.get("/marm_log_show").status_code == 200

        blocked = client.get("/marm_log_show")
        assert blocked.status_code == 429
        assert blocked.json()["error"] == "Rate limit exceeded"
        assert 1 <= int(blocked.headers["Retry-After"]) <= 60

        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"
    finally:
        limiter.limits = original_limits
        limiter.request_buckets.clear()
        limiter.blocked_ips.clear()


def test_memory_heavy_endpoints_use_tighter_rate_limit_than_default(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    rate_limiter_module = importlib.import_module("marm_mcp_server.core.rate_limiter")
    limiter = rate_limiter_module.rate_limiter
    original_limits = {name: config.copy() for name, config in limiter.limits.items()}
    limiter.limits["memory_heavy"] = {"requests": 1, "window": 60, "block_duration": 120}

    try:
        client = local_client(server.app)

        first = client.post(
            "/marm_smart_recall",
            json={"session_name": "rate-test", "query": "anything", "limit": 1},
        )
        assert first.status_code == 200

        blocked = client.post(
            "/marm_smart_recall",
            json={"session_name": "rate-test", "query": "anything", "limit": 1},
        )
        assert blocked.status_code == 429
        assert blocked.json()["error"] == "Rate limit exceeded"
        assert 1 <= int(blocked.headers["Retry-After"]) <= 120
    finally:
        limiter.limits = original_limits
        limiter.request_buckets.clear()
        limiter.blocked_ips.clear()
