from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request


async def authenticate(request: Request, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> str:
    supplied = x_api_key or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None)
    for key, team in request.app.state.client_keys.items():
        if supplied and secrets.compare_digest(supplied, key):
            return team
    raise HTTPException(status_code=401, detail="invalid or missing CodeFlux API key")

