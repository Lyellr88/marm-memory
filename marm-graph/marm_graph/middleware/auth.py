"""Authentication middleware for marm-graph.

Same two-mode gate as marm-mcp-server: loopback-only when no key is set, Bearer
required when a key is set. This is what makes "UI-only" REST endpoints actually
safe on the wire — they are HTTP-facing, so they go through this gate too.
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from ..config.settings import MARM_GRAPH_API_KEY

PUBLIC_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json"}
PUBLIC_PREFIXES = ("/openapi",)
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


async def auth_middleware(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS or request.url.path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)

    if not MARM_GRAPH_API_KEY:
        client_ip = request.client.host if request.client else ""
        if client_ip not in _LOOPBACK:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "message": (
                        "marm-graph is reachable over a network interface but no "
                        "MARM_GRAPH_API_KEY is configured. Set MARM_GRAPH_API_KEY for "
                        "remote access, or bind to 127.0.0.1 for local-only use."
                    ),
                },
            )
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer ") or auth_header[7:] != MARM_GRAPH_API_KEY:
        return JSONResponse(
            status_code=401,
            content={
                "error": "Unauthorized",
                "message": "Valid Authorization: Bearer <MARM_GRAPH_API_KEY> header required.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)
