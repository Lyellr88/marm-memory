import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from ..config.settings import MARM_GRAPH_API_KEY

PUBLIC_PATHS = {"/health"}
_DOCS_PATHS = {"/", "/docs", "/redoc", "/openapi.json"}
_DOCS_PREFIXES = ("/openapi",)
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    is_docs_path = path in _DOCS_PATHS or path.startswith(_DOCS_PREFIXES)

    if path in PUBLIC_PATHS or (is_docs_path and not MARM_GRAPH_API_KEY):
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
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    if not secrets.compare_digest(token.encode(), MARM_GRAPH_API_KEY.encode()):
        return JSONResponse(
            status_code=401,
            content={
                "error": "Unauthorized",
                "message": "Valid Authorization: Bearer <MARM_GRAPH_API_KEY> header required.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)
