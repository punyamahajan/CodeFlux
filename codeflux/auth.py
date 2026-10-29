from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Query, Request


def supplied_key(
    authorization: str | None, x_api_key: str | None, x_goog_api_key: str | None, key: str | None
) -> str | None:
    """Accept a CodeFlux key wherever OpenAI, Anthropic, or Gemini clients put theirs."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_api_key or x_goog_api_key or key


async def authenticate(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    x_goog_api_key: str | None = Header(default=None),
    key: str | None = Query(default=None, include_in_schema=False),
) -> str:
    supplied = supplied_key(authorization, x_api_key, x_goog_api_key, key)
    if supplied:
        dynamic = await request.app.state.client_key_repository.authenticate(supplied)
        if dynamic:
            limit = dynamic["monthly_token_limit"]
            used = await request.app.state.usage_repository.tokens_this_month(str(dynamic["team"]))
            if limit is not None and used >= limit:
                raise HTTPException(status_code=429, detail="monthly CodeFlux token budget exhausted")
            request.state.client_identity = dynamic
            return str(dynamic["team"])
    for key_value, team in request.app.state.client_keys.items():
        if supplied and secrets.compare_digest(supplied, key_value):
            request.state.client_identity = {"team": team, "name": team, "monthly_token_limit": None}
            return team
    raise HTTPException(status_code=401, detail="invalid or missing CodeFlux API key")
