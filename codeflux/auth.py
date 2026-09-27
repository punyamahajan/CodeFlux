from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request


async def authenticate(request: Request, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> str:
    supplied = x_api_key or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None)
    if supplied:
        dynamic = await request.app.state.client_key_repository.authenticate(supplied)
        if dynamic:
            limit = dynamic["monthly_token_limit"]
            used = await request.app.state.usage_repository.tokens_this_month(str(dynamic["team"]))
            if limit is not None and used >= limit:
                raise HTTPException(status_code=429, detail="monthly CodeFlux token budget exhausted")
            request.state.client_identity = dynamic
            return str(dynamic["team"])
    for key, team in request.app.state.client_keys.items():
        if supplied and secrets.compare_digest(supplied, key):
            request.state.client_identity = {"team": team, "name": team, "monthly_token_limit": None}
            return team
    raise HTTPException(status_code=401, detail="invalid or missing CodeFlux API key")
