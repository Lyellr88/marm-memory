"""
MARM MCP Server - Mock OAuth Endpoints
This module provides mock OAuth 2.0 endpoints for local development and testing.
The OAuth implementation is for demonstration purposes and should not be used
in production environments.
Author: Lyell - MARM Systems
Version: 2.2.5
"""
from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import JSONResponse, RedirectResponse
from typing import Optional
import uuid
import time
import hashlib
import urllib.parse

router = APIRouter()

# Mock OAuth configuration - matches documentation
MOCK_CLIENT_ID = "local_client_b6f3a01e"
MOCK_CLIENT_SECRET = "local_secret_ad6703cd2b4243ab"
MOCK_SCOPES = ["read", "write"]

# Simple in-memory storage for development
auth_codes = {}
access_tokens = {}

def generate_auth_code(client_id: str, redirect_uri: str, scope: str) -> str:
    """Generate a mock authorization code."""
    code = f"auth_code_{uuid.uuid4().hex[:16]}"
    auth_codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "expires_at": time.time() + 600,  # 10 minutes
        "used": False
    }
    return code

def generate_access_token(client_id: str, scope: str) -> str:
    """Generate a mock access token."""
    token = f"marm_token_{uuid.uuid4().hex[:24]}"
    access_tokens[token] = {
        "client_id": client_id,
        "scope": scope,
        "expires_at": time.time() + 3600,  # 1 hour
        "token_type": "Bearer"
    }
    return token

@router.get("/oauth/authorize", include_in_schema=False)
async def oauth_authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    scope: str = "read write",
    state: Optional[str] = None
):
    """
    Mock OAuth authorization endpoint.

    For local development, this automatically grants authorization
    and redirects with an authorization code.
    """
    # Validate client_id
    if client_id != MOCK_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid client_id"
        )

    # Validate response_type
    if response_type != "code":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported response_type. Only 'code' is supported."
        )

    # Validate scope
    requested_scopes = scope.split()
    if not all(s in MOCK_SCOPES for s in requested_scopes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope. Supported scopes: {', '.join(MOCK_SCOPES)}"
        )

    # Generate authorization code
    auth_code = generate_auth_code(client_id, redirect_uri, scope)

    # Build redirect URL with authorization code
    params = {"code": auth_code}
    if state:
        params["state"] = state

    redirect_url = f"{redirect_uri}?{urllib.parse.urlencode(params)}"

    return RedirectResponse(url=redirect_url, status_code=302)

@router.post("/oauth/token", include_in_schema=False)
async def oauth_token(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: str = Form(...),
    client_secret: str = Form(...)
):
    """
    Mock OAuth token endpoint.

    Exchanges authorization codes for access tokens.
    """
    # Validate client credentials
    if client_id != MOCK_CLIENT_ID or client_secret != MOCK_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid client credentials"
        )

    if grant_type == "authorization_code":
        # Validate authorization code
        if not code or code not in auth_codes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or missing authorization code"
            )

        auth_data = auth_codes[code]

        # Check if code is expired
        if time.time() > auth_data["expires_at"]:
            del auth_codes[code]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authorization code expired"
            )

        # Check if code was already used
        if auth_data["used"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authorization code already used"
            )

        # Validate redirect_uri
        if redirect_uri != auth_data["redirect_uri"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid redirect_uri"
            )

        # Mark code as used
        auth_codes[code]["used"] = True

        # Generate access token
        access_token = generate_access_token(client_id, auth_data["scope"])

        # Clean up used authorization code
        del auth_codes[code]

        return JSONResponse({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": auth_data["scope"]
        })

    elif grant_type == "client_credentials":
        # Direct client credentials grant
        access_token = generate_access_token(client_id, "read write")

        return JSONResponse({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read write"
        })

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported grant_type"
        )

@router.get("/oauth/userinfo", include_in_schema=False)
async def oauth_userinfo(request: Request):
    """
    Mock OAuth user info endpoint.

    Returns basic user information for authenticated requests.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header"
        )

    token = auth_header.split(" ", 1)[1]

    if token not in access_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token"
        )

    token_data = access_tokens[token]

    # Check if token is expired
    if time.time() > token_data["expires_at"]:
        del access_tokens[token]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token expired"
        )

    return JSONResponse({
        "sub": "marm_local_user",
        "name": "MARM Local User",
        "email": "user@localhost",
        "scope": token_data["scope"]
    })

@router.post("/oauth/revoke", include_in_schema=False)
async def oauth_revoke(
    token: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...)
):
    """
    Mock OAuth token revocation endpoint.
    """
    # Validate client credentials
    if client_id != MOCK_CLIENT_ID or client_secret != MOCK_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid client credentials"
        )

    # Remove token if it exists
    if token in access_tokens:
        del access_tokens[token]

    return JSONResponse({"success": True})

@router.get("/oauth/debug", include_in_schema=False)
async def oauth_debug():
    """
    Debug endpoint to view current OAuth state (development only).
    """
    current_time = time.time()

    # Clean up expired codes and tokens
    expired_codes = [code for code, data in auth_codes.items() if current_time > data["expires_at"]]
    for code in expired_codes:
        del auth_codes[code]

    expired_tokens = [token for token, data in access_tokens.items() if current_time > data["expires_at"]]
    for token in expired_tokens:
        del access_tokens[token]

    return JSONResponse({
        "client_id": MOCK_CLIENT_ID,
        "supported_scopes": MOCK_SCOPES,
        "active_auth_codes": len(auth_codes),
        "active_access_tokens": len(access_tokens),
        "endpoints": {
            "authorization": "/oauth/authorize",
            "token": "/oauth/token",
            "userinfo": "/oauth/userinfo",
            "revoke": "/oauth/revoke"
        }
    })