"""WebSocket rate limiting middleware for MARM MCP Server."""

from fastapi import WebSocket
import time
from core.rate_limiter import rate_limiter

def get_websocket_client_ip(websocket: WebSocket) -> str:
    """Extract client IP from WebSocket connection, handling proxies"""
    # Check for forwarded headers (nginx, CloudFlare, etc.)
    forwarded_for = websocket.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP in the chain (original client)
        return forwarded_for.split(",")[0].strip()
    
    real_ip = websocket.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fallback to direct connection IP
    return websocket.client.host if websocket.client else "unknown"

def determine_websocket_endpoint_type(path: str) -> str:
    """Classify WebSocket endpoint for rate limiting rules"""
    if any(endpoint in path for endpoint in ['/mcp/ws']):
        return 'websocket'
    else:
        return 'default'

async def websocket_rate_limit_middleware(websocket: WebSocket, call_next):
    """Rate limiting middleware for WebSocket connections - prevents abuse while keeping service free"""

    # Skip rate limiting for health/status endpoints
    if websocket.url.path in ['/health', '/ping', '/', '/docs', '/openapi.json']:
        return await call_next(websocket)

    # Get client IP and endpoint type
    client_ip = get_websocket_client_ip(websocket)
    endpoint_type = determine_websocket_endpoint_type(websocket.url.path)

    # Check rate limit
    allowed, reason = rate_limiter.is_allowed(client_ip, endpoint_type)

    if not allowed:
        # For WebSocket rate limiting, we need to accept first, then close
        try:
            await websocket.accept()
            await websocket.close(code=1008, reason=f"Rate limit exceeded: {reason}")
        except:
            # If accept fails, just return
            pass
        return

    # Proceed with WebSocket connection
    await call_next(websocket)