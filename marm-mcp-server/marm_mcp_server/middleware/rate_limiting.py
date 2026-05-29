"""Rate limiting middleware for FastAPI."""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import time
from ..core.rate_limiter import rate_limiter
from ..config.settings import RATE_LIMIT_BLOCK_SECONDS

_TRUSTED_PROXY_IPS = {"127.0.0.1", "::1"}

def get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies.

    X-Forwarded-For is only trusted when the direct TCP connection comes from
    a known local proxy — prevents remote callers from spoofing 127.0.0.1.
    """
    direct_ip = request.client.host if request.client else "unknown"

    if direct_ip in _TRUSTED_PROXY_IPS:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

    return direct_ip

def determine_endpoint_type(path: str) -> str:
    """Classify endpoint for rate limiting rules"""
    if path == '/mcp':
        return 'default'
    if any(endpoint in path for endpoint in ['/marm_smart_recall']):
        return 'memory_heavy'
    elif any(endpoint in path for endpoint in ['/marm_summary', '/search']):
        return 'search'  
    else:
        return 'default'

async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware - prevents abuse while keeping service free"""

    # Skip rate limiting for health/status endpoints
    if request.url.path in ['/health', '/ping', '/', '/docs', '/openapi.json', '/ready']:
        return await call_next(request)

    # Get client IP and endpoint type
    client_ip = get_client_ip(request)
    endpoint_type = determine_endpoint_type(request.url.path)
    
    # Check rate limit
    allowed, reason = rate_limiter.is_allowed(client_ip, endpoint_type)
    
    if not allowed:
        retry_after = RATE_LIMIT_BLOCK_SECONDS
        if client_ip in rate_limiter.blocked_ips:
            retry_after = max(1, int(rate_limiter.blocked_ips[client_ip] - time.time()))
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "message": reason,
                "retry_after": retry_after,
                "client_ip": client_ip,
                "timestamp": time.time()
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Remaining": "0"
            }
        )
    
    # Add rate limit headers to response
    response = await call_next(request)
    
    # Add informational headers (optional, for debugging)
    response.headers["X-RateLimit-Applied"] = "true"
    response.headers["X-Client-IP"] = client_ip
    
    return response
