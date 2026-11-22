from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

DEFAULT_TOKEN_EXPIRE_HOURS = 12
TOKEN_ALGORITHM = "HS256"
COOKIE_NAME = "access_token"
COOKIE_MAX_AGE = DEFAULT_TOKEN_EXPIRE_HOURS * 3600


def create_access_token(
    data: dict[str, Any],
    secret: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token using HS256 with 12 hours lifetime by default."""
    to_encode = data.copy()
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(hours=DEFAULT_TOKEN_EXPIRE_HOURS))
    to_encode.update({"iat": int(now.timestamp()), "exp": int(expire.timestamp())})
    return jwt.encode(to_encode, secret, algorithm=TOKEN_ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    """Decode and verify a signed JWT access token.

    Raises jwt.ExpiredSignatureError if expired, or jwt.InvalidTokenError if invalid.
    """
    return jwt.decode(token, secret, algorithms=[TOKEN_ALGORITHM])
