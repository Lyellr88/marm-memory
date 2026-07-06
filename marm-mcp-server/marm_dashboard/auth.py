"""Auth middleware — mirrors marm-mcp-server/middleware/auth.py."""

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import MARM_API_KEY

PUBLIC_PATHS = {"/health", "/api/auth/unlock"}
PUBLIC_PREFIXES = ("/assets/",)

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self' http://127.0.0.1:8001 http://localhost:8001; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'"
    ),
}


_TRUSTED_PROXY_IPS = {"127.0.0.1", "::1"}


def _client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies.

    X-Forwarded-For/X-Real-IP are only trusted when the direct TCP connection
    comes from a known local proxy -- mirrors marm-mcp-server's own
    middleware/rate_limiting.py get_client_ip(), so a remote caller can't spoof
    127.0.0.1 to bypass the loopback-only auth mode.
    """
    direct_ip = request.client.host if request.client else ""

    if direct_ip in _TRUSTED_PROXY_IPS:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real = request.headers.get("X-Real-IP")
        if real:
            return real.strip()

    return direct_ip


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return ""


def is_valid_key(candidate: str) -> bool:
    if not MARM_API_KEY or not candidate:
        return False
    return secrets.compare_digest(candidate, MARM_API_KEY)


def _mount_relative_path(request: Request) -> str:
    """request.url.path relative to this app's own mount point.

    When this app runs standalone, root_path is "" and this is a no-op. When
    mounted as a sub-app (e.g. at /dashboard inside marm-mcp-server), the ASGI
    scope's root_path carries the mount prefix but path stays the full
    original path -- so comparing raw request.url.path against PUBLIC_PATHS/
    PUBLIC_PREFIXES never matches once mounted, 401-ing every request
    including static assets and the unlock endpoint itself.
    """
    path = request.url.path
    root_path = request.scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        path = path[len(root_path) :] or "/"
    return path


async def auth_middleware(request: Request, call_next):
    path = _mount_relative_path(request)
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    if path == "/" and request.method == "GET":
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    if not MARM_API_KEY:
        if _client_ip(request) not in ("127.0.0.1", "::1", "localhost"):
            response = JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "message": (
                        "Dashboard is reachable on the network but MARM_API_KEY is not set. "
                        "Set the same key as marm-mcp-server, or bind to 127.0.0.1."
                    ),
                },
            )
            response.headers.update(SECURITY_HEADERS)
            return response
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    if not is_valid_key(_bearer_token(request)):
        response = JSONResponse(
            status_code=401,
            content={
                "error": "Unauthorized",
                "message": "Authorization: Bearer <MARM_API_KEY> required (same key as MCP).",
                "auth_required": True,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
        response.headers.update(SECURITY_HEADERS)
        return response

    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response
