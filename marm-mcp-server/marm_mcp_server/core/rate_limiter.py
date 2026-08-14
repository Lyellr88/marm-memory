"""IP-based rate limiting for MARM MCP Server (no authentication required)."""

import threading
import time
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple

from ..config.settings import (
    MARM_RATE_LIMIT_RPM,
    RATE_LIMIT_BLOCK_SECONDS,
    RATE_LIMIT_WINDOW_SECONDS,
)


class IPRateLimiter:
    """Simple IP-based rate limiter for preventing abuse without authentication"""

    def __init__(self) -> None:
        self.request_buckets: Dict[str, deque] = defaultdict(lambda: deque())
        self.blocked_ips: Dict[str, float] = {}  # IP -> unblock_timestamp

        self.cleanup_lock = threading.Lock()
        self.last_cleanup = time.time()

        self.configure(
            requests=MARM_RATE_LIMIT_RPM,
            window=RATE_LIMIT_WINDOW_SECONDS,
            block_duration=RATE_LIMIT_BLOCK_SECONDS,
        )

    def configure(
        self, requests: int, window: int = 60, block_duration: int = 30
    ) -> None:
        """Apply one shared HTTP/MCP rate limit to all endpoint buckets."""
        config = {
            "requests": requests,
            "window": window,
            "block_duration": block_duration,
        }
        self.limits = {
            "default": config.copy(),
            "memory_heavy": config.copy(),
            "search": config.copy(),
        }
        self.request_buckets.clear()
        self.blocked_ips.clear()

    def is_allowed(
        self, client_ip: str, endpoint_type: str = "default"
    ) -> Tuple[bool, Optional[str]]:
        """Check if request is allowed, return (allowed, reason_if_blocked)"""
        current_time = time.time()

        self._cleanup_if_needed(current_time)

        if client_ip in self.blocked_ips:
            unblock_time = self.blocked_ips[client_ip]
            if current_time < unblock_time:
                remaining = int(unblock_time - current_time)
                return (
                    False,
                    f"IP blocked for {remaining} more seconds due to rate limit violation",
                )
            else:
                del self.blocked_ips[client_ip]

        config = self.limits.get(endpoint_type, self.limits["default"])
        if config["requests"] == 0:
            return True, None

        bucket = self.request_buckets[client_ip]

        cutoff_time = current_time - config["window"]
        while bucket and bucket[0] < cutoff_time:
            bucket.popleft()

        if len(bucket) < config["requests"]:
            bucket.append(current_time)
            return True, None
        else:
            self.blocked_ips[client_ip] = current_time + config["block_duration"]
            return (
                False,
                f"Rate limit exceeded: {config['requests']} requests per {config['window']}s. Blocked for {config['block_duration']}s.",
            )

    def _cleanup_if_needed(self, current_time: float) -> None:
        """Clean up old data to prevent memory leaks"""
        if current_time - self.last_cleanup < 300:
            return

        with self.cleanup_lock:
            if current_time - self.last_cleanup < 300:
                return

            expired_blocks = [
                ip
                for ip, unblock_time in self.blocked_ips.items()
                if current_time >= unblock_time
            ]
            for ip in expired_blocks:
                del self.blocked_ips[ip]

            cutoff_time = current_time - 3600  # 1 hour
            ips_to_remove = []

            for ip, bucket in self.request_buckets.items():
                while bucket and bucket[0] < cutoff_time:
                    bucket.popleft()

                if not bucket and ip not in self.blocked_ips:
                    ips_to_remove.append(ip)

            for ip in ips_to_remove:
                del self.request_buckets[ip]

            self.last_cleanup = current_time


rate_limiter = IPRateLimiter()
