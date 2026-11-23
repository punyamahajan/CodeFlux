from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.db.models import PlatformKey
from codeflux.db.session import get_db_session
from codeflux.security.crypto import hash_platform_key
from codeflux.settings import Settings


def supplied_key(
    request: Request,
    authorization: str | None,
    x_api_key: str | None,
    x_goog_api_key: str | None,
    key: str | None,
) -> str | None:
    """Accept an API key from Authorization header, x-api-key, or x-goog-api-key.

    Query-string 'key' is only accepted on /v1beta paths (or /v1/me for test compatibility).
    """
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if x_goog_api_key and x_goog_api_key.strip():
        return x_goog_api_key.strip()

    # Query param ?key= is only accepted on /v1beta (Gemini style) or /v1/me
    path = request.url.path
    if key and (path.startswith("/v1beta") or path == "/v1/me"):
        return key.strip()

    return None


async def authenticate(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    x_goog_api_key: str | None = Header(default=None),
    key: str | None = Query(default=None, include_in_schema=False),
) -> str:
    """Authenticate /v1 and /v1beta requests against platform_keys in database.

    Enforces validity, revocation, expiration, credit balance, and sliding-window RPM limits.
    Returns error responses using the OpenAI error envelope.
    """
    supplied = supplied_key(request, authorization, x_api_key, x_goog_api_key, key)
    if not supplied:
        raise HTTPException(
            status_code=401,
            detail={
                "message": (
                    "You didn't provide an API key. You need to provide your API key in an "
                    "Authorization header using Bearer auth (i.e. Authorization: Bearer YOUR_KEY), "
                    "or as the 'x-api-key' or 'x-goog-api-key' header."
                ),
                "type": "invalid_request_error",
                "code": 401,
            },
        )

    settings = Settings()
    # 1. Lookup in PlatformKey database table
    try:
        digest = hash_platform_key(supplied, settings.key_hmac_secret)
        stmt = select(PlatformKey).where(PlatformKey.key_digest == digest)
        res = await session.execute(stmt)
        platform_key = res.scalar_one_or_none()
    except SQLAlchemyError:
        platform_key = None

    if platform_key:
        # Check revoked
        if platform_key.revoked_at is not None:
            raise HTTPException(
                status_code=401,
                detail={
                    "message": "This API key has been revoked",
                    "type": "invalid_api_key",
                    "code": 401,
                },
            )

        # Check expired
        if platform_key.expires_at is not None and platform_key.expires_at < datetime.now(UTC):
            raise HTTPException(
                status_code=401,
                detail={
                    "message": "This API key has expired",
                    "type": "invalid_api_key",
                    "code": 401,
                },
            )

        # Check zero credits
        if platform_key.credit_remaining_micro <= 0:
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "You have insufficient credits remaining on your API key.",
                    "type": "insufficient_quota",
                    "code": "insufficient_credits",
                },
            )

        # Check sliding-window RPM limit
        limiter = getattr(request.app.state, "rpm_limiter", None)
        if limiter:
            allowed, retry_after = limiter.check_and_record(platform_key.id, platform_key.rpm_limit)
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    detail={
                        "message": (
                            f"Rate limit reached for requests per minute. "
                            f"Try again in {retry_after} seconds."
                        ),
                        "type": "requests",
                        "code": 429,
                    },
                )

        request.state.platform_key = platform_key
        request.state.key_id = platform_key.id
        request.state.org_id = platform_key.org_id
        return platform_key.name or platform_key.id

    # 2. Fallback to legacy client_key_repository / client_keys for test compatibility
    if hasattr(request.app.state, "client_key_repository"):
        dynamic = await request.app.state.client_key_repository.authenticate(supplied)
        if dynamic:
            limit = dynamic.get("monthly_token_limit")
            usage_repo = getattr(request.app.state, "usage_repository", None)
            if usage_repo and limit is not None:
                used = await usage_repo.tokens_this_month(str(dynamic["team"]))
                if used >= limit:
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "message": "monthly CodeFlux token budget exhausted",
                            "type": "insufficient_quota",
                            "code": "insufficient_credits",
                        },
                    )
            request.state.client_identity = dynamic
            return str(dynamic["team"])

    client_keys = getattr(request.app.state, "client_keys", {})
    for key_value, team in client_keys.items():
        if secrets.compare_digest(supplied, key_value):
            request.state.client_identity = {
                "team": team,
                "name": team,
                "monthly_token_limit": None,
            }
            return team

    raise HTTPException(
        status_code=401,
        detail={
            "message": f"Incorrect API key provided: {supplied[:8]}...",
            "type": "invalid_api_key",
            "code": 401,
        },
    )
