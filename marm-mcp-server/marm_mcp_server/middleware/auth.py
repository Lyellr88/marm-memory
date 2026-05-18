"""Authentication middleware for MARM MCP Server."""

from fastapi import Request
from fastapi.responses import JSONResponse
from ..config.settings import MARM_API_KEY

PUBLIC_PATHS = {'/health', '/ready', '/ping', '/', '/docs', '/redoc', '/openapi.json'}
PUBLIC_PREFIXES = ('/openapi',)


async def auth_middleware(request: Request, call_next):
    """
    Two-mode auth gate:
      - No MARM_API_KEY set: loopback-only (127.0.0.1 / ::1). Safe default for local deployments.
      - MARM_API_KEY set: require Authorization: Bearer <key> on all non-public routes.
    """
    if request.url.path in PUBLIC_PATHS or request.url.path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)

    if not MARM_API_KEY:
        client_ip = request.client.host if request.client else ""
        # Note: behind a reverse proxy (nginx, Traefik) or Docker bridge, client.host
        # will be the proxy/bridge IP (172.x.x.x, 10.x.x.x), not loopback.
        # Set MARM_API_KEY to switch to Bearer token mode for those deployments.
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "message": (
                        "This server is bound to a network interface but no MARM_API_KEY "
                        "is configured. Set MARM_API_KEY to enable remote access, or bind "
                        "to 127.0.0.1 for local-only use."
                    )
                }
            )
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer ") or auth_header[7:] != MARM_API_KEY:
        return JSONResponse(
            status_code=401,
            content={
                "error": "Unauthorized",
                "message": "Valid Authorization: Bearer <MARM_API_KEY> header required."
            },
            headers={"WWW-Authenticate": "Bearer"}
        )

    return await call_next(request)
