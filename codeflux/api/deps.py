from __future__ import annotations

from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.db.models import User
from codeflux.db.session import get_db_session
from codeflux.security.tokens import COOKIE_NAME, decode_access_token
from codeflux.settings import Settings


def get_token_from_request(request: Request) -> str | None:
    """Extract access token from Authorization Bearer header or httpOnly cookie.

    Authorization header takes precedence over cookies.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()

    cookie_token = request.cookies.get(COOKIE_NAME)
    if cookie_token:
        return cookie_token

    return None


async def require_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Dependency that authenticates the user from JWT (cookie or Bearer header).

    Returns the authenticated User model.
    Raises HTTPException 401 with standard /api error envelope if unauthenticated.
    """
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Authentication required"},
        )

    settings = Settings()
    try:
        payload: dict[str, Any] = decode_access_token(token, settings.jwt_secret)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "token_expired", "message": "Authentication token has expired"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "Invalid authentication token"},
        ) from exc

    user_id = payload.get("sub")
    org_id = payload.get("org_id")
    if not user_id or not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "Malformed token payload"},
        )

    stmt = select(User).where(User.id == user_id, User.org_id == org_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "User not found or deleted"},
        )

    return user


async def require_admin(
    current_user: Annotated[User, Depends(require_user)],
) -> User:
    """Dependency that ensures the authenticated user has the 'admin' role.

    Raises HTTPException 403 if the user is not an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "Admin privileges required"},
        )
    return current_user


# Alias for compatibility
get_current_user = require_user
