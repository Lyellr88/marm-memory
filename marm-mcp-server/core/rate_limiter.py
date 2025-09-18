"""IP-based rate limiting for MARM MCP Server (no authentication required)."""

import time
import threading
from typing import Dict, Optional, Tuple
from collections import defaultdict, deque

class IPRateLimiter:
    """Simple IP-based rate limiter for preventing abuse without authentication"""
    
    def __init__(self):
        # Rate limiting buckets per IP
        self.request_buckets: Dict[str, deque] = defaultdict(lambda: deque())
        self.blocked_ips: Dict[str, float] = {}  # IP -> unblock_timestamp
        
        # Cleanup thread for memory management
        self.cleanup_lock = threading.Lock()
        self.last_cleanup = time.time()
        
        # Rate limiting configuration
        self.limits = {
            # Standard endpoints - generous limits for normal use
            'default': {
                'requests': 60,        # 60 requests
                'window': 60,          # per minute
                'block_duration': 300  # 5 minute cooldown
            },
            # Memory-intensive endpoints - tighter limits
            'memory_heavy': {
                'requests': 20,        # 20 requests  
                'window': 60,          # per minute
                'block_duration': 600  # 10 minute cooldown
            },
            # Search endpoints - moderate limits
            'search': {
                'requests': 30,        # 30 requests
                'window': 60,          # per minute  
                'block_duration': 300  # 5 minute cooldown
            }
        }
    
    def is_allowed(self, client_ip: str, endpoint_type: str = 'default') -> Tuple[bool, Optional[str]]:
        """Check if request is allowed, return (allowed, reason_if_blocked)"""
        current_time = time.time()
        
        # Clean up old data periodically
        self._cleanup_if_needed(current_time)
        
        # Check if IP is currently blocked
        if client_ip in self.blocked_ips:
            unblock_time = self.blocked_ips[client_ip]
            if current_time < unblock_time:
                remaining = int(unblock_time - current_time)
                return False, f"IP blocked for {remaining} more seconds due to rate limit violation"
            else:
                # Unblock the IP
                del self.blocked_ips[client_ip]
        
        # Get rate limit config for this endpoint type
        config = self.limits.get(endpoint_type, self.limits['default'])
        
        # Get request bucket for this IP
        bucket = self.request_buckets[client_ip]
        
        # Remove requests outside the time window
        cutoff_time = current_time - config['window']
        while bucket and bucket[0] < cutoff_time:
            bucket.popleft()
        
        # Check if under limit
        if len(bucket) < config['requests']:
            bucket.append(current_time)
            return True, None
        else:
            # Rate limit exceeded, block IP
            self.blocked_ips[client_ip] = current_time + config['block_duration']
            return False, f"Rate limit exceeded: {config['requests']} requests per {config['window']}s. Blocked for {config['block_duration']}s."
    
    def _cleanup_if_needed(self, current_time: float):
        """Clean up old data to prevent memory leaks"""
        # Only cleanup every 5 minutes
        if current_time - self.last_cleanup < 300:
            return
        
        with self.cleanup_lock:
            # Double-check after acquiring lock
            if current_time - self.last_cleanup < 300:
                return
            
            # Clean up expired blocks
            expired_blocks = [ip for ip, unblock_time in self.blocked_ips.items() 
                             if current_time >= unblock_time]
            for ip in expired_blocks:
                del self.blocked_ips[ip]
            
            # Clean up old request buckets (older than 1 hour)
            cutoff_time = current_time - 3600  # 1 hour
            ips_to_remove = []
            
            for ip, bucket in self.request_buckets.items():
                # Remove old requests
                while bucket and bucket[0] < cutoff_time:
                    bucket.popleft()
                
                # Remove empty buckets for IPs not seen in last hour
                if not bucket and ip not in self.blocked_ips:
                    ips_to_remove.append(ip)
            
            for ip in ips_to_remove:
                del self.request_buckets[ip]
            
            self.last_cleanup = current_time
    
    def get_stats(self) -> Dict:
        """Get rate limiting statistics for monitoring"""
        current_time = time.time()
        
        active_ips = len([ip for ip, bucket in self.request_buckets.items() if bucket])
        blocked_ips = len([ip for ip, unblock_time in self.blocked_ips.items() 
                          if current_time < unblock_time])
        
        return {
            'active_ips': active_ips,
            'blocked_ips': blocked_ips,
            'total_tracked_ips': len(self.request_buckets),
            'memory_usage_estimate': f"{len(self.request_buckets) * 100}B"  # Rough estimate
        }

# Global rate limiter instance
rate_limiter = IPRateLimiter()