"""Auth middleware — mirrors marm-mcp-server/middleware/auth.py."""

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import MARM_API_KEY

# Unlock check + health only; static assets and HTML shell load without a token.
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


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("X-Real-IP")
    if real:
        return real.strip()
    return request.client.host if request.client else ""


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return ""


def is_valid_key(candidate: str) -> bool:
    if not MARM_API_KEY or not candidate:
        return False
    return secrets.compare_digest(candidate, MARM_API_KEY)


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    # GET / serves the UI shell (unlock form is client-side).
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
