"""
API token authentication for audit endpoints.

When API_SECRET_KEY is set, all /audits requests must include the token via
Authorization: Bearer <token> or X-API-Key: <token>. When unset, no auth is required.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status

from shared.config import get_config


def verify_api_token(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    config = get_config()
    if not config.api_secret_key or not config.api_secret_key.strip():
        return

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if not token and x_api_key:
        token = x_api_key.strip()

    if not token or not hmac.compare_digest(token, config.api_secret_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token. Use Authorization: Bearer <token> or X-API-Key: <token>.",
        )
