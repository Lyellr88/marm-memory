"""Rate limiting middleware for FastAPI."""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import time
from core.rate_limiter import rate_limiter

def get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies"""
    # Check for forwarded headers (nginx, CloudFlare, etc.)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP in the chain (original client)
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fallback to direct connection IP
    return request.client.host if request.client else "unknown"

def determine_endpoint_type(path: str) -> str:
    """Classify endpoint for rate limiting rules"""
    if any(endpoint in path for endpoint in ['/marm_smart_recall', '/marm_context_bridge']):
        return 'memory_heavy'
    elif any(endpoint in path for endpoint in ['/marm_summary', '/search']):
        return 'search'  
    else:
        return 'default'

async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware - prevents abuse while keeping service free"""
    
    # Skip rate limiting for health/status endpoints
    if request.url.path in ['/health', '/ping', '/', '/docs', '/openapi.json']:
        return await call_next(request)
    
    # Get client IP and endpoint type
    client_ip = get_client_ip(request)
    endpoint_type = determine_endpoint_type(request.url.path)
    
    # Check rate limit
    allowed, reason = rate_limiter.is_allowed(client_ip, endpoint_type)
    
    if not allowed:
        # Return rate limit error
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "message": reason,
                "retry_after": "See message for details",
                "client_ip": client_ip,
                "timestamp": time.time()
            },
            headers={
                "Retry-After": "300",  # Suggest retry after 5 minutes
                "X-RateLimit-Remaining": "0"
            }
        )
    
    # Add rate limit headers to response
    response = await call_next(request)
    
    # Add informational headers (optional, for debugging)
    response.headers["X-RateLimit-Applied"] = "true"
    response.headers["X-Client-IP"] = client_ip
    
    return response